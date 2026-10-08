"""Stable public API response shapes. No user profile is accepted by the API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: str
    label: str
    start_date: date
    end_date: date | None = None
    audience: str | None = None


class PricePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    unit_type: str
    area_sqm: float | None = None
    exclusive_area_sqm: float | None = None
    area_basis: str | None = None
    price_kind: str
    amount_krw: int | None = None
    monthly_krw: int | None = None
    basis_label: str | None = None
    verification: str
    evidence_url: str | None = None
    evidence_text: str | None = None
    document_hash: str | None = None


class CompetitionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    unit_type: str
    model_no: str | None = None
    rank: int | None = None
    residence_area: str
    residence_area_label: str | None = None
    supply_type: str = "general"
    supply_type_label: str | None = None
    resident_priority: str | None = None
    supply_count: int | None = None
    application_count: int | None = None
    competition_rate: str
    result_status: str
    result_text: str | None = None
    evidence_url: str
    verification: str
    observed_at: datetime


class CompetitionStatePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str = "pending"
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    complete: bool = False
    proof_invalidated: bool = False
    unit_types: list[str] = Field(default_factory=list)
    evidence_url: str | None = None
    message: str | None = None


class HousingKindEvidencePublic(BaseModel):
    verification: str = "unknown"
    source: str | None = None
    evidence_url: str | None = None
    evidence_text: str | None = None


class RankApplicabilityPublic(HousingKindEvidencePublic):
    status: str = "unknown"
    account_required: bool | None = None
    reason: str | None = None
    document_hash: str | None = None


class ApplicationMethodEvidencePublic(HousingKindEvidencePublic):
    document_hash: str | None = None
    criterion_date: date | None = None


class QualificationContextPublic(BaseModel):
    public_housing: bool | None = None
    speculation_zone: bool | None = None
    subscription_overheated: bool | None = None
    weakened_area: bool | None = None
    capital_region: bool | None = None
    rule_effective_date: date | None = None
    original_announcement_date: date | None = None
    application_announcement_date: date | None = None
    application_criterion_date: date | None = None
    application_criterion_basis: str | None = None


class OfferedSupplyPublic(BaseModel):
    supply_type: str
    unit_type: str | None = None
    supply_count: int | None = None
    verification: str = "official"
    evidence_url: str | None = None
    evidence_text: str | None = None
    evidence_page: int | None = None
    document_hash: str | None = None
    criterion_date: date | None = None


class ContractSchedulePublic(BaseModel):
    status: str = "unknown"
    start_date: date | None = None
    end_date: date | None = None
    verification: str = "unknown"
    source: str | None = None
    evidence_url: str | None = None
    evidence_text: str | None = None
    evidence_page: int | None = None
    document_hash: str | None = None
    source_hash: str | None = None
    evidence_location: str | None = None


class NoticePublic(BaseModel):
    id: str
    source: str
    sources: list[str] = Field(default_factory=list)
    correction_of_external_id: str | None = None
    correction_of_id: str | None = None
    provider: str | None = None
    title: str
    category: str
    housing_kind: str = "unknown"
    housing_kind_evidence: HousingKindEvidencePublic | None = None
    rank_applicability: RankApplicabilityPublic = Field(default_factory=RankApplicabilityPublic)
    application_method: str = "unknown"
    application_method_evidence: ApplicationMethodEvidencePublic | None = None
    qualification_context: QualificationContextPublic = Field(default_factory=QualificationContextPublic)
    contract_schedule: ContractSchedulePublic = Field(default_factory=ContractSchedulePublic)
    offered_supplies: list[OfferedSupplyPublic] | None = None
    selection_methods: list[dict[str, Any]] = Field(default_factory=list)
    winning_scores: list[dict[str, Any]] = Field(default_factory=list)
    address: str | None = None
    region_code: str | None = None
    region_name: str | None = None
    announcement_date: date | None = None
    sort_date: date | None = None
    application_end_date: date | None = None
    official_url: str | None = None
    document_hash: str | None = None
    price_cap_status: str
    events: list[EventPublic] = Field(default_factory=list)
    prices: list[PricePublic] = Field(default_factory=list)
    competitions: list[CompetitionPublic] = Field(default_factory=list)
    competition: CompetitionStatePublic = Field(default_factory=CompetitionStatePublic)
    rules: list[dict[str, Any]] = Field(default_factory=list)
    rules_complete: bool = False
    updated_at: datetime | None = None
    version: int


class RevisionPublic(BaseModel):
    version: int
    seen_at: datetime
    content_hash: str


class NoticeDetail(NoticePublic):
    revisions: list[RevisionPublic] = Field(default_factory=list)


class NoticePage(BaseModel):
    items: list[NoticePublic]
    total: int
    page: int
    page_size: int


class SourceStatusPublic(BaseModel):
    source: str
    status: str
    message: str | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    record_count: int | None = None


class CoveragePublic(BaseModel):
    sources: list[SourceStatusPublic]


class HealthPublic(BaseModel):
    status: str
