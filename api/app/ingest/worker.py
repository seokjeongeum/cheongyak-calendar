"""Three-hour official housing notice polling worker.

Run ``python -m app.ingest.worker`` or ``python -m app.ingest.worker --once``.
All applicant profile data stays in the browser; this process requests only
public notices. Missing service credentials are recorded as disabled coverage.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import logging
import os
import signal
from collections.abc import Callable
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from time import monotonic
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError
from sqlalchemy import and_, func, inspect, or_, select
from sqlalchemy.orm import Session, defer, lazyload
from sqlalchemy.orm.attributes import NO_VALUE

from app.db import SessionLocal, collector_session_limits, init_db
from app.collection import CollectionHeartbeat, claim_collection, finish_collection, renew_collection
from app.integration_settings import setting_value
from app.extract.pipeline import DOCUMENT_PIPELINE_VERSION, _diagnostics_rule, enrich_notice, extraction_configured
from app.extract.official_rules import PARSER_VERSION
from app.extract.reprocess import _context as _document_context, _document_patch
from app.models import DocumentExtractionState, Notice, NoticeEvent, SourceStatus
from app.qualification import is_metadata, merge_poll_rules
from app.repository import NON_APPLICATION_KINDS, _existing_payload, feed_payload_hash, feed_review_hash, is_open_ended_application, lock_notice, notice_patch_changed, open_ended_application_clause, record_source_status, resolve_pending_corrections, upsert_notice
from app.schemas import EventPublic

from . import boards, competition, ih, lh, myhome, reb
from .common import FeedError, date_iso, yield_to_deadlines
from .detail_links import enrich_detail_link

LOGGER = logging.getLogger("cheongyak.ingest")
KST = ZoneInfo("Asia/Seoul")
POLL_SECONDS = 3 * 60 * 60
FEED_TIMEOUT_SECONDS = 10 * 60
DOCUMENT_TIMEOUT_SECONDS = 120
DOCUMENT_BUDGET_SECONDS = 30 * 60
COMPETITION_TIMEOUT_SECONDS = 20 * 60
SAVED_DOCUMENT_LIMIT = 50
OFFICIAL_SOURCES = ("cheongyak_home", "myhome", "lh", "ih", "sh", "gh")
LOOKBACK_DAYS = 180
LOOKAHEAD_DAYS = 60
QUOTA_STATE_KEY = ("_gemini", "free_quota")


def _api_key(source: str) -> str:
    specific = {"myhome": "MYHOME_API_KEY", "lh": "LH_API_KEY", "ih": "IH_API_KEY"}.get(source)
    key = (setting_value(specific) if specific else "") or setting_value("DATA_GO_KR_API_KEY")
    # data.go.kr displays both encoded and decoded variants of the same key.
    # httpx encodes query parameters itself, so decode at most once here.
    return unquote(key.strip())


def _active_notice(payload: dict, today: date) -> bool:
    for event in payload.get("events") or []:
        end = event.get("end_date") or event.get("start_date")
        if end and str(end) >= today.isoformat():
            return True
    announced = payload.get("announcement_date")
    return bool(announced and str(announced) >= (today - timedelta(days=45)).isoformat())


def _save_priority(payload: dict, today: date) -> int:
    """Show available reception first without dropping historical feed rows."""
    for raw_event in payload.get("events") or []:
        try:
            event = EventPublic.model_validate(raw_event)
        except ValidationError:
            # Invalid input still reaches the usual normalization diagnostics.
            continue
        if event.kind.lower() in NON_APPLICATION_KINDS:
            continue
        if is_open_ended_application(event) or (event.end_date or event.start_date) >= today:
            return 0
    announced = date_iso(payload.get("announcement_date"))
    return 1 if announced and announced >= (today - timedelta(days=45)).isoformat() else 2


def _document_checkpoint(existing: Notice) -> dict:
    """Keep only versioned retry facts, rather than the full source document."""
    diagnostics = []
    for rule in existing.rules or []:
        if not isinstance(rule, dict) or rule.get("kind") != "document_diagnostics":
            continue
        discovery_failed = any(
            entry.get("stage") == "discovery"
            and entry.get("status") not in {"ok", "resolved"}
            and entry.get("code") in {"announcement_download_failed", "attachment_not_found"}
            for entry in rule.get("diagnostics") or [] if isinstance(entry, dict)
        )
        download_failed = any(
            entry.get("stage") == "download" and entry.get("status") == "error"
            and entry.get("code") == "document_download_failed"
            for entry in rule.get("diagnostics") or [] if isinstance(entry, dict)
        )
        diagnostics.append({"status": rule.get("status"), "parser_version": rule.get("parser_version"),
                            "pipeline_version": rule.get("pipeline_version"),
                            "discovery_failed": discovery_failed, "download_failed": download_failed})
    return {"notice_version": existing.version, "diagnostics": diagnostics}


def _cached_checkpoint(existing: Notice, state: DocumentExtractionState | None) -> dict | None:
    checkpoint = state.document_checkpoint if state else None
    if (not isinstance(checkpoint, dict) or type(checkpoint.get("notice_version")) is not int
            or checkpoint["notice_version"] != existing.version
            or not isinstance(checkpoint.get("diagnostics"), list)):
        return None
    for entry in checkpoint["diagnostics"]:
        if (not isinstance(entry, dict) or not {"status", "parser_version", "pipeline_version"}.issubset(entry)
                or type(entry.get("discovery_failed")) is not bool or type(entry.get("download_failed")) is not bool):
            return None
    return checkpoint


def _cache_loaded_document(existing: Notice, state: DocumentExtractionState | None) -> None:
    # An unchanged archival row must not load a large rules JSON just to build
    # a cache. The first actual normalization/review supplies this checkpoint.
    if state is not None and inspect(existing).attrs.rules.loaded_value is not NO_VALUE:
        state.document_checkpoint = _document_checkpoint(existing)


def _failed_document_needs_new_pipeline(existing: Notice | None, state: DocumentExtractionState | None = None) -> bool:
    """Retry stale review versions using small cached facts where available."""
    if existing is None:
        return False
    checkpoint = _cached_checkpoint(existing, state)
    if checkpoint is None:
        checkpoint = _document_checkpoint(existing)
        if state is not None:
            state.document_checkpoint = checkpoint
    for rule in checkpoint["diagnostics"]:
        status = rule["status"]
        if rule["pipeline_version"] != DOCUMENT_PIPELINE_VERSION and (status in {"unreadable", "error"} or rule["discovery_failed"] or rule["download_failed"]):
            return True
        if rule["parser_version"] != PARSER_VERSION and status in {"complete", "partial", "unsupported", "unreadable", "error"}:
            return True
    return False


def _save_progress(
    session: Session, state: SourceStatus | None, source: str, saved: int, total: int,
    stored_count: int | None = None, progress_floor: int = 0,
    *, phase: str,
) -> SourceStatus:
    """Commit progress with its notice, retaining the source attempt/success times."""
    count = stored_count if stored_count is not None else max(saved, progress_floor)
    message = (f"공식 공고 저장 중 · {saved}/{total}건 저장" if phase == "raw" else
               f"공식 공고 {count}건 저장 · 문서 확인 {saved}/{total}건")
    if state is None:
        return record_source_status(session, source, "running", message, record_count=count)
    state.status = "running"
    state.message = message
    state.record_count = count
    return state


def _pending_url_payload(payload: dict, existing: Notice | None, url_changed: bool) -> dict:
    """Keep the current hash's review until a revised page's file is read."""
    if (url_changed and existing and existing.document_hash
            and payload.get("document_hash") in {None, existing.document_hash}):
        incoming_rules = payload.get("rules", [])
        return {**payload, "document_hash": existing.document_hash,
                "rules": merge_poll_rules(existing.rules or [], incoming_rules,
                    metadata_only=all(is_metadata(r) for r in incoming_rules))}
    return payload


def _saved_document_queue(today: date) -> tuple[dict, dict]:
    """Select a bounded active backlog without waiting for a provider's feed."""
    now = datetime.now(timezone.utc)
    state = DocumentExtractionState
    first = state.document_checkpoint["diagnostics"][0]
    stale_parser = and_(first["parser_version"].as_string() != PARSER_VERSION,
        first["status"].as_string().in_(["complete", "partial", "unsupported", "unreadable", "error"]))
    stale_pipeline = and_(first["pipeline_version"].as_string() != DOCUMENT_PIPELINE_VERSION,
        or_(first["status"].as_string().in_(["unreadable", "error"]),
            first["discovery_failed"].as_boolean().is_(True),
            first["download_failed"].as_boolean().is_(True)))
    stale = or_(stale_parser, stale_pipeline)
    unknown_checkpoint = or_(state.document_checkpoint.is_(None),
        state.document_checkpoint["notice_version"].as_integer().is_(None),
        state.document_checkpoint["notice_version"].as_integer() != Notice.version,
        first["status"].as_string().is_(None))
    active_reception = select(NoticeEvent.id).where(NoticeEvent.notice_id == Notice.id,
        NoticeEvent.kind.not_in(NON_APPLICATION_KINDS),
        or_(func.coalesce(NoticeEvent.end_date, NoticeEvent.start_date) >= today,
            open_ended_application_clause())).exists()
    statement = (select(Notice, state).outerjoin(state,
        and_(state.source == Notice.source, state.external_id == Notice.external_id))
        .options(defer(Notice.rules), lazyload(Notice.competitions), lazyload(Notice.competition_state))
        .where(Notice.source.in_(OFFICIAL_SOURCES), Notice.official_url.is_not(None),
            or_(active_reception, Notice.announcement_date >= today - timedelta(days=45)),
            or_(stale, unknown_checkpoint, state.audited_on.is_(None), state.audited_on != today),
            or_(stale, unknown_checkpoint, state.deferred_until.is_(None), state.deferred_until <= now))
        .order_by(stale.desc().nullslast(), state.audited_on.asc().nullsfirst(),
            Notice.announcement_date.desc(), Notice.id).limit(SAVED_DOCUMENT_LIMIT))
    pending: dict[str, dict] = {}
    retained: dict[str, dict] = {}
    with SessionLocal() as session:
        for notice, extraction_state in session.execute(statement):
            # Valid scalar checkpoints decide same-day/cooldown skips without
            # transferring a full rules JSON. Only selected work needs a copy.
            changed_parser = _failed_document_needs_new_pipeline(notice, extraction_state)
            audited = extraction_state.audited_on if extraction_state else None
            deferred = extraction_state.deferred_until if extraction_state else None
            if deferred is not None and deferred.tzinfo is None:
                deferred = deferred.replace(tzinfo=timezone.utc)
            if not changed_parser and (audited == today or deferred is not None and deferred > now):
                continue
            payload = copy.deepcopy(_existing_payload(notice))
            # The collector's raw payload and priority helpers use ISO dates.
            if isinstance(payload.get("announcement_date"), date):
                payload["announcement_date"] = payload["announcement_date"].isoformat()
            for event in payload.get("events", []):
                for key in ("start_date", "end_date"):
                    if isinstance(event.get(key), date):
                        event[key] = event[key].isoformat()
            pending.setdefault(notice.source, {})[notice.external_id] = (payload, None if changed_parser else audited)
            retained.setdefault(notice.source, {})[notice.external_id] = notice.last_feed_review_hash
        session.commit()
    return pending, retained


