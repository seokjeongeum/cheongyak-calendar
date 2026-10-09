"""Durable feed rows and bounded document fairness survive interrupted cycles."""
from __future__ import annotations

import asyncio
import copy
from datetime import date, datetime, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db import init_db, make_engine
from app.ingest import worker
from app.models import CompetitionRevision, DocumentExtractionState, IntegrationSetting, Notice, SourceStatus
from app.repository import record_competition_result, record_source_status, upsert_notice
from test_repository_api import example_notice

TODAY = date(2026, 10, 9)
BEFORE = datetime(2026, 10, 8, tzinfo=timezone.utc)
SOURCES = ("cheongyak_home", "myhome", "lh", "ih", "sh", "gh")


@pytest.fixture()
def store(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'fair-worker.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "init_db", lambda: None)
    monkeypatch.setattr(worker, "_api_key", lambda source: "mock-common-key")
    monkeypatch.setattr(worker, "extraction_configured", lambda: False)
    with factory() as session:
        for source in SOURCES:
            record_source_status(session, source, "ok", "이전 성공", BEFORE, 99)
        session.commit()
    yield factory, engine
    engine.dispose()


def rows_for(source: str, count: int = 1) -> list[dict]:
    rows = []
    for index in range(count):
        row = example_notice(source, f"{source}-{index}")
        row["title"] = row["external_id"]
        row["announcement_date"] = TODAY.isoformat()
        row["official_url"] = f"https://official.example/{source}/{index}"
        row["events"] = [{"kind": "general", "label": "접수", "start_date": "2026-10-12"}]
        rows.append(row)
    return rows


def mock_feeds(monkeypatch, rows: dict[str, list[dict]], observed: list[str]) -> None:
    def collector(source):
        async def collect(*args):
            observed.append(source)
            return copy.deepcopy(rows[source])
        return collect

    for source, module in (("cheongyak_home", worker.reb), ("myhome", worker.myhome),
                           ("lh", worker.lh), ("ih", worker.ih)):
        monkeypatch.setattr(module, "collect", collector(source))
    monkeypatch.setattr(worker.boards, "collect_sh", collector("sh"))

    async def gh(*args):
        observed.append("gh")
        return copy.deepcopy(rows["gh"]), "공식 보드 일부 확인 필요"
    monkeypatch.setattr(worker.boards, "collect_gh", gh)


def no_network(request):
    raise AssertionError("All collection and extraction are mocked")


@pytest.mark.asyncio
async def test_all_feed_rows_and_competition_start_before_fair_serial_document_turns(store, monkeypatch):
    factory, engine = store
    rows = {source: rows_for(source, 5 if source == "cheongyak_home" else 1) for source in SOURCES}
    # Preserve the old first audit of a newly inserted historical notice too.
    rows["cheongyak_home"][-1]["announcement_date"] = "2026-05-01"
    rows["cheongyak_home"][-1]["events"] = [{"kind": "general", "label": "접수", "start_date": "2026-05-10"}]
    rows["cheongyak_home"][0]["ingest_warning"] = "공식 상세 일부 미확보"
    observed_feeds = []
    mock_feeds(monkeypatch, rows, observed_feeds)
    expected_ids = {row["external_id"] for source_rows in rows.values() for row in source_rows}
    documents = []
    competition_started = False
    active = 0

    async def competition(**kwargs):
        nonlocal competition_started
        with factory() as session:
            assert set(session.scalars(select(Notice.external_id))) == expected_ids
        competition_started = True
        await asyncio.sleep(0)
        return {"status": "ok", "count": 0}

    async def enrich(payload, **kwargs):
        nonlocal active
        assert competition_started and observed_feeds == list(SOURCES)
        active += 1
        assert active == 1  # One public document request chain, never six.
        documents.append((payload["source"], payload["external_id"]))
        with factory() as session:
            assert set(session.scalars(select(Notice.external_id))) == expected_ids
            state = session.get(SourceStatus, payload["source"])
            assert state.status == "running"
            assert state.record_count == len(rows[payload["source"]])
            assert state.last_success_at.replace(tzinfo=timezone.utc) == BEFORE
        # A transport wait lets all source tasks join the fair semaphore queue.
        await asyncio.sleep(0)
        active -= 1
        return payload

    monkeypatch.setattr(worker.competition, "run_once", competition)
    monkeypatch.setattr(worker, "enrich_notice", enrich)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        result = await worker.run_once(today=TODAY, client=client)
    assert [source for source, identity in documents[:len(SOURCES)]] == list(SOURCES)
    assert {identity for source, identity in documents} == expected_ids
    assert result["cheongyak_home"]["count"] == 5
    assert result["cheongyak_home"]["missing_detail"] == 1
    assert result["gh"]["status"] == "partial"
    with factory() as session:
        assert session.get(SourceStatus, "cheongyak_home").record_count == 5
        assert "문서 확인" not in session.get(SourceStatus, "cheongyak_home").message
    assert engine.pool.checkedout() == 0


@pytest.mark.asyncio
async def test_stop_during_first_pdf_keeps_all_feed_rows_without_premature_success(store, monkeypatch):
    factory, engine = store
    rows = {source: rows_for(source, 4 if source == "cheongyak_home" else 1) for source in SOURCES}
    observed_feeds = []
    mock_feeds(monkeypatch, rows, observed_feeds)
    started = asyncio.Event()
    competition_cancelled = asyncio.Event()
    document_cancelled = asyncio.Event()

    async def competition(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            competition_cancelled.set()

    async def enrich(payload, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            document_cancelled.set()

    monkeypatch.setattr(worker.competition, "run_once", competition)
    monkeypatch.setattr(worker, "enrich_notice", enrich)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        cycle = asyncio.create_task(worker.run_once(today=TODAY, client=client))
        await asyncio.wait_for(started.wait(), timeout=5)
        assert engine.pool.checkedout() == 0  # No connection while awaiting a PDF/turn.
        cycle.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cycle
    assert competition_cancelled.is_set() and document_cancelled.is_set()
    assert observed_feeds == list(SOURCES)
    with factory() as session:
        assert set(session.scalars(select(Notice.external_id))) == {
            row["external_id"] for source_rows in rows.values() for row in source_rows
        }
        pending = session.scalars(select(DocumentExtractionState)).all()
        assert len(pending) == sum(len(source_rows) for source_rows in rows.values())
        assert all(state.audited_on is None and state.deferred_until is None for state in pending)
        for source in SOURCES:
            state = session.get(SourceStatus, source)
            assert state.status == "running"
            assert state.record_count == len(rows[source])
            assert state.last_success_at.replace(tzinfo=timezone.utc) == BEFORE
            assert state.last_attempt_at.replace(tzinfo=timezone.utc) > BEFORE
            assert "문서 확인 대기" in state.message
    assert engine.pool.checkedout() == 0


@pytest.mark.asyncio
async def test_cached_first_source_yields_before_other_sources_finish(store, monkeypatch):
    factory, _ = store
    rows = {source: rows_for(source, 8 if source == "cheongyak_home" else 1) for source in SOURCES}
    with factory() as session:
        for source_rows in rows.values():
            for row in source_rows:
                upsert_notice(session, row)
                session.add(DocumentExtractionState(source=row["source"], external_id=row["external_id"], audited_on=TODAY))
        session.commit()
    mock_feeds(monkeypatch, rows, [])
    completed = []
    original_record = worker.record_source_status

    def record(session, source, status, *args, **kwargs):
        if source in SOURCES and status in {"ok", "partial"}:
            completed.append(source)
        return original_record(session, source, status, *args, **kwargs)

    async def competition(**kwargs):
        return {"status": "ok", "count": 0}

    audited = []
    async def enrich(payload, **kwargs):
        audited.append(payload["external_id"])
        return payload

    monkeypatch.setattr(worker, "record_source_status", record)
    monkeypatch.setattr(worker.competition, "run_once", competition)
    monkeypatch.setattr(worker, "enrich_notice", enrich)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        await worker.run_once(today=TODAY, client=client)
    assert not audited
    assert completed == [*SOURCES[1:], SOURCES[0]]


@pytest.mark.asyncio
async def test_pending_first_archive_audit_survives_restart_and_runs_once(store, monkeypatch):
    factory, _ = store
    row = rows_for("cheongyak_home")[0]
    row["announcement_date"] = "2026-05-01"
    row["events"] = [{"kind": "general", "label": "접수", "start_date": "2026-05-10"}]
    assert not worker._active_notice(row, TODAY)
    calls = []

    async def enrich(payload, **kwargs):
        calls.append(kwargs["known_document_hash"])
        return {**payload, "document_hash": "historical-official-bytes"}

    monkeypatch.setattr(worker, "enrich_notice", enrich)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        await worker._save_rows(row["source"], [copy.deepcopy(row)], client, TODAY,
            audit_documents=False, finalize=False)
        with factory() as session:
            state = session.get(DocumentExtractionState, (row["source"], row["external_id"]))
            assert state.audited_on is None
            assert session.scalar(select(Notice).where(Notice.external_id == row["external_id"])).document_hash is None
        # A fresh SessionLocal invocation has no in-memory first-pass queue.
        await worker._save_rows(row["source"], [copy.deepcopy(row)], client, TODAY)
        await worker._save_rows(row["source"], [copy.deepcopy(row)], client, TODAY)
    assert calls == [None]
    with factory() as session:
        assert session.get(DocumentExtractionState, (row["source"], row["external_id"])).audited_on == TODAY
        notice = session.scalar(select(Notice).where(Notice.external_id == row["external_id"]))
        assert notice.document_hash == "historical-official-bytes"
        assert notice.revisions[0].payload["document_hash"] is None


@pytest.mark.asyncio
async def test_global_model_quota_is_reloaded_between_source_turns(store, monkeypatch):
    factory, _ = store
    rows = {source: rows_for(source) for source in SOURCES}
    mock_feeds(monkeypatch, rows, [])
    monkeypatch.setattr(worker, "extraction_configured", lambda: True)
    allowed = []

    async def competition(**kwargs):
        return {"status": "ok", "count": 0}

    async def enrich(payload, **kwargs):
        allowed.append((payload["source"], kwargs["allow_gemini"]))
        await asyncio.sleep(0)
        return {**payload, "extraction_status": "quota"} if kwargs["allow_gemini"] else payload

    monkeypatch.setattr(worker.competition, "run_once", competition)
    monkeypatch.setattr(worker, "enrich_notice", enrich)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        result = await worker.run_once(today=TODAY, client=client)
    assert allowed == [(source, index == 0) for index, source in enumerate(SOURCES)]
    assert all(result[source]["deferred"] == 1 for source in SOURCES)
    with factory() as session:
        assert session.get(DocumentExtractionState, worker.QUOTA_STATE_KEY).deferred_until is not None


@pytest.mark.asyncio
async def test_core_save_preserves_review_prices_competition_history_and_settings(store, monkeypatch):
    factory, _ = store
    row = example_notice()
    row["announcement_date"] = TODAY.isoformat()
    row["document_hash"] = "reviewed-original-bytes"
    reviewed = {"kind": "applicant_regions", "effect": "metadata", "verification": "official",
                "source": "official_document_parser", "document_hash": row["document_hash"],
                "regions": [{"region_code": "11", "region_name": "서울특별시"}], "scope_complete": True}
    row["rules"].append(reviewed)
    with factory() as session:
        notice = upsert_notice(session, row)
        record_competition_result(session, notice, "ok", complete=True, unit_types=["59A"], observed_at=BEFORE,
            rows=[{"unit_type": "59A", "rank": 1, "residence_area": "local", "supply_count": 3,
                   "application_count": 12, "competition_rate": "4.00", "result_status": "first_closed",
                   "evidence_url": "https://official.example/competition"}])
        session.add(DocumentExtractionState(source=row["source"], external_id=row["external_id"], audited_on=TODAY))
        session.add(IntegrationSetting(name="DATA_GO_KR_API_KEY", value="mock-stored-key"))
        session.commit()
        prior_revision = copy.deepcopy(notice.revisions[0].payload)
        prior_events = [(e.kind, e.start_date, e.end_date) for e in notice.events]
        prior_prices = [(p.unit_type, p.amount_krw) for p in notice.prices]
    feed = {key: row[key] for key in ("source", "external_id", "title", "official_url", "announcement_date")}
    feed["rules"] = [{"kind": "housing_classification", "effect": "metadata", "housing_kind": "private", "verification": "official"}]

    audited = []
    async def enrich(payload, **kwargs):
        audited.append(payload["external_id"])
        return payload

    monkeypatch.setattr(worker, "enrich_notice", enrich)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        await worker._save_rows(row["source"], [copy.deepcopy(feed)], client, TODAY,
            audit_documents=False, finalize=False)
        with factory() as session:
            state = session.get(SourceStatus, row["source"])
            assert state.status == "running" and state.last_success_at.replace(tzinfo=timezone.utc) == BEFORE
            assert session.get(DocumentExtractionState, (row["source"], row["external_id"])).audited_on == TODAY
        await worker._save_rows(row["source"], [copy.deepcopy(feed)], client, TODAY,
            document_semaphore=asyncio.Semaphore(1), stored_count=1)
    assert not audited  # Unchanged source with today's audit remains cached.
    with factory() as session:
        saved = session.scalar(select(Notice).where(Notice.external_id == row["external_id"]))
        assert saved.document_hash == row["document_hash"] and reviewed in saved.rules
        assert [(e.kind, e.start_date, e.end_date) for e in saved.events] == prior_events
        assert [(p.unit_type, p.amount_krw) for p in saved.prices] == prior_prices
        assert saved.revisions[0].payload == prior_revision
        assert saved.competition_state.status == "ok" and saved.competition_state.complete
        assert saved.competitions[0].competition_rate == "4.00"
        assert len(session.scalars(select(CompetitionRevision)).all()) == 1
        assert session.get(IntegrationSetting, "DATA_GO_KR_API_KEY").value == "mock-stored-key"


@pytest.mark.asyncio
async def test_core_changed_url_still_audits_after_same_day_old_url_review(store, monkeypatch):
    factory, _ = store
    row = example_notice()
    row["announcement_date"] = TODAY.isoformat()
    row["document_hash"] = "original-reviewed-bytes"
    reviewed = {"kind": "applicant_regions", "effect": "metadata", "verification": "official",
                "source": "official_document_parser", "document_hash": row["document_hash"],
                "regions": [{"region_code": "11", "region_name": "서울특별시"}], "scope_complete": True,
                "evidence_url": row["official_url"]}
    row["rules"].append(reviewed)
    with factory() as session:
        upsert_notice(session, row)
        session.add(DocumentExtractionState(source=row["source"], external_id=row["external_id"], audited_on=TODAY))
        session.commit()
    row["official_url"] = "https://official.example/current-correction"
    row.pop("document_hash")  # Official feed updates URLs without byte hashes.
    row["rules"] = [{"kind": "housing_classification", "effect": "metadata",
                     "housing_kind": "private", "verification": "official"}]
    calls = []

    async def enrich(payload, **kwargs):
        calls.append((payload["official_url"], kwargs["known_document_hash"]))
        return {**payload, "document_hash": "current-corrected-bytes"}

    monkeypatch.setattr(worker, "enrich_notice", enrich)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        await worker._save_rows(row["source"], [copy.deepcopy(row)], client, TODAY,
            audit_documents=False, finalize=False)
        with factory() as session:
            assert session.get(DocumentExtractionState, (row["source"], row["external_id"])).audited_on is None
            known = session.scalar(select(Notice).where(Notice.external_id == row["external_id"]))
            assert known.document_hash == "original-reviewed-bytes" and reviewed in known.rules
        await worker._save_rows(row["source"], [copy.deepcopy(row)], client, TODAY,
            document_semaphore=asyncio.Semaphore(1), stored_count=1)
    assert calls == [(row["official_url"], "original-reviewed-bytes")]
    with factory() as session:
        corrected = session.scalar(select(Notice).where(Notice.external_id == row["external_id"]))
        assert corrected.document_hash == "current-corrected-bytes" and reviewed not in corrected.rules
        assert session.get(DocumentExtractionState, (row["source"], row["external_id"])).audited_on == TODAY
