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
from datetime import date, datetime, timedelta, timezone
from time import monotonic
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.collection import CollectionHeartbeat, claim_collection, finish_collection, renew_collection
from app.integration_settings import setting_value
from app.extract.pipeline import DOCUMENT_PIPELINE_VERSION, enrich_notice, extraction_configured
from app.models import DocumentExtractionState, Notice, SourceStatus
from app.qualification import is_metadata, merge_poll_rules
from app.repository import NON_APPLICATION_KINDS, is_open_ended_application, lock_notice, record_source_status, resolve_pending_corrections, upsert_notice
from app.schemas import EventPublic

from . import boards, competition, ih, lh, myhome, reb
from .common import FeedError, date_iso

LOGGER = logging.getLogger("cheongyak.ingest")
KST = ZoneInfo("Asia/Seoul")
POLL_SECONDS = 3 * 60 * 60
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


def _failed_document_needs_new_pipeline(existing: Notice | None) -> bool:
    """One same-day retry after a download fix; successful reviews stay cached."""
    return bool(existing and any(
        rule.get("kind") == "document_diagnostics"
        and rule.get("status") in {"unreadable", "error"}
        and rule.get("pipeline_version") != DOCUMENT_PIPELINE_VERSION
        for rule in existing.rules or []
    ))


def _save_progress(session: Session, state: SourceStatus | None, source: str, saved: int, total: int) -> SourceStatus:
    """Commit progress with its notice, retaining the source attempt/success times."""
    message = f"공식 공고 저장 중 · {saved}/{total}건 저장"
    if state is None:
        return record_source_status(session, source, "running", message, record_count=saved)
    state.status = "running"
    state.message = message
    state.record_count = saved
    return state


async def _save_rows(
    source: str, rows: list[dict], client: httpx.AsyncClient, today: date,
    source_warning: str | None = None,
) -> tuple[int, int, int, int, int, int, str]:
    saved = 0
    invalid = 0
    deferred = 0
    missing = 0
    missing_prices = 0
    missing_dates = 0
    with SessionLocal() as session:
        quota_state = session.get(DocumentExtractionState, QUOTA_STATE_KEY)
        source_state = session.get(SourceStatus, source)
        for payload in sorted(rows, key=lambda row: _save_priority(row, today)):
            if payload.get("source") != source:
                invalid += 1
                continue
            identity = (source, str(payload.get("external_id") or ""))
            if payload.pop("ingest_warning", None):
                missing += 1
            existing = session.scalar(select(Notice).where(Notice.source == source, Notice.external_id == identity[1]))
            extraction_state = session.get(DocumentExtractionState, identity)
            url_changed = existing is not None and existing.official_url != payload.get("official_url")
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
            if quota_blocked and extraction_configured() and payload.get("official_url") and _active_notice(payload, today):
                deferred += 1
            should_audit = (
                (existing is None or url_changed or (
                    (extraction_state is None or extraction_state.audited_on != today
                     or _failed_document_needs_new_pipeline(existing) or (
                        extraction_configured() and not quota_blocked
                        and deferred_until is not None and deferred_until <= now
                    ))
                    and _active_notice(payload, today)
                ))
            )
            if should_audit:
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
                    enriched = await enrich_notice(payload, client=client, known_document_hash=known_hash, allow_gemini=allow_gemini)
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
                    LOGGER.warning("Document enrichment failed for %s: %s", source, type(exc).__name__)
            try:
                notice = upsert_notice(session, payload)
                source_state = _save_progress(session, source_state, source, saved + 1, len(rows))
                session.commit()
                saved += 1
                if not any(price.amount_krw is not None or price.monthly_krw is not None for price in notice.prices):
                    missing_prices += 1
                if not any(event.kind not in NON_APPLICATION_KINDS for event in notice.events):
                    missing_dates += 1
            except (ValueError, TypeError) as exc:
                session.rollback()
                invalid += 1
                LOGGER.warning("Skipped invalid %s notice: %s", source, type(exc).__name__)
            except Exception:
                session.rollback()
                raise
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
        record_source_status(session, source, status, ", ".join(message_parts), record_count=saved)
        session.commit()
    return saved, invalid, deferred, missing_prices, missing_dates, missing, status


