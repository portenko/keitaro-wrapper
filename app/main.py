from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
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
def offers(q: str = "", kt: KeitaroClient = Depends(get_keitaro)):
    return [
        {"id": o["id"], "name": o["name"], "country": o.get("country")}
        for o in kt.offers(search=q or None)
    ]


@app.post("/api/campaigns", status_code=201)
def create_campaign(body: CampaignIn, db: Session = Depends(get_db), kt: KeitaroClient = Depends(get_keitaro)):
    try:
        c = services.create_campaign(db, kt, **body.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"id": c["id"], "name": c["name"], "alias": c.get("alias")}


@app.get("/api/campaigns")
def list_campaigns(q: str = "", kt: KeitaroClient = Depends(get_keitaro)):
    return [
        {"id": c["id"], "name": c["name"], "state": c["state"], "group": c.get("group")}
        for c in kt.campaigns(search=q or None)
    ]


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
