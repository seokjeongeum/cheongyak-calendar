"""Normalized ingestion and read helpers for public notice data."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session

from app.models import CompetitionRevision, CompetitionState, Notice, NoticeEvent, NoticeRevision, SourceStatus, UnitCompetition, UnitPrice, utc_now
from app.schemas import CompetitionPublic, CompetitionStatePublic, EventPublic, NoticeDetail, NoticePublic, PricePublic, RevisionPublic
from app.supply_classification import reviewed_supply_classification
from app.qualification import public_selection_methods, public_winning_scores, is_metadata, merge_poll_rules, public_application_method, public_classification, public_contract_schedule, public_offered_supplies, public_rank_applicability, requirements_complete


PRICE_CAP_STATUSES = {"yes", "no", "unknown", "not_applicable"}
PRICE_KINDS = {"sale", "sale_max", "sale_total", "deposit", "rent", "deposit_monthly"}
VERIFICATIONS = {"official", "ai_unverified", "unknown"}
SOURCE_IDS = ("cheongyak_home", "myhome", "lh", "ih", "sh", "gh", "cheongyak_competition")
NON_APPLICATION_KINDS = {"announcement", "contract", "result", "winner"}
OPEN_RECEPTION_PATTERN = r"상시|마감\s*시|소진\s*시|종료일\s*미공개"
NON_APPLICATION_LABEL_PATTERN = r"당첨자 발표|계약일|계약 체결"


def _date(value: date | str | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _datetime(value: datetime | str | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.replace(tzinfo=ZoneInfo("Asia/Seoul")) if result.tzinfo is None else result


def _string(value: Any, limit: int | None = None) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result[:limit] if limit else result


def _nonnegative_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    result = int(value)
    if result < 0:
        raise ValueError("Price amounts cannot be negative")
    return result


def _json_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _existing_payload(notice: Notice) -> dict[str, Any]:
    return {
        "source": notice.source,
        "external_id": notice.external_id,
        "correction_of_external_id": notice.correction_of_external_id,
        "provider": notice.provider,
        "title": notice.title,
        "category": notice.category,
        "address": notice.address,
        "region_code": notice.region_code,
        "region_name": notice.region_name,
        "announcement_date": notice.announcement_date,
        "official_url": notice.official_url,
        "document_hash": notice.document_hash,
        "price_cap_status": notice.price_cap_status,
        "rules_complete": notice.rules_complete,
        "events": [
            {
                "kind": event.kind,
                "label": event.label,
                "start_date": event.start_date,
                "end_date": event.end_date,
                "audience": event.audience,
            }
            for event in notice.events
        ],
        "prices": [
            {
                "unit_type": price.unit_type,
                "area_sqm": price.area_sqm,
                "price_kind": price.price_kind,
                "amount_krw": price.amount_krw,
                "monthly_krw": price.monthly_krw,
                "basis_label": price.basis_label,
                "verification": price.verification,
                "evidence_url": price.evidence_url,
                "evidence_text": price.evidence_text,
                "document_hash": price.document_hash,
            }
            for price in notice.prices
        ],
        "rules": notice.rules,
    }


def _normalize(payload: dict[str, Any], prior: Notice | None) -> dict[str, Any]:
    base = _existing_payload(prior) if prior else {}
    document_changed = bool(prior and (
        (payload.get("document_hash") is not None and payload["document_hash"] != prior.document_hash)
        or (payload.get("official_url") is not None and payload["official_url"] != prior.official_url)
    ))
    for key, value in payload.items():
        if value is None:
            continue
        if key in {"prices", "rules"} and value == [] and prior and not payload.get(f"replace_{key}"):
            continue
        base[key] = value
    if prior and payload.get("rules") and not payload.get("replace_rules"):
        previous_rules = _json_safe(prior.rules or [])
        if document_changed:
            previous_rules = [rule for rule in previous_rules if rule.get("verification") not in {"ai_unverified", "auto_unverified"}
                              and rule.get("source") != "official_document_parser"]
        incoming_rules = _json_safe(base["rules"])
        if document_changed:
            # Enrichment callers may carry the prior rules through an unreadable
            # corrected PDF. Never attach those verified facts to the new hash.
            # API facts are independent of the attachment and remain available.
            incoming_rules = [rule for rule in incoming_rules if rule.get("source") != "official_document_parser"
                              or (payload.get("document_hash") and rule.get("document_hash") == payload["document_hash"])]
        if prior.announcement_date:
            for rule in incoming_rules:
                if rule.get("kind") == "qualification_context" and isinstance(rule.get("value"), dict):
                    original_date = _date(rule["value"].get("original_announcement_date"))
                    rule["value"]["original_announcement_date"] = min(original_date, prior.announcement_date).isoformat() if original_date else prior.announcement_date.isoformat()
        base["rules"] = merge_poll_rules(previous_rules, incoming_rules, metadata_only=all(is_metadata(rule) for rule in incoming_rules))
    if prior and document_changed:
        for key in ("prices", "rules"):
            if key not in payload or (payload[key] == [] and not payload.get(f"replace_{key}")):
                base[key] = [item for item in base[key] if item.get("verification") not in {"ai_unverified", "auto_unverified"}]
        base["rules"] = [rule for rule in base["rules"] if rule.get("source") != "official_document_parser"
                         or (payload.get("document_hash") and rule.get("document_hash") == payload["document_hash"])]
    elif prior:
        # A normal source poll can update official values without erasing
        # document-derived candidates from the unchanged document.
        for key in ("prices", "rules"):
            if payload.get(key):
                old_ai = [item for item in _existing_payload(prior)[key] if item.get("verification") in {"ai_unverified", "auto_unverified"}]
                merged = list(base[key])
                for candidate in old_ai:
                    if key == "prices":
                        same_type = lambda item: item.get("unit_type") == candidate.get("unit_type")
                        same_kind = lambda item: item.get("price_kind") == candidate.get("price_kind")
                        if any(same_type(item) and same_kind(item) and item.get("verification") == "official"
                               and (item.get("amount_krw") is not None or item.get("monthly_krw") is not None)
                               for item in merged):
                            continue
                        blank_index = next((index for index, item in enumerate(merged)
                            if same_type(item) and item.get("verification") == "unknown"
                            and item.get("amount_krw") is None and item.get("monthly_krw") is None
                            and (same_kind(item) or
                                 {item.get("price_kind"), candidate.get("price_kind")} <= {"deposit", "deposit_monthly"})
                        ), None)
                        if blank_index is not None:
                            merged[blank_index] = candidate
                            continue
                    encoded = json.dumps(_json_safe(candidate), sort_keys=True, ensure_ascii=False)
                    if all(json.dumps(_json_safe(item), sort_keys=True, ensure_ascii=False) != encoded for item in merged):
                        merged.append(candidate)
                base[key] = merged

    source = _string(base.get("source"), 80)
    external_id = _string(base.get("external_id"), 240)
    title = _string(base.get("title"), 500)
    if not source or not external_id or not title:
        raise ValueError("source, external_id, and title are required")

    cap_status = _string(base.get("price_cap_status")) or "unknown"
    if cap_status not in PRICE_CAP_STATUSES:
        raise ValueError(f"Invalid price_cap_status: {cap_status}")

    events = []
    for raw in base.get("events") or []:
        start = _date(raw.get("start_date"))
        if start is None:
            continue
        end = _date(raw.get("end_date"))
        if end is not None and end < start:
            raise ValueError("Event end_date precedes start_date")
        events.append({
            "kind": _string(raw.get("kind"), 80) or "other",
            "label": _string(raw.get("label"), 240) or "접수",
            "start_date": start.isoformat(),
            "end_date": end.isoformat() if end else None,
            "audience": _string(raw.get("audience"), 240),
        })

    prices = []
    for raw in base.get("prices") or []:
        unit_type = _string(raw.get("unit_type"), 120)
        if not unit_type:
            continue
        kind = _string(raw.get("price_kind"), 32) or "sale"
        if kind not in PRICE_KINDS:
            raise ValueError(f"Invalid price_kind: {kind}")
        verification = _string(raw.get("verification"), 32) or "unknown"
        if verification == "auto_unverified":
            verification = "ai_unverified"
        if verification not in VERIFICATIONS:
            verification = "unknown"
        prices.append({
            "unit_type": unit_type,
            "area_sqm": float(raw["area_sqm"]) if raw.get("area_sqm") not in (None, "") else None,
            "price_kind": kind,
            "amount_krw": _nonnegative_int(raw.get("amount_krw")),
            "monthly_krw": _nonnegative_int(raw.get("monthly_krw")),
            "basis_label": _string(raw.get("basis_label"), 240),
            "verification": verification,
            "evidence_url": _string(raw.get("evidence_url")),
            "evidence_text": _string(raw.get("evidence_text")),
            "document_hash": _string(raw.get("document_hash"), 128),
        })

    rules = _json_safe(base.get("rules") or [])
    if not isinstance(rules, list) or any(not isinstance(rule, dict) for rule in rules):
        raise ValueError("rules must be a list of objects")
    rules_complete = requirements_complete(rules, bool(base.get("rules_complete", False)))

    return {
        "source": source,
        "external_id": external_id,
        "correction_of_external_id": _string(base.get("correction_of_external_id"), 240),
        "provider": _string(base.get("provider"), 160),
        "title": title,
        "category": _string(base.get("category"), 80) or "other",
        "address": _string(base.get("address"), 500),
        "region_code": _string(base.get("region_code"), 32),
        "region_name": _string(base.get("region_name"), 160),
        "announcement_date": _date(base.get("announcement_date")).isoformat() if _date(base.get("announcement_date")) else None,
        "official_url": _string(base.get("official_url")),
        "document_hash": _string(base.get("document_hash"), 128),
        "price_cap_status": cap_status,
        "rules_complete": rules_complete,
        "events": events,
        "prices": prices,
        "rules": rules,
    }


def _fingerprint(payload: dict[str, Any]) -> str | None:
    title = re.sub(r"[^0-9a-z가-힣]", "", payload["title"].lower())
    address = re.sub(r"[^0-9a-z가-힣]", "", (payload.get("address") or "").lower())
    date_text = payload.get("announcement_date")
    if not title or not address or not date_text:
        return None
    return hashlib.sha256(f"{title}|{address}|{date_text}".encode()).hexdigest()


def _resolve_correction(session: Session, notice: Notice) -> Notice | None:
    """Connect a correction after its predecessor has reached this database."""
    reference = notice.correction_of_external_id
    if not reference:
        return None
    previous = session.scalar(select(Notice).where(
        Notice.source == notice.source, Notice.external_id == reference,
        Notice.id != notice.id,
    ).limit(1))
    if previous is None:
        # MyHome's beforePblancId identifies the announcement, while its
        # fetched rows can append houseSn. Resolve only an unambiguous row.
        candidates = session.scalars(select(Notice).where(
            Notice.source == notice.source,
            Notice.external_id.startswith(f"{reference}:", autoescape=True),
            Notice.id != notice.id,
        )).all()
        previous = candidates[0] if len(candidates) == 1 else None
    if previous is not None:
        notice.correction_of_id = previous.id
        if notice.duplicate_of_id == canonical_id(previous):
            notice.duplicate_of_id = None
    return previous


def resolve_pending_corrections(session: Session, source: str) -> int:
    """Resolve newest-first board rows during the same collection cycle."""
    resolved = 0
    pending = session.scalars(select(Notice).where(
        Notice.source == source, Notice.correction_of_external_id.is_not(None),
        Notice.correction_of_id.is_(None),
    )).all()
    for notice in pending:
        if _resolve_correction(session, notice) is not None:
            resolved += 1
    if resolved:
        session.flush()
    return resolved


def lock_notice(session: Session, source: str, external_id: str) -> Notice | None:
    """Serialize writers and reload retained ORM objects before merging updates.

    A transaction advisory lock covers the first insertion, where a row lock
    cannot yet exist. SELECT FOR UPDATE also coordinates existing-row writers;
    populate_existing refreshes selectin children cached across worker commits.
    The caller owns the transaction and releases the locks on commit/rollback.
    """
    with session.no_autoflush:
        if session.get_bind().dialect.name == "postgresql":
            identity = json.dumps([source, external_id], ensure_ascii=False, separators=(",", ":"))
            lock_key = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big", signed=True)
            session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})
        return session.scalar(select(Notice).where(
            Notice.source == source, Notice.external_id == external_id,
        ).with_for_update().execution_options(populate_existing=True))


def upsert_notice(session: Session, payload: dict[str, Any]) -> Notice:
    """Create/update a notice and keep every changed source version.

    The caller owns the transaction and must commit. Identical repeated polls only
    advance last_seen_at. Source updates preserve omitted fields, so a document
    enrichment job can add prices/rules without erasing fetched schedule data.
    """
    source = _string(payload.get("source"), 80)
    external_id = _string(payload.get("external_id"), 240)
    if not source or not external_id:
        raise ValueError("source and external_id are required")
    notice = lock_notice(session, source, external_id)
    normalized = _normalize(payload, notice)
    correction_reference = normalized.get("correction_of_external_id")
    if correction_reference:
        previous = session.scalar(select(Notice).where(Notice.source == source, Notice.external_id == correction_reference).limit(1))
        if previous is None:
            candidates = session.scalars(select(Notice).where(Notice.source == source, Notice.external_id.startswith(f"{correction_reference}:", autoescape=True))).all()
            previous = candidates[0] if len(candidates) == 1 else None
        if previous is not None:
            original_dates = [previous.announcement_date.isoformat()] if previous.announcement_date else []
            for rule in previous.rules or []:
                if rule.get("kind") == "qualification_context" and isinstance(rule.get("value"), dict):
                    raw = _date(rule["value"].get("original_announcement_date"))
                    if raw:
                        original_dates.append(raw.isoformat())
            for rule in normalized["rules"]:
                if rule.get("kind") == "qualification_context" and isinstance(rule.get("value"), dict) and original_dates:
                    raw = _date(rule["value"].get("original_announcement_date"))
                    rule["value"]["original_announcement_date"] = min([*original_dates, *([raw.isoformat()] if raw else [])])
    content_hash = hashlib.sha256(json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    fingerprint = _fingerprint(normalized)
    observed_at = utc_now()
    updated_at = _datetime(payload.get("updated_at"))

    if notice is not None and notice.content_hash == content_hash:
        notice.last_seen_at = observed_at
        if updated_at is not None:
            notice.updated_at = updated_at
        if notice.correction_of_external_id and notice.correction_of_id is None:
            _resolve_correction(session, notice)
        session.flush()
        return notice

    if notice is None:
        notice = Notice(source=source, external_id=external_id, content_hash=content_hash, version=1)
        session.add(notice)
    else:
        notice.version += 1
        previous_payload = _json_safe(_existing_payload(notice))
        competition_identity_fields = (
            "correction_of_external_id", "official_url", "announcement_date",
            "title", "category", "address", "region_code", "region_name",
        )
        previous_applications = [event for event in previous_payload["events"] if event["kind"] not in NON_APPLICATION_KINDS]
        current_applications = [event for event in normalized["events"] if event["kind"] not in NON_APPLICATION_KINDS]
        previous_units = {price["unit_type"] for price in previous_payload["prices"]}
        current_units = {price["unit_type"] for price in normalized["prices"]}
        # Qualification parsing is a service enrichment, not a change to the
        # official reception or competition table. Preserve fresh results for
        # rule-only updates and the first document hash we discover. A known
        # document replacement still requests revalidation conservatively.
        replaced_document = bool(notice.document_hash and normalized["document_hash"]
                                 and notice.document_hash != normalized["document_hash"])
        competition_changed = (
            any(previous_payload[field] != normalized[field] for field in competition_identity_fields)
            or previous_applications != current_applications
            or previous_units != current_units
            or replaced_document
        )
        if notice.competition_state is not None and competition_changed:
            notice.competition_state.status = "pending"
            notice.competition_state.complete = False
            notice.competition_state.message = "공고 변경 후 경쟁률 재확인 대기"
            notice.competition_state.proof_invalidated = True

    for key in (
        "provider", "title", "category", "address", "region_code", "region_name",
        "official_url", "document_hash", "price_cap_status", "rules", "rules_complete",
    ):
        setattr(notice, key, normalized[key])
    notice.announcement_date = _date(normalized["announcement_date"])
    notice.content_hash = content_hash
    notice.fingerprint = fingerprint
    notice.last_seen_at = observed_at
    if updated_at is not None:
        notice.updated_at = updated_at
    notice.correction_of_external_id = normalized["correction_of_external_id"]
    previous = _resolve_correction(session, notice)
    if previous is None:
        notice.correction_of_id = None

    # A matching official URL or an exact title/address/date fingerprint is a
    # safe cross-source duplicate. Preserve the secondary row and its evidence.
    other = None
    previous_root_id = canonical_id(previous) if previous is not None else None
    if fingerprint:
        other = session.scalar(select(Notice).where(
            Notice.fingerprint == fingerprint, Notice.source != source,
            Notice.duplicate_of_id.is_(None), Notice.id != notice.id,
            Notice.id != previous_root_id,
        ).limit(1))
    if other is None and normalized["official_url"]:
        other = session.scalar(select(Notice).where(
            Notice.official_url == normalized["official_url"], Notice.source != source,
            Notice.duplicate_of_id.is_(None), Notice.id != notice.id,
            Notice.id != previous_root_id,
        ).limit(1))
    notice.duplicate_of_id = other.id if other is not None else None

    notice.events = [NoticeEvent(
        kind=event["kind"], label=event["label"], start_date=_date(event["start_date"]),
        end_date=_date(event["end_date"]), audience=event["audience"],
    ) for event in normalized["events"]]
    notice.prices = [UnitPrice(**price) for price in normalized["prices"]]
    session.flush()
    session.add(NoticeRevision(notice_id=notice.id, version=notice.version, content_hash=content_hash, payload=normalized))
    session.flush()
    return notice


def record_source_status(
    session: Session,
    source: str,
    status: str,
    message: str | None = None,
    fetched_at: datetime | None = None,
    record_count: int | None = None,
) -> SourceStatus:
    """Record attempted collection, retaining the previous successful time."""
    if not source:
        raise ValueError("source is required")
    if status not in {"ok", "partial", "error", "pending", "running", "disabled"}:
        raise ValueError(f"Invalid source status: {status}")
    row = session.get(SourceStatus, source)
    if row is None:
        row = SourceStatus(source=source)
        session.add(row)
    attempted_at = _datetime(fetched_at) or utc_now()
    row.status = status
    row.message = message
    row.last_attempt_at = attempted_at
    if status in {"ok", "partial"}:
        row.last_success_at = attempted_at
    if record_count is not None:
        row.record_count = record_count
    session.flush()
    return row


def source_coverage(session: Session) -> list[SourceStatus]:
    rows = {row.source: row for row in session.scalars(select(SourceStatus)).all()}
    return [rows.get(source, SourceStatus(source=source, status="pending", message="아직 수집되지 않았습니다.")) for source in SOURCE_IDS] + [
        row for source, row in sorted(rows.items()) if source not in SOURCE_IDS
    ]


def canonical_id(notice: Notice) -> str:
    return notice.duplicate_of_id or notice.id


def record_competition_result(
    session: Session, notice: Notice, status: str, *, rows: list[dict] | None = None,
    unit_types: list[str] | None = None, complete: bool = False,
    evidence_url: str | None = None, message: str | None = None,
    observed_at: datetime | None = None,
    expected_notice_version: int | None = None,
) -> CompetitionState:
    """Replace a successful public snapshot, retain prior figures on failure."""
    if status not in {"pending", "running", "ok", "partial", "error", "disabled"}:
        raise ValueError("Invalid competition status")
    # Competition and document collectors use long-lived sessions and can run
    # concurrently. Refresh the same notice lock before replacing its snapshot.
    notice = lock_notice(session, notice.source, notice.external_id) or notice
    stale_fetch = expected_notice_version is not None and notice.version != expected_notice_version
    if stale_fetch:
        # A source correction/enrichment committed while the network request
        # was in flight. Keep saved figures, but never certify the old fetch as
        # fresh closure evidence for the updated notice.
        status, rows, complete = "pending", None, False
        evidence_url = None
        message = "공고 변경 후 경쟁률 재확인 대기"
    observed_at = _datetime(observed_at) or utc_now()
    state = notice.competition_state
    if state is None:
        state = CompetitionState(notice_id=notice.id)
        notice.competition_state = state
    if stale_fetch:
        state.proof_invalidated = True
    state.status = status
    state.last_attempt_at = observed_at
    state.complete = bool(complete and status == "ok" and rows)
    state.message = message
    if evidence_url is not None:
        state.evidence_url = evidence_url
    if status in {"ok", "partial"} and rows is not None:
        state.proof_invalidated = False
        # Hash changed results without timestamps so repeated polls do not
        # create spurious revisions. Corrections/reopening do create one.
        snapshot_rows = [{key: item for key, item in row.items() if key != "observed_at"} for row in rows]
        snapshot = {"rows": snapshot_rows, "unit_types": unit_types or [], "complete": state.complete}
        digest = hashlib.sha256(json.dumps(_json_safe(snapshot), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        previous = session.scalar(select(CompetitionRevision).where(
            CompetitionRevision.notice_id == notice.id
        ).order_by(CompetitionRevision.id.desc()).limit(1))
        if previous is None or previous.content_hash != digest:
            session.add(CompetitionRevision(notice_id=notice.id, content_hash=digest, payload=_json_safe(snapshot), seen_at=observed_at))
        notice.competitions = [UnitCompetition(**{**row, "observed_at": observed_at}) for row in rows]
        state.unit_types = list(dict.fromkeys(unit_types or []))
        state.last_success_at = observed_at
    session.flush()
    return state


def related_notices(session: Session, notice: Notice) -> list[Notice]:
    canonical = session.get(Notice, canonical_id(notice))
    if canonical is None:
        canonical = notice
    duplicates = session.scalars(select(Notice).where(Notice.duplicate_of_id == canonical.id).order_by(Notice.source)).all()
    return [canonical, *duplicates]


def is_open_ended_application(event: EventPublic) -> bool:
    """A missing end alone does not turn a single-day event into ongoing intake."""
    return (event.kind.lower() not in NON_APPLICATION_KINDS and event.end_date is None and
            not re.search(NON_APPLICATION_LABEL_PATTERN, event.label) and
            bool(re.search(OPEN_RECEPTION_PATTERN, event.label)))


def open_ended_application_clause():
    """Equivalent SQL predicate for API and active document-reprocessing queries."""
    return and_(NoticeEvent.end_date.is_(None), func.lower(NoticeEvent.kind).not_in(NON_APPLICATION_KINDS),
                NoticeEvent.label.regexp_match(OPEN_RECEPTION_PATTERN),
                ~NoticeEvent.label.regexp_match(NON_APPLICATION_LABEL_PATTERN))


def application_sort_date(notice: NoticePublic, start: date | None = None, end: date | None = None) -> date | None:
    applications = [event for event in notice.events if event.kind not in NON_APPLICATION_KINDS]
    matching = [
        max(event.start_date, start) if start is not None else event.start_date for event in applications
        if not is_open_ended_application(event) and
        (end is None or event.start_date <= end) and (start is None or (event.end_date or event.start_date) >= start)
    ]
    if matching:
        return min(matching)
    if any(is_open_ended_application(event) and (end is None or event.start_date <= end) for event in applications):
        return None
    if applications:
        return min(event.start_date for event in applications)
    return notice.announcement_date


def application_end_date(notice: NoticePublic) -> date | None:
    """Latest official reception end, excluding results and contract dates."""
    if any(is_open_ended_application(event) for event in notice.events):
        return None
    return max(
        (event.end_date or event.start_date for event in notice.events if event.kind not in NON_APPLICATION_KINDS),
        default=None,
    )


def notice_matches_window(
    notice: NoticePublic, start: date | None, end: date | None, *, application_only: bool = False,
) -> bool:
    applications = [event for event in notice.events if event.kind not in NON_APPLICATION_KINDS]
    if applications:
        return any(
            (end is None or event.start_date <= end) and
            (start is None or is_open_ended_application(event) or (event.end_date or event.start_date) >= start)
            for event in applications
        )
    if application_only:
        return False
    if start is None and end is None:
        return True
    return bool(notice.announcement_date and
                (start is None or notice.announcement_date >= start) and
                (end is None or notice.announcement_date <= end))


def notice_public(
    related: list[Notice], detail: bool = False, start: date | None = None, end: date | None = None
) -> NoticePublic | NoticeDetail:
    # Stored duplicate rows can still contain an older parser interpretation.
    # Retire it before classification and qualification projection, without
    # altering source rows or their revision history. Import here keeps the
    # document package outside repository initialization.
    from app.extract.official_rules import PARSER_VERSION, parser_version_usable
    from app.extract.reviewed_sources import reviewed_source_for_document

    scope_fields = ("supply_type", "supply_types", "unit_type", "unit_types", "purpose", "restriction", "scope")

    def scoped(rule: dict[str, Any], inherited: dict[str, Any]) -> dict[str, Any]:
        result = {**inherited, **{key: rule[key] for key in scope_fields if key in rule}}
        if result.get("purpose") in {None, "eligibility", "admission"}:
            result.pop("purpose", None)
        return result

    def values(rule: dict[str, Any], single: str, plural: str) -> tuple:
        return tuple(sorted({str(value) for value in [rule.get(single), *(rule.get(plural) or [])] if value}))

    def review_key(rule: dict[str, Any], scope: dict[str, Any]) -> tuple:
        return (rule.get("kind"), values(scope, "supply_type", "supply_types"), values(scope, "unit_type", "unit_types"),
                scope.get("purpose"), scope.get("restriction"), scope.get("scope"),
                rule.get("label") if rule.get("kind") in {"all", "any", "not", "condition_group"} else None)

    def substantive_review(rule: dict[str, Any]) -> bool:
        if rule.get("kind") in {"document_diagnostics", "condition_coverage", "unparsed"} or rule.get("preserved_review_parser_version"):
            return False
        if rule.get("status") in {"partial", "unreadable", "unsupported", "error"} or rule.get("scope_complete") is False:
            return False
        if rule.get("kind") == "applicant_regions":
            return rule.get("scope_complete") is True
        if rule.get("kind") == "regional_allocation":
            method = rule.get("allocation_method")
            return bool(method and method != "unknown" and (method != "regional_quota" or rule.get("regional_shares") or rule.get("local_share_percent") is not None))
        return True

    replacements: dict[str, set[tuple]] = {}
    admission_reviews: dict[str, list[dict[str, Any]]] = {}
    complete_scopes: dict[str, list[dict[str, Any]]] = {}
    full_admission_reviews: set[str] = set()
    current_diagnostics: dict[str, tuple[float, dict[str, Any]]] = {}

    def collect_review(rule: dict[str, Any], notice: Notice, inherited: dict[str, Any]) -> None:
        scope = scoped(rule, inherited)
        if rule.get("effect") in {"priority", "procedure", "instruction"} or scope.get("purpose") == "selection":
            # Children inherit the parent's role even when their own effect
            # is omitted. Selection and instructions do not replace admission.
            return
        digest = rule.get("document_hash")
        if (rule.get("source") == "official_document_parser" and rule.get("verification") == "official"
                and rule.get("parser_version") == PARSER_VERSION and digest and digest == notice.document_hash
                and substantive_review(rule)):
            replacements.setdefault(digest, set()).add(review_key(rule, scope))
            if not is_metadata(rule) and scope.get("purpose") not in {"first_rank", "second_rank", "selection"}:
                admission_reviews.setdefault(digest, []).append(scope)
        for key in ("conditions", "exceptions"):
            for child in rule.get(key, []):
                if isinstance(child, dict):
                    collect_review(child, notice, scope)

    for notice in related:
        for rule in notice.rules or []:
            collect_review(rule, notice, {})
            digest = rule.get("document_hash")
            if (rule.get("kind") == "document_diagnostics" and rule.get("source") == "official_document_parser"
                    and rule.get("verification") == "official" and rule.get("parser_version") == PARSER_VERSION
                    and digest and digest == notice.document_hash):
                updated = notice.updated_at
                observed = updated.replace(tzinfo=timezone.utc).timestamp() if updated and updated.tzinfo is None else updated.timestamp() if updated else 0
                if digest not in current_diagnostics or observed > current_diagnostics[digest][0]:
                    current_diagnostics[digest] = (observed, rule)
    for notice in related:
        for rule in notice.rules or []:
            digest = rule.get("document_hash")
            if (rule.get("kind") != "condition_coverage" or rule.get("source") != "official_document_parser"
                    or rule.get("verification") != "official" or rule.get("parser_version") != PARSER_VERSION
                    or not digest or digest != notice.document_hash or digest not in replacements
                    or rule.get("status") in {"unreadable", "unsupported", "error"}
                    or rule.get("preserved_review_parser_version") or not rule.get("scopes")):
                continue
            source = reviewed_source_for_document(str(rule.get("evidence_url") or ""), digest)
            reviewed_pages = set((source or {}).get("admission_reviewed_pages") or [])
            if (digest in admission_reviews and source and source.get("admission_review_version") and reviewed_pages
                    and any(review.get("review_version") == source["admission_review_version"]
                            and reviewed_pages <= set(review.get("reviewed_pages") or [])
                            for review in [rule, *rule["scopes"]] if isinstance(review, dict))):
                # This exact whole-source review replaces generic admission
                # interpretations even when individual exception branches
                # explicitly remain unsupported in its fresh coverage report.
                full_admission_reviews.add(digest)
            # A real partial review renews its coverage report, but leaves
            # unmatched previously reviewed conditions available for these bytes.
            replacements[digest].add(review_key(rule, scoped(rule, {})))
            scopes = [scope for scope in rule["scopes"] if isinstance(scope, dict) and scope.get("complete") is True
                      and all(not topic.get("required", True) or topic.get("status") in {"verified", "not_applicable"}
                              for topic in scope.get("topics", []) if isinstance(topic, dict))
                      and any(all(not values(scope, single, plural) or not values(condition, single, plural) or
                                  bool(set(values(scope, single, plural)) & set(values(condition, single, plural)))
                                  for single, plural in (("supply_type", "supply_types"), ("unit_type", "unit_types")))
                              for condition in admission_reviews.get(digest, []))]
            complete_scopes.setdefault(digest, []).extend(scopes)
            offered = set(rule.get("offered_supply_types") or [])
            if offered and offered <= {scope.get("supply_type") for scope in scopes if not values(scope, "unit_type", "unit_types")}:
                complete_scopes[digest].append({"global_admission": True})

    def admission_replaced(scope: dict[str, Any], digest: str) -> bool:
        for reviewed in complete_scopes.get(digest, []):
            if reviewed.get("global_admission"):
                if not values(scope, "supply_type", "supply_types"):
                    return True
                continue
            if all(not values(reviewed, single, plural) or bool(values(scope, single, plural)) and
                   set(values(scope, single, plural)) <= set(values(reviewed, single, plural))
                   for single, plural in (("supply_type", "supply_types"), ("unit_type", "unit_types"))):
                return True
        return False

    def current_parser_rule(rule: dict[str, Any], notice: Notice, inherited: dict[str, Any] | None = None) -> bool:
        if not parser_version_usable(rule, category=notice.category, title=notice.title, rules=notice.rules):
            return False
        if rule.get("source") == "official_document_parser" and notice.document_hash and rule.get("document_hash") != notice.document_hash:
            return False
        if (rule.get("kind") == "document_diagnostics" and rule.get("source") == "official_document_parser"
                and rule.get("document_hash") in current_diagnostics
                and rule != current_diagnostics[rule["document_hash"]][1]):
            # Latest processing evidence for the same bytes supersedes an
            # older duplicate's failure; it is never admission review proof.
            return False
        scope = scoped(rule, inherited or {})
        if rule.get("source") == "official_document_parser" and rule.get("parser_version") != PARSER_VERSION:
            digest = rule.get("document_hash")
            if (review_key(rule, scope) in replacements.get(digest, set()) or
                    not is_metadata(rule) and scope.get("purpose") not in {"first_rank", "second_rank", "selection"}
                    and (digest in full_admission_reviews or admission_replaced(scope, digest))):
                return False
        # Dropping only a child could weaken an all/any/exception requirement.
        # Retire the containing branch when an obsolete interpretation occurs.
        return all(current_parser_rule(child, notice, scope) for key in ("conditions", "exceptions")
                   for child in rule.get(key, []) if isinstance(child, dict))

    canonical = related[0]
    reviewed_supply = reviewed_supply_classification(
        official_url=canonical.official_url, announcement_date=canonical.announcement_date,
        title=canonical.title, provider=canonical.provider) if canonical.source == "cheongyak_home" else None
    seen_events: set[tuple] = set()
    events: list[EventPublic] = []
    price_by_key: dict[tuple, PricePublic] = {}
    seen_rules: set[str] = set()
    rules: list[dict[str, Any]] = []
    declared_complete = False

    for notice in related:
        for event in notice.events:
            key = (event.kind, event.label, event.start_date, event.end_date, event.audience)
            if key not in seen_events:
                seen_events.add(key)
                events.append(EventPublic.model_validate(event))
        for price in notice.prices:
            key = (price.unit_type, price.area_sqm, price.price_kind, price.amount_krw, price.monthly_krw, price.basis_label)
            current = price_by_key.get(key)
            if current is None or (current.verification != "official" and price.verification == "official"):
                price_by_key[key] = PricePublic(
                    source=notice.source,
                    **{field: getattr(price, field) for field in PricePublic.model_fields if field != "source" and hasattr(price, field)},
                )
        usable_rules = [rule for rule in notice.rules or [] if current_parser_rule(rule, notice)]
        # A completeness flag associated with retired conditions cannot certify
        # the current document's partial or failed reparse.
        if len(usable_rules) == len(notice.rules or []):
            declared_complete = declared_complete or notice.rules_complete
        for rule in usable_rules:
            key = json.dumps(rule, sort_keys=True, ensure_ascii=False)
            if key not in seen_rules:
                seen_rules.add(key)
                rules.append(rule)

    events.sort(key=lambda event: (event.start_date, event.kind, event.label))
    prices = list(price_by_key.values())
    area_rules = [r for r in rules if r.get("kind") == "unit_exclusive_areas" and r.get("verification") == "official" and is_metadata(r)]
    for price in prices:
        # Existing area_sqm is often SUPLY_AR, not the dwelling's exclusive
        # area. Only explicit official area evidence may drive deposit tiers.
        matches = [u for r in area_rules for u in r.get("units", []) if isinstance(u, dict) and u.get("unit_type") == price.unit_type]
        values = {u["exclusive_area_sqm"] for u in matches if isinstance(u.get("exclusive_area_sqm"), (int, float)) and not isinstance(u.get("exclusive_area_sqm"), bool)}
        if len(values) == 1:
            price.exclusive_area_sqm = next(iter(values))
            price.area_basis = "exclusive" if price.area_sqm == price.exclusive_area_sqm else "supply" if price.area_sqm is not None else None
    prices.sort(key=lambda price: (price.unit_type, price.price_kind, price.amount_krw or -1))
    def competition_time(raw: datetime | None) -> datetime:
        # SQLite drops timezone metadata, but competition timestamps are UTC.
        return raw.replace(tzinfo=timezone.utc) if raw is not None and raw.tzinfo is None else raw or datetime.min.replace(tzinfo=timezone.utc)

    with_competition = [item for item in related if item.competition_state is not None]
    # A newer pending duplicate must not erase a previously saved official
    # result from another source. Failed checks retain their own saved rows.
    competition_notice = max(
        [item for item in with_competition if item.competitions] or with_competition,
        key=lambda item: competition_time(item.competition_state.last_attempt_at),
        default=None,
    )
    competition_rows = [CompetitionPublic.model_validate(row) for row in competition_notice.competitions] if competition_notice else []
    competition_state = CompetitionStatePublic.model_validate(competition_notice.competition_state) if competition_notice else CompetitionStatePublic()
    if any(item.competition_state and item.competition_state.proof_invalidated for item in related):
        competition_state.proof_invalidated = True
    for row in competition_rows:
        row.observed_at = competition_time(row.observed_at)
    for field in ("last_attempt_at", "last_success_at"):
        raw = getattr(competition_state, field)
        if raw is not None:
            setattr(competition_state, field, competition_time(raw))
    housing_kind, housing_kind_evidence, qualification_context = public_classification(rules)
    if reviewed_supply and reviewed_supply not in rules:
        # Existing public source rows retain their originals and revisions;
        # the exact provider cross-link also corrects the read projection.
        rules.append(reviewed_supply)
    application_method, application_method_evidence = public_application_method(rules)
    data = {
        "id": canonical.id,
        "source": canonical.source,
        "sources": [item.source for item in related],
        "correction_of_external_id": canonical.correction_of_external_id,
        "correction_of_id": canonical.correction_of_id,
        "provider": canonical.provider,
        "title": canonical.title,
        "category": reviewed_supply["category"] if reviewed_supply else canonical.category,
        "housing_kind": housing_kind,
        "housing_kind_evidence": housing_kind_evidence,
        "rank_applicability": public_rank_applicability(rules),
        "application_method": application_method,
        "application_method_evidence": application_method_evidence,
        "qualification_context": qualification_context,
        "contract_schedule": public_contract_schedule(rules, contract_events=[
            {"start_date": event.start_date, "end_date": event.end_date, "source": notice.source,
             "evidence_url": notice.official_url, "evidence_text": f"{event.label} · {event.start_date}" + (f"–{event.end_date}" if event.end_date else "")}
            for notice in related for event in notice.events if event.kind == "contract"
        ]),
        "offered_supplies": public_offered_supplies(rules),
        "selection_methods": public_selection_methods(rules),
        "winning_scores": public_winning_scores(rules),
        "address": canonical.address,
        "region_code": canonical.region_code,
        "region_name": canonical.region_name,
        "announcement_date": canonical.announcement_date,
        "official_url": canonical.official_url,
        "document_hash": canonical.document_hash,
        "price_cap_status": "not_applicable" if reviewed_supply and reviewed_supply["category"] == "public_rental" else next((item.price_cap_status for item in related if item.price_cap_status in {"yes", "no"}), canonical.price_cap_status),
        "events": events,
        "prices": prices,
        "competitions": competition_rows,
        "competition": competition_state,
        "rules": rules,
        "rules_complete": requirements_complete(rules, declared_complete),
        "updated_at": max((item.updated_at for item in related if item.updated_at), default=None),
        "version": canonical.version,
    }
    if detail:
        data["revisions"] = [RevisionPublic.model_validate(revision, from_attributes=True) for revision in canonical.revisions]
        result = NoticeDetail(**data)
    else:
        result = NoticePublic(**data)
    result.sort_date = application_sort_date(result, start, end)
    result.application_end_date = application_end_date(result)
    return result