async def _review_saved_document(payload: dict, expected_feed_hash: str | None,
    client: httpx.AsyncClient, today: date, *, deadline: float) -> tuple[int, int]:
    """Apply a document-only patch to the latest retained source under its lock."""
    source, external_id = payload["source"], payload["external_id"]
    identity = (source, external_id)
    enriched = None
    failure = None
    try:
        async with asyncio.timeout(min(DOCUMENT_TIMEOUT_SECONDS, max(0, deadline - monotonic()))):
            enriched = await enrich_notice(copy.deepcopy(payload), client=client,
                known_document_hash=payload.get("document_hash"), allow_gemini=False)
    except Exception as exc:
        failure = exc
        LOGGER.warning("Saved document review failed for %s: %s", source, type(exc).__name__)
    with SessionLocal() as session:
        notice = lock_notice(session, source, external_id)
        if notice is None:
            return 1, 1
        current = _existing_payload(notice)
        allowed_hashes = {payload.get("document_hash"), (enriched or {}).get("document_hash")}
        if (_document_context(payload) != _document_context(current)
                or payload.get("title") != current.get("title")
                or notice.last_feed_review_hash != expected_feed_hash
                or current.get("document_hash") not in allowed_hashes):
            # A correction/newer review won the race. Never restore its older
            # source fields, hashes, prices or checkpoint from this snapshot.
            return 1, 1
        state = session.get(DocumentExtractionState, identity, populate_existing=True)
        if state is None:
            state = DocumentExtractionState(source=source, external_id=external_id)
            session.add(state)
        if failure is not None:
            diagnostic = _diagnostics_rule([{
                "stage": "processing", "code": "audit_timeout" if isinstance(failure, TimeoutError) else "audit_failed",
                "status": "error", "evidence_url": current.get("official_url"),
                "message": "공고문 확인 시간 한도에 도달했습니다. 저장된 자료를 유지하며 다음 수집에서 이어서 확인합니다." if isinstance(failure, TimeoutError) else "공고문 확인 실행에 실패했습니다. 저장된 자료를 유지하며 다음 수집에서 다시 확인합니다.",
                "missing_items": ["현재 공고문 확인의 완료 기록"],
            }], "error", current.get("document_hash"))
            patch = {"source": source, "external_id": external_id, "replace_rules": True,
                "rules": [rule for rule in current.get("rules", []) if rule.get("kind") != "document_diagnostics"] + [diagnostic]}
            state.audited_on = None
            state.deferred_until = datetime.now(timezone.utc) + timedelta(seconds=POLL_SECONDS)
        else:
            patch = _document_patch(current, enriched)
            state.audited_on = today
            state.deferred_until = None
        if notice_patch_changed(notice, patch):
            notice = upsert_notice(session, patch)
        state.document_checkpoint = _document_checkpoint(notice)
        session.commit()
    return 1, int(failure is not None)


