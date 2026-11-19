"""Бизнес-логика: создание кампании и правка офферов."""
import re
import secrets

from sqlalchemy.orm import Session

from . import config
from .keitaro import KeitaroClient, KeitaroError
from .models import CampaignRecord, OfferChange

GEO_RE = re.compile(r"^[A-Za-z]{2}$")
EDITABLE_TYPES = ("regular", "default")


def create_campaign(
    db: Session,
    kt: KeitaroClient,
    name: str,
    geo: str,
    offer_id: int,
    domain_id: int,
    group_id: int,
    source_id: int,
) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("Название кампании пустое")
    if not GEO_RE.match(geo.strip()):
        raise ValueError("Гео-код: две латинские буквы, например PL")
    geo = geo.strip().upper()
    kt.offer(offer_id)  # 404 от Keitaro, если оффера нет

    campaign = kt.create_campaign({
        "name": name,
        "type": "position",
        "alias": f"{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}-{secrets.token_hex(3)}",
        "domain_id": domain_id,
        "group_id": group_id,
        "traffic_source_id": source_id,
        "state": "active",
        "cost_type": "CPC",
        "cost_value": 0,
        "cost_currency": "USD",
        "cost_auto": True,
        "uniqueness_method": "ip",
        "uniqueness_use_cookies": True,
        "cookies_ttl": 24,
    })
    cid = campaign["id"]
    try:
        kt.create_stream({
            "campaign_id": cid,
            "type": "regular",
            "name": f"Geo {geo} → Google",
            "position": 1,
            "schema": "action",
            "action_type": "http",
            "action_payload": "https://google.com",
            "collect_clicks": True,
            "filter_or": False,
            "state": "active",
            "filters": [{"name": "country", "mode": "accept", "payload": [geo]}],
        })
        kt.create_stream({
            "campaign_id": cid,
            "type": "default",
            "name": "Default offers",
            "position": 2,
            "schema": "landings",
            "action_type": "http",
            "collect_clicks": True,
            "state": "active",
            "offer_selection": "before_click",
            "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
        })
    except KeitaroError:
        kt.delete_campaign(cid)  # не оставляем кампанию без потоков
        raise

    db.add(CampaignRecord(keitaro_id=cid, name=name, geo=geo, offer_id=offer_id))
    db.commit()
    return campaign


def offers_stream(kt: KeitaroClient, campaign_id: int) -> dict:
    streams = kt.streams(campaign_id)
    for s in streams:
        if s["type"] == "default" and s.get("schema") == "landings":
            return s
    for s in streams:
        if s.get("schema") == "landings":
            return s
    raise LookupError("В кампании нет потока с офферами")


def _shares(count: int) -> list[int]:
    """Делит 100% поровну, остаток уходит первым офферам."""
    if count == 0:
        return []
    base, rest = divmod(100, count)
    return [base + (1 if i < rest else 0) for i in range(count)]


def _write_offers(kt: KeitaroClient, stream: dict, offer_ids: list[int]) -> None:
    shares = _shares(len(offer_ids))
    kt.update_stream(stream["id"], {
        "offers": [
            {"offer_id": oid, "share": sh, "state": "active"}
            for oid, sh in zip(offer_ids, shares)
        ],
    })


def add_offer(db: Session, kt: KeitaroClient, campaign_id: int, offer_id: int) -> None:
    kt.offer(offer_id)
    stream = offers_stream(kt, campaign_id)
    ids = [o["offer_id"] for o in stream["offers"]]
    if offer_id in ids:
        raise ValueError("Оффер уже есть в кампании")
    _write_offers(kt, stream, ids + [offer_id])
    db.add(OfferChange(campaign_id=campaign_id, offer_id=offer_id, action="add"))
    db.commit()


def remove_offer(db: Session, kt: KeitaroClient, campaign_id: int, offer_id: int) -> None:
    stream = offers_stream(kt, campaign_id)
    ids = [o["offer_id"] for o in stream["offers"]]
    if offer_id not in ids:
        raise ValueError("Оффера нет в кампании")
    _write_offers(kt, stream, [i for i in ids if i != offer_id])
    db.add(OfferChange(campaign_id=campaign_id, offer_id=offer_id, action="remove"))
    db.commit()


def _rescale(others: list[tuple[int, int]], total: int) -> list[int]:
    """Раскладывает total по долям others пропорционально, сумма точная."""
    weights = [sh for _, sh in others]
    if not sum(weights):
        weights = [1] * len(others)
    raw = [w * total / sum(weights) for w in weights]
    out = [int(r) for r in raw]
    order = sorted(range(len(raw)), key=lambda i: raw[i] - out[i], reverse=True)
    for i in order[: total - sum(out)]:
        out[i] += 1
    return out


def set_share(db: Session, kt: KeitaroClient, campaign_id: int, offer_id: int, share: int) -> None:
    """Ставит оффера долю share, остальные пересчитываются пропорционально."""
    stream = offers_stream(kt, campaign_id)
    offers = [(o["offer_id"], o["share"]) for o in stream["offers"]]
    if offer_id not in [i for i, _ in offers]:
        raise ValueError("Оффера нет в кампании")
    others = [(i, sh) for i, sh in offers if i != offer_id]
    if not 1 <= share <= 100:
        raise ValueError("Доля от 1 до 100")
    if not others and share != 100:
        raise ValueError("Единственный оффер получает 100%")
    if others and share == 100:
        raise ValueError("Остальным офферам нужна доля, максимум 99")
    new = dict(zip([i for i, _ in others], _rescale(others, 100 - share))) if others else {}
    new[offer_id] = share
    kt.update_stream(stream["id"], {
        "offers": [{"offer_id": i, "share": new[i], "state": "active"} for i, _ in offers],
    })
    db.add(OfferChange(campaign_id=campaign_id, offer_id=offer_id, action=f"share={share}"))
    db.commit()


def campaign_offers(kt: KeitaroClient, campaign_id: int, interval: str = "all_time") -> list[dict]:
    """Офферы кампании с реальной статистикой из отчёта Keitaro."""
    stream = offers_stream(kt, campaign_id)
    stats = {r["offer_id"]: r for r in kt.offer_report(campaign_id, interval)["rows"]}
    out = []
    for o in stream["offers"]:
        info = kt.offer(o["offer_id"])
        s = stats.get(o["offer_id"], {})
        out.append({
            "offer_id": o["offer_id"],
            "name": info["name"],
            "share": o["share"],
            "state": o["state"],
            "clicks": s.get("clicks", 0),
            "conversions": s.get("conversions", 0),
            "revenue": s.get("revenue", 0),
            "cost": s.get("cost", 0),
            "profit": s.get("profit", 0),
            "roi": s.get("roi", 0),
            "cr": s.get("cr", 0),
        })
    return out
