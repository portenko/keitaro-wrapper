from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CampaignRecord(Base):
    """Кампании, созданные через эту обёртку."""

    __tablename__ = "campaign_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    geo: Mapped[str] = mapped_column(String(2))
    offer_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class OfferChange(Base):
    """Журнал добавления и удаления офферов в кампаниях."""

    __tablename__ = "offer_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(Integer, index=True)
    offer_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))  # add | remove | share=N
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