async def _save_rows(
    source: str, rows: list[dict], client: httpx.AsyncClient, today: date,
    source_warning: str | None = None,
    *, audit_documents: bool = True, finalize: bool = True,
    document_semaphore: asyncio.Semaphore | None = None, stored_count: int | None = None,
    persist_before_audit: bool = False, on_raw_saved: Callable[[dict], None] | None = None,
    progress_floor: int = 0, on_audit_pending: Callable[[dict, date | None], None] | None = None,
    track_source_progress: bool = True, document_deadline: float | None = None,
    document_timeout_seconds: float | None = None, preserve_row_order: bool = False,
    on_row_result: Callable[[dict], None] | None = None,
) -> tuple[int, int, int, int, int, int, str]:
    saved = 0
    invalid = 0
    deferred = 0
    missing = 0
    missing_prices = 0
    missing_dates = 0
    with SessionLocal() as session:
        for payload in rows if preserve_row_order else sorted(rows, key=lambda row: _save_priority(row, today)):
            try:
                # Await a fair document turn before opening a read transaction.
                # Each prior row has already committed, releasing its connection.
                async with (document_semaphore or nullcontext()):
                    if audit_documents and document_deadline is not None and monotonic() >= document_deadline:
                        break
                    quota_state = session.get(DocumentExtractionState, QUOTA_STATE_KEY, populate_existing=True)
                    source_state = session.get(SourceStatus, source, populate_existing=True)
                    if payload.get("source") != source:
                        invalid += 1
                        session.commit()
                        continue
                    identity = (source, str(payload.get("external_id") or ""))
                    has_ingest_warning = bool(payload.pop("ingest_warning", None))
                    if has_ingest_warning:
                        missing += 1
                    try:
                        raw_hash = feed_payload_hash(payload)
                        review_hash = feed_review_hash(payload)
                    except (ValueError, TypeError):
                        invalid += 1
                        session.commit()
                        LOGGER.warning("Skipped invalid %s notice: normalization failed", source)
                        continue
                    raw_payload = copy.deepcopy(payload)
                    existing = session.scalar(select(Notice).options(
                        defer(Notice.rules), lazyload(Notice.competitions),
                    ).where(Notice.source == source, Notice.external_id == identity[1]))
                    extraction_state = session.get(DocumentExtractionState, identity)
                    did_audit = False
                    url_changed = existing is not None and existing.official_url != payload.get("official_url")
                    feed_changed = (existing is not None and existing.last_feed_review_hash is not None
                                    and existing.last_feed_review_hash != review_hash)
                    now = datetime.now(timezone.utc)
                    deferred_until = extraction_state.deferred_until if extraction_state else None
                    if deferred_until is not None and deferred_until.tzinfo is None:
                        # SQLite does not retain DateTime timezone metadata; all new
                        # cooldown timestamps are written as UTC.
                        deferred_until = deferred_until.replace(tzinfo=timezone.utc)
                    quota_until = quota_state.deferred_until if quota_state else None
                    if quota_until is not None and quota_until.tzinfo is None:
                        quota_until = quota_until.replace(tzinfo=timezone.utc)
                    quota_blocked = quota_until is not None and quota_until > now
                    if audit_documents and quota_blocked and extraction_configured() and payload.get("official_url") and _active_notice(payload, today):
                        deferred += 1
                    should_audit = (
                        (existing is None or url_changed or feed_changed or (extraction_state is not None and extraction_state.audited_on is None) or (
                            _active_notice(payload, today) and
                            (extraction_state is None or extraction_state.audited_on != today
                             or _failed_document_needs_new_pipeline(existing, extraction_state) or (
                                extraction_configured() and not quota_blocked
                                and deferred_until is not None and deferred_until <= now
                            ))
                        ))
                    )
                    # A timed-out first audit is a durable pending task, with a
                    # cooldown so repeated restarts cannot retry only that row.
                    local_retry_blocked = (extraction_state is not None and extraction_state.audited_on is None
                            and deferred_until is not None and deferred_until > now
                            and not url_changed and not feed_changed and not _failed_document_needs_new_pipeline(existing, extraction_state))
                    if local_retry_blocked:
                        should_audit = False
                        if audit_documents:
                            deferred += 1
                    if persist_before_audit and should_audit:
                        try:
                            # Commit this row before its own PDF wait, rather than
                            # blocking every source on a full archival DB pass.
                            existing = lock_notice(session, source, identity[1])
                            extraction_state = session.get(DocumentExtractionState, identity, populate_existing=True)
                            url_changed = existing is not None and existing.official_url != payload.get("official_url")
                            payload = _pending_url_payload(payload, existing, url_changed)
                            existing = upsert_notice(session, payload)
                            if extraction_state is None:
                                extraction_state = DocumentExtractionState(source=source, external_id=identity[1])
                                session.add(extraction_state)
                            extraction_state.audited_on = None
                            existing.last_feed_hash = raw_hash
                            existing.last_feed_version = existing.version
                            existing.last_feed_review_hash = review_hash
                            _cache_loaded_document(existing, extraction_state)
                            if track_source_progress:
                                source_state = _save_progress(session, source_state, source, saved + 1, len(rows),
                                    progress_floor=progress_floor, phase="document" if audit_documents else "raw")
                            session.commit()
                            if on_raw_saved:
                                on_raw_saved(payload)
                        except (ValueError, TypeError) as exc:
                            session.rollback()
                            invalid += 1
                            LOGGER.warning("Skipped invalid %s notice: %s", source, type(exc).__name__)
                            continue
                    if audit_documents and should_audit:
                        did_audit = True
                        try:
                            # Public PDF/HWP/HWPX parsing does not require a model key.
                            # A Gemini cooldown never blocks local official facts.
                            allow_gemini = not quota_blocked and (deferred_until is None or deferred_until <= now)
                            feed_payload = copy.deepcopy(payload)
                            if existing:
                                incoming_rules = payload.get("rules", [])
                                payload["rules"] = merge_poll_rules(existing.rules or [], incoming_rules, metadata_only=all(is_metadata(r) for r in incoming_rules))
                            known_hash = existing.document_hash if existing else None
                            # No notice/state lock or read transaction is retained
                            # during downloading. Reprocessing may commit meanwhile.
                            session.commit()
                            async def enrich_public_facts():
                                enriched = await enrich_notice(payload, client=client, known_document_hash=known_hash, allow_gemini=allow_gemini)
                                if _active_notice(payload, today):
                                    enriched = await enrich_detail_link(enriched, client=client, previous_rules=existing.rules if existing else [])
                                return enriched

                            if document_timeout_seconds is None:
                                enriched = await enrich_public_facts()
                            else:
                                remaining = document_timeout_seconds if document_deadline is None else min(document_timeout_seconds, max(0, document_deadline - monotonic()))
                                async with asyncio.timeout(remaining):
                                    enriched = await enrich_public_facts()
                            existing = lock_notice(session, source, identity[1])
                            extraction_state = session.get(DocumentExtractionState, identity, populate_existing=True)
                            stale_document = existing is not None and existing.document_hash not in {known_hash, enriched.get("document_hash")}
                            if stale_document:
                                # A concurrent local audit may have seen a corrected
                                # attachment while this download received stale bytes.
                                # Keep its hash/facts and apply only this feed's fields.
                                enriched = {**feed_payload, "document_hash": existing.document_hash,
                                            "rules": merge_poll_rules(existing.rules or [], feed_payload.get("rules", []),
                                                metadata_only=all(is_metadata(r) for r in feed_payload.get("rules", [])))}
                            if extraction_state is None:
                                extraction_state = DocumentExtractionState(source=source, external_id=identity[1])
                                session.add(extraction_state)
                            extraction_status = enriched.get("extraction_status")
                            if stale_document:
                                extraction_state.audited_on = None
                            elif extraction_status in {"deferred", "quota"}:
                                extraction_state.audited_on = today
                                deferred += 1
                                delay = timedelta(hours=24 if extraction_status == "quota" else 3)
                                extraction_state.deferred_until = now + delay
                                if extraction_status == "quota":
                                    if quota_state is None:
                                        quota_state = DocumentExtractionState(source=QUOTA_STATE_KEY[0], external_id=QUOTA_STATE_KEY[1])
                                        session.add(quota_state)
                                    quota_state.deferred_until = now + delay
                            else:
                                extraction_state.audited_on = today
                                extraction_state.deferred_until = None
                            # An unchanged document yields empty extraction arrays. Do
                            # not erase previously persisted AI candidates on a poll.
                            if existing and enriched.get("document_hash") == existing.document_hash:
                                for key in ("prices", "rules"):
                                    if not enriched.get(key) and not payload.get(key):
                                        enriched.pop(key, None)
                            payload = enriched
                        except Exception as exc:  # one bad document cannot block a feed
                            session.rollback()
                            LOGGER.warning("Document enrichment failed for %s: %s", source, type(exc).__name__)
                            deferred += 1
                            extraction_state = session.get(DocumentExtractionState, identity, populate_existing=True)
                            if extraction_state is None:
                                extraction_state = DocumentExtractionState(source=source, external_id=identity[1])
                                session.add(extraction_state)
                            extraction_state.audited_on = None
                            extraction_state.deferred_until = datetime.now(timezone.utc) + timedelta(seconds=POLL_SECONDS)
                            diagnostic = _diagnostics_rule([{
                                "stage": "processing", "code": "audit_timeout" if isinstance(exc, TimeoutError) else "audit_failed",
                                "status": "error", "evidence_url": payload.get("official_url"),
                                "message": "공고문 확인 시간 한도에 도달했습니다. 저장된 자료를 유지하며 다음 수집에서 이어서 확인합니다." if isinstance(exc, TimeoutError) else "공고문 확인 실행에 실패했습니다. 저장된 자료를 유지하며 다음 수집에서 다시 확인합니다.",
                                "missing_items": ["현재 공고문 확인의 완료 기록"],
                            }], "error", known_hash)
                            payload["rules"] = [rule for rule in payload.get("rules", []) if rule.get("kind") != "document_diagnostics"] + [diagnostic]
                    try:
                        if not audit_documents:
                            payload = _pending_url_payload(payload, existing, url_changed)
                        # Recheck the scalar checksum under the same row lock used
                        # by real writes. A concurrent correction/review increments
                        # version and conservatively invalidates this shortcut.
                        current = lock_notice(session, source, identity[1], include_rules=False)
                        if (not did_audit and current is not None and current.last_feed_hash == raw_hash
                                and current.last_feed_version == current.version):
                            notice = current
                            notice.last_seen_at = datetime.now(timezone.utc)
                        else:
                            notice = upsert_notice(session, payload)
                        notice.last_feed_hash = raw_hash
                        notice.last_feed_version = notice.version
                        notice.last_feed_review_hash = review_hash
                        if not audit_documents and (existing is None or url_changed or feed_changed):
                            # Keep a durable pending first/revised-URL audit across
                            # stops without inventing an attempted or read date.
                            if extraction_state is None:
                                extraction_state = DocumentExtractionState(source=source, external_id=identity[1])
                                session.add(extraction_state)
                            extraction_state.audited_on = None
                            if feed_changed:
                                extraction_state.deferred_until = None
                        _cache_loaded_document(notice, extraction_state)
                        if track_source_progress:
                            source_state = _save_progress(session, source_state, source, saved + 1, len(rows),
                                stored_count, progress_floor, phase="document" if audit_documents else "raw")
                        session.commit()
                        if on_raw_saved:
                            on_raw_saved(payload)
                        if not audit_documents and (should_audit or local_retry_blocked) and on_audit_pending:
                            checkpoint = extraction_state.audited_on if extraction_state else None
                            on_audit_pending(raw_payload, None if _failed_document_needs_new_pipeline(notice, extraction_state) else checkpoint)
                        saved += 1
                        row_missing_prices = not any(price.amount_krw is not None or price.monthly_krw is not None for price in notice.prices)
                        row_missing_dates = not any(event.kind not in NON_APPLICATION_KINDS for event in notice.events)
                        if row_missing_prices:
                            missing_prices += 1
                        if row_missing_dates:
                            missing_dates += 1
                        if on_row_result:
                            on_row_result({"external_id": identity[1], "missing_prices": row_missing_prices,
                                           "missing_dates": row_missing_dates, "missing_detail": has_ingest_warning})
                    except (ValueError, TypeError) as exc:
                        session.rollback()
                        invalid += 1
                        LOGGER.warning("Skipped invalid %s notice: %s", source, type(exc).__name__)
                    except Exception:
                        session.rollback()
                        raise
            finally:
                await yield_to_deadlines()
        status = "partial" if invalid or deferred or missing or missing_prices or missing_dates or source_warning or not rows else "ok"
        message_parts = [f"{saved}건 저장"]
        if invalid:
            message_parts.append(f"{invalid}건 정규화 실패")
        if deferred:
            message_parts.append(f"문서 추출 {deferred}건 대기")
        if missing:
            message_parts.append(f"공식 상세 누락 {missing}건")
        if missing_prices:
            message_parts.append(f"주택형 가격 미확인 {missing_prices}건")
        if missing_dates:
            message_parts.append(f"접수일 미확인 {missing_dates}건")
        if source_warning:
            message_parts.append(source_warning)
        if not rows:
            message_parts.append("조회 범위 0건; 공고 누락 여부 확인 필요")
        resolve_pending_corrections(session, source)
        if finalize and track_source_progress:
            record_source_status(session, source, status, ", ".join(message_parts), record_count=max(saved, progress_floor))
        elif track_source_progress:
            state = session.get(SourceStatus, source)
            _save_progress(session, state, source, saved, len(rows), progress_floor=progress_floor,
                phase="document" if audit_documents else "raw")
            state = session.get(SourceStatus, source)
            state.message = f"공식 공고 {saved}건 저장 · 문서 확인 대기"
        session.commit()
    return saved, invalid, deferred, missing_prices, missing_dates, missing, status


