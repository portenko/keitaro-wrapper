from pathlib import Path

import secrets

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import config, services
from .db import get_db
from .keitaro import KeitaroClient, KeitaroError
from .models import CampaignRecord

app = FastAPI(title="Keitaro wrapper")
STATIC = Path(__file__).parent / "static"


def get_keitaro() -> KeitaroClient:
    return KeitaroClient()


@app.exception_handler(KeitaroError)
def keitaro_error(_, exc: KeitaroError):
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": f"Keitaro: {exc.detail}"}, status_code=502 if exc.status >= 500 else 400)


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    geo: str
    offer_id: int
    domain_id: int
    group_id: int
    source_id: int


class OfferIn(BaseModel):
    offer_id: int


class ShareIn(BaseModel):
    share: int


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """Включается, если заданы BASIC_AUTH_USER и BASIC_AUTH_PASSWORD."""
    from base64 import b64decode
    from fastapi.responses import Response
    if not config.BASIC_AUTH_USER:
        return await call_next(request)
    try:
        user, _, pwd = b64decode(request.headers.get("authorization", "")[6:]).decode().partition(":")
    except Exception:
        user = pwd = ""
    if secrets.compare_digest(user, config.BASIC_AUTH_USER) and secrets.compare_digest(pwd, config.BASIC_AUTH_PASSWORD):
        return await call_next(request)
    return Response("Нужен вход", status_code=401, headers={"WWW-Authenticate": 'Basic realm="keitaro-wrapper"'})


@app.get("/api/meta")
def meta(kt: KeitaroClient = Depends(get_keitaro)):
    return {
        "domains": [{"id": d["id"], "name": d["name"]} for d in kt.domains() if d.get("state") == "active"],
        "groups": [{"id": g["id"], "name": g["name"]} for g in kt.groups("campaigns")],
        "sources": [{"id": s["id"], "name": s["name"]} for s in kt.traffic_sources()],
        "defaults": {
            "domain_id": config.DEFAULT_DOMAIN_ID,
            "group_id": config.DEFAULT_GROUP_ID,
            "source_id": config.DEFAULT_SOURCE_ID,
            "prefix": config.CAMPAIGN_PREFIX,
        },
    }


@app.get("/api/offers")
def offers(q: str = "", page: int = 1, per_page: int = 20, kt: KeitaroClient = Depends(get_keitaro)):
    per_page = min(max(per_page, 1), 100)
    rows = kt.offers(search=q or None, limit=per_page, offset=(max(page, 1) - 1) * per_page)
    return [{"id": o["id"], "name": o["name"], "country": o.get("country")} for o in rows]


@app.post("/api/campaigns", status_code=201)
def create_campaign(body: CampaignIn, db: Session = Depends(get_db), kt: KeitaroClient = Depends(get_keitaro)):
    try:
        c = services.create_campaign(db, kt, **body.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"id": c["id"], "name": c["name"], "alias": c.get("alias")}


@app.get("/api/campaigns")
def list_campaigns(q: str = "", page: int = 1, per_page: int = 20, kt: KeitaroClient = Depends(get_keitaro)):
    per_page = min(max(per_page, 1), 100)
    rows = kt.campaigns(search=q or None, limit=per_page + 1, offset=(max(page, 1) - 1) * per_page)
    return {
        "items": [
            {"id": c["id"], "name": c["name"], "state": c["state"], "group": c.get("group")}
            for c in rows[:per_page]
        ],
        "has_more": len(rows) > per_page,
    }


@app.get("/api/campaigns/{campaign_id}")
def get_campaign(campaign_id: int, interval: str = "all_time", db: Session = Depends(get_db),
                 kt: KeitaroClient = Depends(get_keitaro)):
    c = kt.campaign(campaign_id)
    try:
        offers_ = services.campaign_offers(kt, campaign_id, interval)
    except LookupError as e:
        raise HTTPException(404, str(e))
    rec = db.query(CampaignRecord).filter_by(keitaro_id=campaign_id).first()
    return {
        "id": c["id"], "name": c["name"], "state": c["state"],
        "domain": c.get("domain"), "group": c.get("group"),
        "created_here": bool(rec), "offers": offers_,
        "totals": {k: round(sum(o[k] for o in offers_), 2)
                   for k in ("clicks", "conversions", "revenue", "cost", "profit")},
    }


@app.post("/api/campaigns/{campaign_id}/offers", status_code=201)
def add_offer(campaign_id: int, body: OfferIn, db: Session = Depends(get_db),
              kt: KeitaroClient = Depends(get_keitaro)):
    try:
        services.add_offer(db, kt, campaign_id, body.offer_id)
    except (ValueError, LookupError) as e:
        raise HTTPException(422, str(e))
    return {"ok": True}


@app.put("/api/campaigns/{campaign_id}/offers/{offer_id}")
def set_share(campaign_id: int, offer_id: int, body: ShareIn, db: Session = Depends(get_db),
              kt: KeitaroClient = Depends(get_keitaro)):
    try:
        services.set_share(db, kt, campaign_id, offer_id, body.share)
    except (ValueError, LookupError) as e:
        raise HTTPException(422, str(e))
    return {"ok": True}


@app.delete("/api/campaigns/{campaign_id}/offers/{offer_id}")
def remove_offer(campaign_id: int, offer_id: int, db: Session = Depends(get_db),
                 kt: KeitaroClient = Depends(get_keitaro)):
    try:
        services.remove_offer(db, kt, campaign_id, offer_id)
    except (ValueError, LookupError) as e:
        raise HTTPException(422, str(e))
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