async def run_once(*, today: date | None = None, client: httpx.AsyncClient | None = None) -> dict[str, dict]:
    """Run every source once; each source records its own last attempt/result."""
    # httpx INFO request logs include query strings and therefore serviceKey.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    init_db()
    today = today or datetime.now(KST).date()
    start, end = today - timedelta(days=LOOKBACK_DAYS), today + timedelta(days=LOOKAHEAD_DAYS)
    own_client = client is None
    client = client or httpx.AsyncClient(headers={"User-Agent": "CheongyakCalendar/1.0 (+public housing notice index)"}, follow_redirects=True)
    results: dict[str, dict] = {}
    try:
        for source in ("cheongyak_home", "myhome", "lh", "ih", "sh", "gh"):
            key = _api_key(source)
            if source not in ("sh", "gh") and not key:
                with SessionLocal() as session:
                    record_source_status(session, source, "disabled", "공공데이터포털 API 키 미설정")
                    session.commit()
                results[source] = {"status": "disabled", "count": 0}
                continue
            # Commit before the potentially long network request so coverage
            # can distinguish active collection from an untouched source.
            with SessionLocal() as session:
                record_source_status(session, source, "running", "공식 공고 수집 중")
                session.commit()
            try:
                source_warning = None
                if source == "cheongyak_home":
                    rows = await reb.collect(client, key, start, end)
                elif source == "myhome":
                    rows = await myhome.collect(client, key, start, end)
                elif source == "lh":
                    rows = await lh.collect(client, key, start, end)
                elif source == "ih":
                    rows = await ih.collect(client, key, start, end)
                elif source == "sh":
                    rows = await boards.collect_sh(client, start, end)
                else:
                    rows, source_warning = await boards.collect_gh(client, start, end)
                saved, invalid, deferred, missing_prices, missing_dates, missing, status = await _save_rows(
                    source, rows, client, today, source_warning
                )
                results[source] = {
                    "status": status, "count": saved, "invalid": invalid, "deferred": deferred,
                    "missing_detail": missing, "missing_prices": missing_prices, "missing_dates": missing_dates,
                }
            except Exception as exc:
                # Avoid leaking URL query strings containing the service key.
                LOGGER.error("%s collection failed: %s", source, type(exc).__name__)
                message = str(exc) if isinstance(exc, FeedError) else f"수집 실패: {type(exc).__name__}"
                with SessionLocal() as session:
                    record_source_status(session, source, "error", message)
                    session.commit()
                results[source] = {"status": "error", "count": 0}
        # Independent collection after notice feeds: this does not send public
        # documents to Gemini or touch any applicant profile.
        try:
            results[competition.SOURCE] = await competition.run_once(today=today, client=client)
        except Exception as exc:
            LOGGER.error("Competition collection failed: %s", type(exc).__name__)
            with SessionLocal() as session:
                record_source_status(session, competition.SOURCE, "error", "경쟁률 수집 작업 실패 · 다음 수집에서 다시 확인")
                session.commit()
            results[competition.SOURCE] = {"status": "error", "count": 0}
        return results
    finally:
        if own_client:
            await client.aclose()


async def run_cycle(*, job_id: str | None = None) -> dict[str, dict] | None:
    """Share collection ownership across manual, Compose and scheduled CLI runs."""
    init_db()
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
        if failed:
            message = f"수집을 마쳤으나 {len(failed)}개 출처에서 실패했습니다. 출처별 사유를 확인하세요."
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
        result = await run_cycle()
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
            result = asyncio.run(run_cycle(job_id=args.job_id))
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
