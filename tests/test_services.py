import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import services
from app.db import Base
from app.keitaro import KeitaroClient, KeitaroError
from app.models import CampaignRecord, OfferChange


class FakeKeitaro(KeitaroClient):
    """Хранит потоки в памяти, как это делает Keitaro."""

    def __init__(self, offers=(1, 2, 3, 4)):
        self.known = set(offers)
        self.streams_ = {}
        self.deleted = []
        self.fail_second_stream = False
        self.next_id = 100

    def offer(self, offer_id):
        if offer_id not in self.known:
            raise KeitaroError(404, "no offer")
        return {"id": offer_id, "name": f"Offer {offer_id}"}

    def create_campaign(self, payload):
        self.campaign_payload = payload
        return {"id": 7, "name": payload["name"], "alias": payload["alias"]}

    def create_stream(self, payload):
        if self.fail_second_stream and payload["type"] == "default":
            raise KeitaroError(400, "boom")
        self.next_id += 1
        s = {**payload, "id": self.next_id, "offers": payload.get("offers", [])}
        self.streams_.setdefault(payload["campaign_id"], []).append(s)
        return s

    def delete_campaign(self, campaign_id):
        self.deleted.append(campaign_id)

    def streams(self, campaign_id):
        return self.streams_[campaign_id]

    def update_stream(self, stream_id, payload):
        for ss in self.streams_.values():
            for s in ss:
                if s["id"] == stream_id:
                    s["offers"] = [{**o, "stream_id": stream_id} for o in payload["offers"]]

    def offer_report(self, campaign_id, interval="all_time"):
        return {"rows": [{"offer_id": 1, "clicks": 10, "conversions": 2, "revenue": 5.5,
                          "cost": 1, "profit": 4.5, "roi": 450, "cr": 20}]}


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def make(db, kt, **over):
    args = dict(name="test_x_1", geo="pl", offer_id=1, domain_id=1, group_id=2, source_id=3)
    args.update(over)
    return services.create_campaign(db, kt, **args)


def test_create_builds_two_streams(db):
    kt = FakeKeitaro()
    make(db, kt)
    geo, default = kt.streams_[7]
    assert geo["filters"] == [{"name": "country", "mode": "accept", "payload": ["PL"]}]
    assert geo["action_payload"] == "https://google.com" and geo["position"] == 1
    assert default["offers"] == [{"offer_id": 1, "share": 100, "state": "active"}]
    p = kt.campaign_payload
    assert (p["domain_id"], p["group_id"], p["traffic_source_id"]) == (1, 2, 3)
    rec = db.query(CampaignRecord).one()
    assert (rec.keitaro_id, rec.geo, rec.offer_id) == (7, "PL", 1)


@pytest.mark.parametrize("geo", ["", "P", "POL", "1a"])
def test_bad_geo_rejected(db, geo):
    with pytest.raises(ValueError):
        make(db, FakeKeitaro(), geo=geo)


def test_empty_name_rejected(db):
    with pytest.raises(ValueError):
        make(db, FakeKeitaro(), name="  ")


def test_unknown_offer_creates_nothing(db):
    kt = FakeKeitaro()
    with pytest.raises(KeitaroError):
        make(db, kt, offer_id=99)
    assert kt.streams_ == {}


def test_stream_failure_rolls_campaign_back(db):
    kt = FakeKeitaro()
    kt.fail_second_stream = True
    with pytest.raises(KeitaroError):
        make(db, kt)
    assert kt.deleted == [7]
    assert db.query(CampaignRecord).count() == 0


def test_add_offer_splits_shares_evenly(db):
    kt = FakeKeitaro()
    make(db, kt)
    for oid in (2, 3):
        services.add_offer(db, kt, 7, oid)
    shares = [(o["offer_id"], o["share"]) for o in kt.streams_[7][1]["offers"]]
    assert shares == [(1, 34), (2, 33), (3, 33)]
    assert sum(s for _, s in shares) == 100
    assert db.query(OfferChange).filter_by(action="add").count() == 2


def test_add_duplicate_rejected(db):
    kt = FakeKeitaro()
    make(db, kt)
    with pytest.raises(ValueError):
        services.add_offer(db, kt, 7, 1)


def test_remove_offer_redistributes(db):
    kt = FakeKeitaro()
    make(db, kt)
    services.add_offer(db, kt, 7, 2)
    services.remove_offer(db, kt, 7, 1)
    assert [(o["offer_id"], o["share"]) for o in kt.streams_[7][1]["offers"]] == [(2, 100)]
    with pytest.raises(ValueError):
        services.remove_offer(db, kt, 7, 1)


def test_campaign_offers_joins_stats(db):
    kt = FakeKeitaro()
    make(db, kt)
    services.add_offer(db, kt, 7, 2)
    a, b = services.campaign_offers(kt, 7)
    assert (a["clicks"], a["conversions"], a["profit"]) == (10, 2, 4.5)
    assert (b["clicks"], b["name"]) == (0, "Offer 2")


def test_client_raises_on_http_error():
    t = httpx.MockTransport(lambda r: httpx.Response(403, json={"error": "no"}))
    with pytest.raises(KeitaroError) as e:
        KeitaroClient("https://x", "k", transport=t).domains()
    assert e.value.status == 403


def test_set_share_rescales_others_to_100(db):
    kt = FakeKeitaro()
    make(db, kt)
    for oid in (2, 3):
        services.add_offer(db, kt, 7, oid)  # 34/33/33
    services.set_share(db, kt, 7, 1, 50)
    shares = {o["offer_id"]: o["share"] for o in kt.streams_[7][1]["offers"]}
    assert shares[1] == 50 and sum(shares.values()) == 100
    assert sorted((shares[2], shares[3])) == [25, 25]
    services.set_share(db, kt, 7, 2, 10)
    shares = {o["offer_id"]: o["share"] for o in kt.streams_[7][1]["offers"]}
    assert shares[2] == 10 and sum(shares.values()) == 100


@pytest.mark.parametrize("share", [0, 101, 100])
def test_set_share_bounds(db, share):
    kt = FakeKeitaro()
    make(db, kt)
    services.add_offer(db, kt, 7, 2)
    with pytest.raises(ValueError):
        services.set_share(db, kt, 7, 1, share)


def test_single_offer_must_be_100(db):
    kt = FakeKeitaro()
    make(db, kt)
    with pytest.raises(ValueError):
        services.set_share(db, kt, 7, 1, 60)


def test_rescale_exact_sum():
    for total in (1, 7, 50, 99):
        assert sum(services._rescale([(1, 34), (2, 33), (3, 33)], total)) == total
    assert sum(services._rescale([(1, 0), (2, 0)], 100)) == 100


def test_search_filters_by_name_and_id_and_pages():
    rows = [{"id": i, "name": f"camp_{'portenko' if i % 2 else 'other'}_{i}"} for i in range(1, 11)]
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(200, json=rows)

    kt = KeitaroClient("https://x", "k", transport=httpx.MockTransport(handler))
    kt._cache = {}
    assert [r["id"] for r in kt.campaigns("PORTENKO", limit=3)] == [1, 3, 5]
    assert [r["id"] for r in kt.campaigns("portenko", limit=3, offset=3)] == [7, 9]
    assert [r["id"] for r in kt.campaigns("10")] == [10]
    assert len(calls) == 1  # один запрос к Keitaro, остальное из кэша
