"""Persistent public notice, provenance, and collection status models."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Notice(Base):
    __tablename__ = "notices"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_notice_source_external"),
        Index("ix_notice_region_date", "region_code", "announcement_date"),
        Index("ix_notice_fingerprint", "fingerprint"),
        Index("ix_notice_category", "category"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    external_id: Mapped[str] = mapped_column(String(240), nullable=False)
    correction_of_external_id: Mapped[str | None] = mapped_column(String(240))
    correction_of_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("notices.id"))
    provider: Mapped[str | None] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False, default="other")
    address: Mapped[str | None] = mapped_column(String(500))
    region_code: Mapped[str | None] = mapped_column(String(32))
    region_name: Mapped[str | None] = mapped_column(String(160))
    announcement_date: Mapped[date | None] = mapped_column(Date)
    official_url: Mapped[str | None] = mapped_column(Text)
    document_hash: Mapped[str | None] = mapped_column(String(128))
    price_cap_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    rules: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    rules_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    duplicate_of_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("notices.id"), nullable=True)

    events: Mapped[list[NoticeEvent]] = relationship(
        back_populates="notice", cascade="all, delete-orphan", lazy="selectin", order_by="NoticeEvent.id"
    )
    prices: Mapped[list[UnitPrice]] = relationship(
        back_populates="notice", cascade="all, delete-orphan", lazy="selectin", order_by="UnitPrice.id"
    )
    revisions: Mapped[list[NoticeRevision]] = relationship(
        back_populates="notice", cascade="all, delete-orphan", lazy="selectin", order_by="NoticeRevision.version"
    )
    competitions: Mapped[list[UnitCompetition]] = relationship(
        back_populates="notice", cascade="all, delete-orphan", lazy="selectin", order_by="UnitCompetition.id"
    )
    competition_state: Mapped[CompetitionState | None] = relationship(
        back_populates="notice", cascade="all, delete-orphan", lazy="selectin", uselist=False
    )


class NoticeEvent(Base):
    __tablename__ = "notice_events"
    __table_args__ = (Index("ix_event_dates", "start_date", "end_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    notice_id: Mapped[str] = mapped_column(ForeignKey("notices.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(80), nullable=False, default="other")
    label: Mapped[str] = mapped_column(String(240), nullable=False, default="접수")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    audience: Mapped[str | None] = mapped_column(String(240))

    notice: Mapped[Notice] = relationship(back_populates="events")


class UnitPrice(Base):
    __tablename__ = "unit_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    notice_id: Mapped[str] = mapped_column(ForeignKey("notices.id", ondelete="CASCADE"), nullable=False, index=True)
    unit_type: Mapped[str] = mapped_column(String(120), nullable=False)
    area_sqm: Mapped[float | None] = mapped_column(Float)
    price_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="sale")
    amount_krw: Mapped[int | None] = mapped_column(BigInteger)
    monthly_krw: Mapped[int | None] = mapped_column(BigInteger)
    basis_label: Mapped[str | None] = mapped_column(String(240))
    verification: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    evidence_url: Mapped[str | None] = mapped_column(Text)
    evidence_text: Mapped[str | None] = mapped_column(Text)
    document_hash: Mapped[str | None] = mapped_column(String(128))

    notice: Mapped[Notice] = relationship(back_populates="prices")


class NoticeRevision(Base):
    __tablename__ = "notice_revisions"
    __table_args__ = (UniqueConstraint("notice_id", "version", name="uq_notice_revision"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    notice_id: Mapped[str] = mapped_column(ForeignKey("notices.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    notice: Mapped[Notice] = relationship(back_populates="revisions")


class IntegrationSetting(Base):
    """Server-only credentials; never included in public notice serializers."""

    __tablename__ = "integration_settings"
    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class SourceStatus(Base):
    __tablename__ = "source_status"

    source: Mapped[str] = mapped_column(String(80), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    message: Mapped[str | None] = mapped_column(Text)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    record_count: Mapped[int | None] = mapped_column(Integer)


class CollectionRun(Base):
    """Shared singleton lease for manual and scheduled public-feed collection."""

    __tablename__ = "collection_runs"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    job_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="idle")
    trigger: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message: Mapped[str | None] = mapped_column(String(240))


class DocumentExtractionState(Base):
    """Durable free-tier cooldown across worker restarts and deployments."""

    __tablename__ = "document_extraction_state"

    source: Mapped[str] = mapped_column(String(80), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    audited_on: Mapped[date | None] = mapped_column(Date)
    deferred_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UnitCompetition(Base):
    """Current official figures; textual rates and closure evidence are retained."""

    __tablename__ = "unit_competitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    notice_id: Mapped[str] = mapped_column(ForeignKey("notices.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="cheongyak_competition")
    unit_type: Mapped[str] = mapped_column(String(120), nullable=False)
    model_no: Mapped[str | None] = mapped_column(String(80))
    rank: Mapped[int | None] = mapped_column(Integer)
    residence_area: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    residence_area_label: Mapped[str | None] = mapped_column(String(80))
    supply_type: Mapped[str] = mapped_column(String(80), nullable=False, default="general")
    supply_type_label: Mapped[str | None] = mapped_column(String(120))
    resident_priority: Mapped[str | None] = mapped_column(String(32))
    supply_count: Mapped[int | None] = mapped_column(Integer)
    application_count: Mapped[int | None] = mapped_column(Integer)
    competition_rate: Mapped[str] = mapped_column(String(120), nullable=False, default="-")
    result_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    result_text: Mapped[str | None] = mapped_column(String(500))
    evidence_url: Mapped[str] = mapped_column(Text, nullable=False)
    verification: Mapped[str] = mapped_column(String(32), nullable=False, default="official")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    notice: Mapped[Notice] = relationship(back_populates="competitions")


class CompetitionState(Base):
    """A failed latest attempt invalidates exclusions while preserving evidence."""

    __tablename__ = "competition_state"

    notice_id: Mapped[str] = mapped_column(ForeignKey("notices.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    proof_invalidated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    unit_types: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_url: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)

    notice: Mapped[Notice] = relationship(back_populates="competition_state")


class CompetitionRevision(Base):
    """Changed official result snapshots, independent of notice revisions."""

    __tablename__ = "competition_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    notice_id: Mapped[str] = mapped_column(ForeignKey("notices.id", ondelete="CASCADE"), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