async def run_once(*, today: date | None = None, client: httpx.AsyncClient | None = None) -> dict[str, dict]:
    """Commit complete feeds first; audit a bounded durable document backlog."""
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    init_db()
    today = today or datetime.now(KST).date()
    start, end = today - timedelta(days=LOOKBACK_DAYS), today + timedelta(days=LOOKAHEAD_DAYS)
    own_client = client is None
    client = client or httpx.AsyncClient(headers={"User-Agent": "CheongyakCalendar/1.0 (+public housing notice index)"}, follow_redirects=True)
    results: dict[str, dict] = {}
    pending_documents: dict[str, dict[str, tuple[dict, date | None]]] = {}
    durable_identities: dict[str, set[str]] = {}
    streamed_rows: dict[str, dict[str, dict]] = {}
    row_results: dict[str, dict[str, dict]] = {}
    invalid_rows: dict[str, int] = {}
    competition_ready = asyncio.Event()
    document_deadline = monotonic() + DOCUMENT_BUDGET_SECONDS
    pending_documents, retained_reviews = _saved_document_queue(today)

    def raw_saved(source: str, payload: dict) -> None:
        durable_identities.setdefault(source, set()).add(payload["external_id"])
        if source == "cheongyak_home":
            competition_ready.set()

    def pending_audit(source: str, payload: dict, checkpoint: date | None) -> None:
        pending_documents.setdefault(source, {})[payload["external_id"]] = (payload, checkpoint)
        # A fetched current row replaces the retained snapshot and follows the
        # existing raw-feed audit path; it must not be reviewed a second time.
        retained_reviews.get(source, {}).pop(payload["external_id"], None)

    async def save_feed_batch(source: str, batch: list[dict]) -> None:
        if not batch:
            with SessionLocal() as session:
                record_source_status(session, source, "partial", "현재 조회 범위 0건 · 나머지 공고 조회 중", record_count=0)
                session.commit()
            return
        snapshot = copy.deepcopy(batch)
        saved, invalid, *_ = await _save_rows(
            source, copy.deepcopy(batch), client, today,
            source_warning="나머지 공고 조회 중", audit_documents=False,
            on_raw_saved=lambda row: raw_saved(source, row),
            on_audit_pending=lambda row, checkpoint: pending_audit(source, row, checkpoint),
            on_row_result=lambda result: row_results.setdefault(source, {}).__setitem__(result["external_id"], result),
            progress_floor=len(durable_identities.get(source, set())),
        )
        invalid_rows[source] = invalid_rows.get(source, 0) + invalid
        for row in snapshot:
            if row.get("external_id") in durable_identities.get(source, set()):
                streamed_rows.setdefault(source, {})[row["external_id"]] = row
        with SessionLocal() as session:
            state = session.get(SourceStatus, source)
            if state is not None:
                state.message = f"공식 공고 {len(durable_identities.get(source, set()))}건 저장 · 나머지 공고 조회 중"
                session.commit()

    async def finish_feed(source: str, rows: list[dict], warning: str | None) -> None:
        # Streaming is durable before later HTTP waits. Unchanged rows are not
        # read/upserted twice against the remote database; enriched details and
        # correction links are still applied when the final payload differs.
        changed = [row for row in rows if streamed_rows.get(source, {}).get(row.get("external_id")) != row]
        if changed:
            _, invalid, *_ = await _save_rows(
                source, changed, client, today, warning, audit_documents=False,
                finalize=False, track_source_progress=False,
                on_raw_saved=lambda row: raw_saved(source, row),
                on_audit_pending=lambda row, checkpoint: pending_audit(source, row, checkpoint),
                on_row_result=lambda result: row_results.setdefault(source, {}).__setitem__(result["external_id"], result),
                progress_floor=len(durable_identities.get(source, set())),
            )
            invalid_rows[source] = invalid_rows.get(source, 0) + invalid
        metrics = list(row_results.get(source, {}).values())
        count = len(durable_identities.get(source, set()))
        invalid = invalid_rows.get(source, 0)
        prices = sum(row["missing_prices"] for row in metrics)
        dates = sum(row["missing_dates"] for row in metrics)
        details = sum(row["missing_detail"] for row in metrics)
        status = "partial" if invalid or prices or dates or details or warning or not rows else "ok"
        message = [f"{count}건 저장"]
        for amount, label in ((invalid, "정규화 실패"), (prices, "주택형 가격 미확인"), (dates, "접수일 미확인"), (details, "공식 상세 누락")):
            if amount:
                message.append(f"{label} {amount}건")
        if warning:
            message.append(warning)
        if not rows:
            message.append("조회 범위 0건; 공고 누락 여부 확인 필요")
        with SessionLocal() as session:
            record_source_status(session, source, status, ", ".join(message), record_count=count)
            session.commit()
        results[source] = {"status": status, "count": count, "invalid": invalid, "deferred": 0,
                           "missing_detail": details, "missing_prices": prices, "missing_dates": dates}

    def failed_source(source: str, exc: Exception) -> None:
        LOGGER.error("%s collection failed: %s", source, type(exc).__name__)
        message = str(exc) if isinstance(exc, FeedError) else ("공식 공고 조회 시간 초과 · 다음 수집에서 재시도" if isinstance(exc, TimeoutError) else f"수집 실패: {type(exc).__name__}")
        saved = len(durable_identities.get(source, set()))
        # A later archive/model failure cannot invalidate already committed
        # current notices. Explain the missing stage and retain useful coverage.
        status = "partial" if saved else "error"
        with SessionLocal() as session:
            record_source_status(session, source, status,
                f"공식 공고 {saved}건 저장 · 나머지 공고 조회 미완료: {message}" if saved else message,
                record_count=saved if saved else None)
            session.commit()
        results[source] = {"status": status, "count": saved}

    async def audit_source(source: str, semaphore: asyncio.Semaphore) -> None:
        queued = pending_documents.get(source, {}).values()
        # First audits/new parser work precede daily rechecks. Persisted dates
        # rotate an unfinished archive forward across later scheduled runs.
        rows = [payload for payload, _ in sorted(queued, key=lambda item: (
            item[1] is not None, item[1] or date.min, _save_priority(item[0], today)))]
        if not rows:
            results[source]["documents_pending"] = 0
            return
        processed = 0
        def document_progress(_payload: dict) -> None:
            nonlocal processed
            processed += 1
            with SessionLocal() as session:
                state = session.get(SourceStatus, source)
                if state is not None:
                    state.message = (state.message or "").split(" · 문서 확인 ")[0] + f" · 문서 확인 처리 {processed}/{len(rows)}건"
                    # The successfully committed raw feed remains available;
                    # progress never turns this source back into running.
                    session.commit()
        # The raw-success timestamp/status is independent of this subphase.
        # Killed hosts leave unstarted audited_on checkpoints pending, while
        # completed rows are skipped on the next run, including archive rows.
        saved = deferred = retained_saved = 0
        for row in rows:
            if monotonic() >= document_deadline:
                break
            if row["external_id"] in retained_reviews.get(source, {}):
                async with semaphore:
                    if monotonic() >= document_deadline:
                        break
                    count, pending = await _review_saved_document(row,
                        retained_reviews[source][row["external_id"]], client, today,
                        deadline=document_deadline)
                    saved += count
                    deferred += pending
                    retained_saved += count - pending
                    document_progress(row)
                await yield_to_deadlines()
            else:
                count, _, pending, *_ = await _save_rows(
                    source, [row], client, today, document_semaphore=semaphore,
                    finalize=False, track_source_progress=False,
                    document_deadline=document_deadline,
                    document_timeout_seconds=DOCUMENT_TIMEOUT_SECONDS,
                    preserve_row_order=True,
                    on_raw_saved=document_progress,
                )
                saved += count
                deferred += pending
        remaining = min(len(rows), max(0, len(rows) - saved) + deferred)
        results[source]["documents_pending"] = remaining
        results[source]["deferred"] = results[source].get("deferred", 0) + deferred
        results[source]["saved_documents_reviewed"] = retained_saved
        with SessionLocal() as session:
            state = session.get(SourceStatus, source)
            if state is not None:
                if remaining and results[source]["status"] in {"ok", "partial"}:
                    results[source]["status"] = "partial"
                state.status = results[source]["status"]
                state.message = (state.message or f"공식 공고 {results[source]['count']}건 저장").split(" · 문서 확인 ")[0] + f" · 문서 확인 {len(rows) - remaining}/{len(rows)}건" + (f" · {remaining}건 다음 수집에서 이어서 확인" if remaining else "")
                session.commit()

    async def collect_competition() -> None:
        await competition_ready.wait()
        try:
            async with asyncio.timeout(COMPETITION_TIMEOUT_SECONDS):
                results[competition.SOURCE] = await competition.run_once(today=today, client=client)
        except TimeoutError:
            # Per-notice competition writes are durable; report the bounded
            # pass separately rather than holding every feed open indefinitely.
            with SessionLocal() as session:
                state = session.get(SourceStatus, competition.SOURCE)
                count = state.record_count or 0 if state else 0
                record_source_status(session, competition.SOURCE, "partial",
                    "경쟁률 확인 시간 한도 · 저장한 결과를 유지하며 다음 수집에서 이어서 확인", record_count=count)
                session.commit()
            results[competition.SOURCE] = {"status": "partial", "count": count}
        except Exception as exc:
            LOGGER.error("Competition collection failed: %s", type(exc).__name__)
            with SessionLocal() as session:
                record_source_status(session, competition.SOURCE, "error", "경쟁률 수집 작업 실패 · 다음 수집에서 다시 확인")
                session.commit()
            results[competition.SOURCE] = {"status": "error", "count": 0}

    async def collect_source(source: str, semaphore: asyncio.Semaphore) -> None:
        try:
            key = _api_key(source)
            if source not in ("sh", "gh") and not key:
                with SessionLocal() as session:
                    record_source_status(session, source, "disabled", "공공데이터포털 API 키 미설정")
                    session.commit()
                results[source] = {"status": "disabled", "count": 0}
                return
            with SessionLocal() as session:
                record_source_status(session, source, "running", "공식 공고 수집 중")
                session.commit()
            async with asyncio.timeout(FEED_TIMEOUT_SECONDS):
                source_warning = None
                if source == "cheongyak_home":
                    async def save_current_rows(current_rows: list[dict]) -> None:
                        changed = [row for row in current_rows
                            if streamed_rows.get(source, {}).get(row.get("external_id")) != row]
                        if changed or not current_rows:
                            await save_feed_batch(source, changed)
                        with SessionLocal() as session:
                            state = session.get(SourceStatus, source)
                            state.message = f"현재 접수 공고 {len(durable_identities.get(source, set()))}건 저장 · 과거 공고 가격 조회 중"
                            session.commit()
                        competition_ready.set()

                    rows = await reb.collect(client, key, start, end,
                        today=today, on_current_rows=save_current_rows,
                        on_rows=lambda batch: save_feed_batch(source, batch))
                elif source == "myhome":
                    rows = await myhome.collect(client, key, start, end, on_rows=lambda batch: save_feed_batch(source, batch))
                elif source == "lh":
                    rows = await lh.collect(client, key, start, end, on_rows=lambda batch: save_feed_batch(source, batch))
                elif source == "ih":
                    rows = await ih.collect(client, key, start, end,
                        on_rows=lambda batch: save_feed_batch(source, batch))
                elif source == "sh":
                    rows = await boards.collect_sh(client, start, end, on_rows=lambda batch: save_feed_batch(source, batch))
                else:
                    rows, source_warning = await boards.collect_gh(client, start, end, on_rows=lambda batch: save_feed_batch(source, batch))
                await finish_feed(source, rows, source_warning)
            if pending_documents.get(source):
                with SessionLocal() as session:
                    state = session.get(SourceStatus, source)
                    state.status = "partial"
                    state.message = (state.message or "") + f" · 문서 확인 0/{len(pending_documents[source])}건"
                    session.commit()
        except Exception as exc:
            failed_source(source, exc)
        finally:
            if source == "cheongyak_home":
                competition_ready.set()
            # Saved documents can be upgraded when this feed failed before its
            # first row or when its API key is disabled. Preserve that feed's
            # status/timestamps/count and append document progress separately.
            if source in results:
                await audit_source(source, semaphore)

    try:
        # Only document work shares a fair turn. Saving a raw feed never waits
        # for another provider's PDF, so an interruption preserves every ready
        # feed's complete inventory and successful collection timestamp.
        semaphore = asyncio.Semaphore(1)
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(collect_competition())
            for source in OFFICIAL_SOURCES:
                tasks.create_task(collect_source(source, semaphore))
        return results
    finally:
        if own_client:
            await client.aclose()


