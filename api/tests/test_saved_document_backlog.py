"""Retained official documents can advance while their list API is offline."""

import copy
from datetime import date, datetime, timedelta, timezone
import re

import httpx
import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import sessionmaker

from app.db import init_db, make_engine
from app.extract.pipeline import _diagnostics_rule
from app.extract.official_rules import PARSER_VERSION
from app.ingest import worker
from app.ingest.common import FeedError
from app.models import CompetitionRevision, DocumentExtractionState, Notice, NoticeRevision, SourceStatus
from app.repository import _existing_payload, record_competition_result, record_source_status, upsert_notice
from test_repository_api import example_notice

TODAY = date(2026, 10, 12)
BEFORE = datetime(2026, 10, 11, tzinfo=timezone.utc)


@pytest.fixture()
def store(monkeypatch, tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'saved-documents.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "init_db", lambda: None)
    monkeypatch.setattr(worker, "extraction_configured", lambda: False)
    monkeypatch.setattr(worker, "_api_key", lambda _: "")

    async def empty(*args, **kwargs):
        return []

    async def empty_gh(*args, **kwargs):
        return [], None

    async def competition(**kwargs):
        return {"status": "ok", "count": 0}

    async def unchanged(payload, **kwargs):
        return payload

    monkeypatch.setattr(worker.boards, "collect_sh", empty)
    monkeypatch.setattr(worker.boards, "collect_gh", empty_gh)
    monkeypatch.setattr(worker.competition, "run_once", competition)
    monkeypatch.setattr(worker, "enrich_detail_link", unchanged)
    yield factory, engine
    engine.dispose()


def insert(factory, number="1", *, source="cheongyak_home", stale=True, audited=TODAY, deferred=None):
    row = example_notice(source, number)
    row.update(title=f"현재 공식 공고 {source} {number}", address=f"서울 {source} {number}",
        announcement_date="2026-10-01", official_url=f"https://www.myhome.go.kr/{source}/{number}.pdf",
        events=[{"kind": "general", "label": "신청 접수", "start_date": "2026-10-12", "end_date": "2026-10-14"}])
    metadata = {"kind": "housing_classification", "effect": "metadata", "housing_kind": "private", "verification": "official", "source": source}
    diagnostic = _diagnostics_rule([], "partial", "retained-document")
    if stale:
        diagnostic["parser_version"] = "prior-parser"
    row["rules"] = [metadata, diagnostic]
    with factory() as session:
        notice = upsert_notice(session, {**row, "document_hash": "retained-document"})
        notice.last_feed_hash = "original-feed-hash"
        notice.last_feed_review_hash = "original-review-hash"
        notice.last_feed_version = notice.version
        state = DocumentExtractionState(source=source, external_id=number, audited_on=audited,
            deferred_until=deferred, document_checkpoint=worker._document_checkpoint(notice))
        session.add(state)
        record_source_status(session, source, "ok", "이전 공식 공고 6건 저장", BEFORE, 6)
        session.commit()
        return notice.id, row


def current_review(payload):
    url, digest = payload["official_url"], payload["document_hash"]
    rule = {"kind": "age_min", "effect": "admission", "value": 19, "verification": "official",
        "source": "official_document_parser", "parser_version": PARSER_VERSION,
        "document_hash": digest, "evidence_url": url, "supply_type": "general", "evidence_text": "만19세 이상"}
    return {**payload, "rules": [rule, _diagnostics_rule([], "partial", digest)],
        # These stale snapshot fields must never be applied by a retained review.
        "title": "문서 결과의 오래된 이름", "events": [], "prices": []}


def no_network(request):
    raise AssertionError("Official downloads and feeds are mocked")


@pytest.mark.asyncio
@pytest.mark.parametrize("feed_status", ["error", "disabled"])
async def test_saved_review_upgrades_local_rules_without_claiming_failed_feed_success(store, monkeypatch, feed_status):
    factory, _ = store
    notice_id, row = insert(factory)
    with factory() as session:
        notice = session.get(Notice, notice_id)
        record_competition_result(session, notice, "ok", rows=[{
            "source": "cheongyak_competition", "unit_type": "59A", "rank": 1,
            "residence_area": "local", "competition_rate": "3.20", "supply_count": 10,
            "application_count": 32, "result_status": "open", "verification": "official",
            "evidence_url": "https://www.applyhome.co.kr/official-result", "observed_at": BEFORE,
        }], unit_types=["59A"], complete=False, observed_at=BEFORE)
        session.commit()
        before_prices = [p.amount_krw for p in notice.prices]
        feed_version = notice.last_feed_version
        competition_revisions = session.scalar(select(func.count()).select_from(CompetitionRevision))
    attempts = []
    feed_attempts = []

    async def failed_feed(*args, **kwargs):
        feed_attempts.append(True)
        raise FeedError("상위 API 연결 실패: ConnectTimeout")

    async def review(payload, **kwargs):
        attempts.append(payload["external_id"])
        assert kwargs["allow_gemini"] is False
        with factory() as session:
            status = session.get(SourceStatus, "cheongyak_home")
            assert status.status == feed_status and status.record_count == 6
        return current_review(payload)

    if feed_status == "error":
        monkeypatch.setattr(worker, "_api_key", lambda source: "fictional" if source == "cheongyak_home" else "")
    monkeypatch.setattr(worker.reb, "collect", failed_feed)
    monkeypatch.setattr(worker, "enrich_notice", review)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        result = await worker.run_once(today=TODAY, client=client)
    assert attempts == [row["external_id"]]
    assert len(feed_attempts) == int(feed_status == "error")
    assert result["cheongyak_home"]["status"] == feed_status
    assert result["cheongyak_home"]["count"] == 0
    assert result["cheongyak_home"]["saved_documents_reviewed"] == 1
    with factory() as session:
        notice = session.get(Notice, notice_id)
        status = session.get(SourceStatus, "cheongyak_home")
        assert status.status == feed_status and status.record_count == 6
        assert status.last_success_at.replace(tzinfo=timezone.utc) == BEFORE
        assert "문서 확인 1/1건" in status.message
        assert ("ConnectTimeout" if feed_status == "error" else "API 키 미설정") in status.message
        assert notice.title == row["title"] and notice.events[0].end_date.isoformat() == "2026-10-14"
        assert [p.amount_krw for p in notice.prices] == before_prices
        assert notice.competitions[0].competition_rate == "3.20"
        assert session.scalar(select(func.count()).select_from(CompetitionRevision)) == competition_revisions
        assert notice.last_feed_hash == "original-feed-hash"
        assert notice.last_feed_review_hash == "original-review-hash" and notice.last_feed_version == feed_version
        assert any(r.get("kind") == "age_min" and r.get("parser_version") == PARSER_VERSION for r in notice.rules)
        state = session.get(DocumentExtractionState, ("cheongyak_home", row["external_id"]))
        assert state.audited_on == TODAY and state.document_checkpoint["notice_version"] == notice.version


@pytest.mark.asyncio
async def test_new_raw_feed_replaces_retained_snapshot_and_is_audited_once(store, monkeypatch):
    factory, _ = store
    notice_id, row = insert(factory)
    fresh = {**row, "title": row["title"] + " 정정", "announcement_date": "2026-10-12"}
    attempts = []

    async def feed(*args, **kwargs):
        return [copy.deepcopy(fresh)]

    async def review(payload, **kwargs):
        attempts.append(payload["title"])
        result = current_review(payload)
        result["title"] = payload["title"]
        result["events"] = payload["events"]
        result["prices"] = payload["prices"]
        return result

    monkeypatch.setattr(worker, "_api_key", lambda source: "fictional" if source == "cheongyak_home" else "")
    monkeypatch.setattr(worker.reb, "collect", feed)
    monkeypatch.setattr(worker, "enrich_notice", review)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        result = await worker.run_once(today=TODAY, client=client)
    assert attempts == [fresh["title"]]
    assert result["cheongyak_home"]["saved_documents_reviewed"] == 0
    with factory() as session:
        assert session.get(Notice, notice_id).title == fresh["title"]


def test_valid_current_checkpoint_skips_large_rules_and_competition_transfer(store):
    factory, engine = store
    notice_id, _ = insert(factory, stale=False)
    with factory() as session:
        notice = session.get(Notice, notice_id)
        notice.rules.append({"kind": "source_archive", "evidence_text": "검토된 원문 " * 10000})
        # JSON mutation tracking is explicit, preserving the valid versioned checkpoint.
        notice.rules = [*notice.rules]
        session.commit()
    reads = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("select"):
            reads.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert worker._saved_document_queue(TODAY) == ({}, {})
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert reads
    assert all(not re.search(r"notices\.rules\b|notice_revisions\.payload\b|competition_revisions\.payload\b|unit_competitions\.", sql) for sql in reads)


@pytest.mark.asyncio
async def test_bounded_saved_backlog_rotates_after_successful_checkpoints(store, monkeypatch):
    factory, _ = store
    identities = []
    for number in range(worker.SAVED_DOCUMENT_LIMIT + 2):
        identities.append(insert(factory, str(number))[0])
    # One due but already-current row must not take a stale-parser slot.
    _, due = insert(factory, "due", stale=False, audited=TODAY - timedelta(days=1))
    attempts = []

    async def review(payload, **kwargs):
        attempts.append(payload["external_id"])
        return current_review(payload)

    monkeypatch.setattr(worker, "enrich_notice", review)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        first = await worker.run_once(today=TODAY, client=client)
        assert len(attempts) == worker.SAVED_DOCUMENT_LIMIT
        assert due["external_id"] not in attempts
        assert first["cheongyak_home"]["saved_documents_reviewed"] == worker.SAVED_DOCUMENT_LIMIT
        second = await worker.run_once(today=TODAY, client=client)
    assert len(attempts) == worker.SAVED_DOCUMENT_LIMIT + 3 and len(set(attempts)) == len(attempts)
    assert second["cheongyak_home"]["saved_documents_reviewed"] == 3
    with factory() as session:
        assert all(session.get(DocumentExtractionState, ("cheongyak_home", str(number))).audited_on == TODAY
            for number in range(worker.SAVED_DOCUMENT_LIMIT + 2))


@pytest.mark.asyncio
async def test_failed_saved_audit_keeps_feed_error_and_cooldown_rotates_next_pass(store, monkeypatch):
    factory, _ = store
    notice_id, row = insert(factory, deferred=datetime.now(timezone.utc) + timedelta(hours=3))
    attempts = []

    async def review(payload, **kwargs):
        attempts.append(payload["external_id"])
        raise TimeoutError

    monkeypatch.setattr(worker, "enrich_notice", review)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        first = await worker.run_once(today=TODAY, client=client)
        second = await worker.run_once(today=TODAY, client=client)
    assert attempts == [row["external_id"]]  # New parser overrides the old cooldown exactly once.
    assert first["cheongyak_home"]["status"] == "disabled"
    assert first["cheongyak_home"]["documents_pending"] == 1
    assert first["cheongyak_home"]["saved_documents_reviewed"] == 0
    assert second["cheongyak_home"]["documents_pending"] == 0
    with factory() as session:
        state = session.get(DocumentExtractionState, ("cheongyak_home", row["external_id"]))
        assert state.audited_on is None and state.deferred_until is not None
        notice = session.get(Notice, notice_id)
        diagnostic = next(r for r in notice.rules if r["kind"] == "document_diagnostics")
        assert diagnostic["parser_version"] == PARSER_VERSION and diagnostic["diagnostics"][0]["code"] == "audit_timeout"
        source = session.get(SourceStatus, "cheongyak_home")
        assert source.status == "disabled" and source.record_count == 6
        assert source.last_success_at.replace(tzinfo=timezone.utc) == BEFORE


@pytest.mark.asyncio
async def test_inflight_saved_review_cannot_restore_old_feed_prices_or_source_context(store, monkeypatch):
    factory, _ = store
    notice_id, row = insert(factory)
    pending, retained = worker._saved_document_queue(TODAY)
    payload = pending["cheongyak_home"][row["external_id"]][0]

    async def review(snapshot, **kwargs):
        with factory() as session:
            fresh = session.get(Notice, notice_id)
            prices = _existing_payload(fresh)["prices"]
            prices[0]["amount_krw"] += 50_000_000
            fresh = upsert_notice(session, {"source": fresh.source, "external_id": fresh.external_id,
                "prices": prices, "replace_prices": True})
            fresh.last_feed_review_hash = "corrected-feed-hash"
            session.commit()
        return current_review(snapshot)

    monkeypatch.setattr(worker, "enrich_notice", review)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        count, deferred = await worker._review_saved_document(payload,
            retained["cheongyak_home"][row["external_id"]], client, TODAY, deadline=worker.monotonic() + 10)
    assert (count, deferred) == (1, 1)
    with factory() as session:
        notice = session.get(Notice, notice_id)
        assert notice.prices[0].amount_krw == row["prices"][0]["amount_krw"] + 50_000_000
        assert notice.last_feed_review_hash == "corrected-feed-hash"
        assert not any(r.get("kind") == "age_min" for r in notice.rules)
        assert session.scalar(select(func.count()).select_from(NoticeRevision)) == 2