async def run_cycle(*, job_id: str | None = None, collector_database: bool = False) -> dict[str, dict] | None:
    """Share collection ownership across manual, Compose and scheduled CLI runs."""
    init_db()
    with collector_session_limits(SessionLocal) if collector_database else nullcontext():
        return await _run_initialized_cycle(job_id=job_id)


async def _run_initialized_cycle(*, job_id: str | None = None) -> dict[str, dict] | None:
    if job_id:
        if not renew_collection(job_id):
            LOGGER.info("Collection job is no longer owned; skipping")
            return None
    else:
        state, claimed = claim_collection("scheduled")
        if not claimed:
            LOGGER.info("Collection already running; skipping duplicate cycle")
            return None
        job_id = state.job_id
    try:
        with CollectionHeartbeat(job_id):
            result = await run_once()
        failed = [source for source, value in result.items() if value.get("status") == "error"]
        message = "수집을 마쳤습니다. 출처별 결과를 확인하세요."
        pending = sum(value.get("documents_pending", 0) for value in result.values())
        if pending:
            message = f"공식 공고 저장을 마쳤습니다. 문서 {pending}건은 다음 수집에서 이어서 확인합니다."
        if failed:
            message = f"수집을 마쳤으나 {len(failed)}개 출처에서 실패했습니다. 출처별 사유를 확인하세요." + (f" 문서 {pending}건은 다음 수집에서 이어서 확인합니다." if pending else "")
        finish_collection(job_id, "completed", message)
        return result
    except BaseException as error:
        interrupted = isinstance(error, (KeyboardInterrupt, asyncio.CancelledError))
        finish_collection(
            job_id, "interrupted" if interrupted else "error",
            "수집 실행이 중단되었습니다. 다시 수집할 수 있습니다." if interrupted else "수집 실행에 실패했습니다. 출처별 상태를 확인하고 다시 시도하세요.",
        )
        raise


async def _forever() -> None:
    while True:
        started = monotonic()
        result = await run_cycle(collector_database=True)
        LOGGER.info("Collection cycle complete: %s", result)
        await asyncio.sleep(max(60, POLL_SECONDS - (monotonic() - started)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect official Korean housing subscription notices")
    parser.add_argument("--once", action="store_true", help="Run a single collection cycle then exit")
    parser.add_argument("--job-id", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.job_id and not args.once:
        parser.error("--job-id requires --once")
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    def stop(_signum, _frame):
        raise KeyboardInterrupt()

    previous_term = signal.signal(signal.SIGTERM, stop)
    try:
        if args.once:
            result = asyncio.run(run_cycle(job_id=args.job_id, collector_database=True))
            if args.job_id and result is None:
                raise SystemExit(1)
            LOGGER.info("Collection cycle complete: %s", result)
        else:
            asyncio.run(_forever())
    except KeyboardInterrupt:
        pass
    except Exception as error:
        # Database and transport exception text may include credentials.
        LOGGER.error("Collection execution failed: %s", type(error).__name__)
        raise SystemExit(1)
    finally:
        signal.signal(signal.SIGTERM, previous_term)


if __name__ == "__main__":
    main()
