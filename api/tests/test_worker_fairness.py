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
from app.extract.pipeline import _diagnostics_rule
from app.extract.official_rules import PARSER_VERSION
from app.ingest import worker
from app.ingest.common import FeedError
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
    async def no_detail_lookup(payload, **kwargs):
        return payload
    monkeypatch.setattr(worker, "enrich_detail_link", no_detail_lookup)
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
        async def collect(*args, **kwargs):
            observed.append(source)
            return copy.deepcopy(rows[source])
        return collect

    for source, module in (("cheongyak_home", worker.reb), ("myhome", worker.myhome),
                           ("lh", worker.lh), ("ih", worker.ih)):
        monkeypatch.setattr(module, "collect", collector(source))
    monkeypatch.setattr(worker.boards, "collect_sh", collector("sh"))

    async def gh(*args, **kwargs):
        observed.append("gh")
        return copy.deepcopy(rows["gh"]), "공식 보드 일부 확인 필요"
    monkeypatch.setattr(worker.boards, "collect_gh", gh)


def no_network(request):
    raise AssertionError("All collection and extraction are mocked")


@pytest.mark.asyncio
async def test_all_source_tasks_start_and_ready_rows_are_durable_before_fair_document_turns(store, monkeypatch):
    factory, engine = store
    rows = {source: rows_for(source, 30 if source == "cheongyak_home" else 1) for source in SOURCES}
    # Preserve the old first audit of a newly inserted historical notice too.
    for historical in rows["cheongyak_home"][1:]:
        historical["announcement_date"] = "2026-05-01"
        historical["events"] = [{"kind": "general", "label": "접수", "start_date": "2026-05-10"}]
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
            assert rows["cheongyak_home"][0]["external_id"] in set(session.scalars(select(Notice.external_id)))
        competition_started = True
        await asyncio.sleep(0)
        return {"status": "ok", "count": 0}

    async def enrich(payload, **kwargs):
        nonlocal active
        assert observed_feeds == list(SOURCES)
        active += 1
        assert active == 1  # One public document request chain, never six.
        documents.append((payload["source"], payload["external_id"]))
        with factory() as session:
            durable = session.scalar(select(Notice).where(Notice.external_id == payload["external_id"]))
            assert durable is not None and durable.document_hash is None
            state = session.get(SourceStatus, payload["source"])
            assert state.status == "partial"
            assert state.record_count == len(rows[payload["source"]])
            assert state.last_success_at.replace(tzinfo=timezone.utc) > BEFORE
        # A transport wait lets all source tasks join the fair semaphore queue.
        await asyncio.sleep(0)
        active -= 1
        return payload

    monkeypatch.setattr(worker.competition, "run_once", competition)
    monkeypatch.setattr(worker, "enrich_notice", enrich)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        result = await worker.run_once(today=TODAY, client=client)
    assert {source for source, identity in documents[:len(SOURCES)]} == set(SOURCES)
    assert competition_started
    assert {identity for source, identity in documents} == expected_ids
    assert result["cheongyak_home"]["count"] == 30
    assert result["cheongyak_home"]["missing_detail"] == 1
    assert result["gh"]["status"] == "partial"
    with factory() as session:
        assert set(session.scalars(select(Notice.external_id))) == expected_ids
        assert session.get(SourceStatus, "cheongyak_home").record_count == 30
        assert "문서 확인 30/30건" in session.get(SourceStatus, "cheongyak_home").message
    assert engine.pool.checkedout() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("slow_source", ["myhome", "gh"])
async def test_slow_collector_does_not_gate_other_sources_or_their_durable_documents(store, monkeypatch, slow_source):
    factory, engine = store
    rows = {source: rows_for(source) for source in SOURCES}
    observed = []
    mock_feeds(monkeypatch, rows, observed)
    slow_started = asyncio.Event()
    slow_cancelled = asyncio.Event()
    document_cancelled = asyncio.Event()
    ready_documents = asyncio.Event()
    hold_source = "gh" if slow_source == "myhome" else "sh"
    documented = set()
    competition_calls = []

    async def blocked(*args, **kwargs):
        observed.append(slow_source)
        slow_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            slow_cancelled.set()

    monkeypatch.setattr(worker.myhome if slow_source == "myhome" else worker.boards,
                        "collect" if slow_source == "myhome" else "collect_gh", blocked)

    async def competition(**kwargs):
        competition_calls.append(True)
        with factory() as session:
            assert session.scalar(select(Notice).where(Notice.source == "cheongyak_home")) is not None
        return {"status": "ok", "count": 0}

    async def enrich(payload, **kwargs):
        assert slow_started.is_set() and observed == list(SOURCES)
        with factory() as session:
            assert session.scalar(select(Notice).where(Notice.external_id == payload["external_id"])) is not None
            blocked_state = session.get(SourceStatus, slow_source)
            assert blocked_state.status == "running" and blocked_state.message == "공식 공고 수집 중"
        documented.add(payload["source"])
        if payload["source"] == hold_source:
            ready_documents.set()
            try:
                await asyncio.Event().wait()
            finally:
                document_cancelled.set()
        await asyncio.sleep(0)
        return payload

    monkeypatch.setattr(worker.competition, "run_once", competition)
    monkeypatch.setattr(worker, "enrich_notice", enrich)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        cycle = asyncio.create_task(worker.run_once(today=TODAY, client=client))
        await asyncio.wait_for(ready_documents.wait(), timeout=5)
        assert documented == set(SOURCES) - {slow_source}
        assert competition_calls == [True]
        assert engine.pool.checkedout() == 0
        cycle.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cycle
    assert slow_cancelled.is_set() and document_cancelled.is_set()
    with factory() as session:
        assert not session.scalars(select(Notice).where(Notice.source == slow_source)).all()
        held = session.scalar(select(Notice).where(Notice.source == hold_source))
        assert held is not None
        assert session.get(DocumentExtractionState, (hold_source, held.external_id)).audited_on is None
        assert session.get(SourceStatus, hold_source).last_success_at.replace(tzinfo=timezone.utc) > BEFORE
        assert session.get(SourceStatus, slow_source).last_success_at.replace(tzinfo=timezone.utc) == BEFORE
        assert all(session.get(SourceStatus, source).last_attempt_at.replace(tzinfo=timezone.utc) > BEFORE for source in SOURCES)
    assert engine.pool.checkedout() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["cancel", "failure", "success"])
async def test_reb_current_batch_is_durable_and_starts_rates_before_archival_models(store, monkeypatch, outcome):
    factory, engine = store
    rows = {source: rows_for(source) for source in SOURCES}
    current = rows_for("cheongyak_home", 2)
    current[0]["ingest_warning"] = "공식 상세 일부 미확보"
    archive = rows_for("cheongyak_home")[0]
    archive["external_id"] = "historical-reb"
    archive["announcement_date"] = "2026-05-01"
    archive["events"] = [{"kind": "general", "label": "접수", "start_date": "2026-05-10"}]
    archive_started = asyncio.Event()
    release_archive = asyncio.Event()
    archive_cancelled = asyncio.Event()
    mock_feeds(monkeypatch, rows, [])
    audited = []
    competition_calls = []

    async def reb_collect(client, key, start, end, *, today, on_current_rows, on_rows=None):
        assert today == TODAY
        original = copy.deepcopy(current)
        await on_current_rows(current)
        assert current == original  # Worker cannot mutate the eventual full feed.
        archive_started.set()
        try:
            await release_archive.wait()
        finally:
            if not release_archive.is_set():
                archive_cancelled.set()
        if outcome == "failure":
            raise FeedError("공식 과거 주택형 가격 조회 실패")
        return copy.deepcopy([*current, archive])

    async def competition(**kwargs):
        competition_calls.append(True)
        with factory() as session:
            assert session.scalar(select(Notice).where(Notice.source == "cheongyak_home")) is not None
        return {"status": "ok", "count": 0}

    async def enrich(payload, **kwargs):
        audited.append(payload["external_id"])
        document_hash = f"reviewed-{payload['external_id']}"
        reviewed = {"kind": "applicant_regions", "effect": "metadata", "verification": "official",
                    "source": "official_document_parser", "parser_version": PARSER_VERSION,
                    "document_hash": document_hash, "regions": [{"region_code": "11", "region_name": "서울특별시"}],
                    "scope_complete": True}
        await asyncio.sleep(0)
        return {**payload, "document_hash": document_hash,
                "rules": [*payload.get("rules", []), reviewed, _diagnostics_rule([], "complete", document_hash)]}

    monkeypatch.setattr(worker.reb, "collect", reb_collect)
    monkeypatch.setattr(worker.competition, "run_once", competition)
    monkeypatch.setattr(worker, "enrich_notice", enrich)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        cycle = asyncio.create_task(worker.run_once(today=TODAY, client=client))
        await asyncio.wait_for(archive_started.wait(), timeout=5)
        with factory() as session:
            state = session.get(SourceStatus, "cheongyak_home")
            assert state.status == "partial" and state.record_count == 2
            assert state.last_success_at.replace(tzinfo=timezone.utc) > BEFORE
            assert state.message == "현재 접수 공고 2건 저장 · 과거 공고 가격 조회 중"
            for current_row in current:
                notice = session.scalar(select(Notice).where(Notice.external_id == current_row["external_id"]))
                assert notice.document_hash is None
                assert session.get(DocumentExtractionState, (notice.source, notice.external_id)).audited_on is None
                assert notice.prices[0].amount_krw == current_row["prices"][0]["amount_krw"]
            assert session.scalar(select(Notice).where(Notice.external_id == archive["external_id"])) is None
        assert competition_calls == [True] and engine.pool.checkedout() == 0
        if outcome == "cancel":
            cycle.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cycle
            assert archive_cancelled.is_set()
            expected_count, expected_status = 2, "partial"
        else:
            release_archive.set()
            result = await asyncio.wait_for(cycle, timeout=5)
            expected_count, expected_status = (2, "partial") if outcome == "failure" else (3, "partial")
            assert result["cheongyak_home"]["count"] == expected_count
            assert result["cheongyak_home"]["status"] == expected_status
        with factory() as session:
            state = session.get(SourceStatus, "cheongyak_home")
            assert state.record_count == expected_count and state.status == expected_status
            assert state.last_success_at.replace(tzinfo=timezone.utc) > BEFORE
            for current_row in current:
                assert audited.count(current_row["external_id"]) == (0 if outcome == "cancel" else 1)
                notice = session.scalar(select(Notice).where(Notice.external_id == current_row["external_id"]))
                assert notice.document_hash == (None if outcome == "cancel" else f"reviewed-{current_row['external_id']}")
                if outcome != "cancel":
                    assert any(rule.get("kind") == "applicant_regions" for rule in notice.rules)
    assert competition_calls == [True] and engine.pool.checkedout() == 0


@pytest.mark.asyncio
async def test_empty_current_callback_releases_rates_while_archival_models_wait(store, monkeypatch):
    factory, _ = store
    mock_feeds(monkeypatch, {source: rows_for(source) for source in SOURCES}, [])
    archival_started = asyncio.Event()
    rates_started = asyncio.Event()

    async def reb_collect(client, key, start, end, *, today, on_current_rows, on_rows=None):
        await on_current_rows([])
        archival_started.set()
        await asyncio.Event().wait()

    async def competition(**kwargs):
        rates_started.set()
        return {"status": "ok", "count": 0}

    async def enrich(payload, **kwargs):
        await asyncio.sleep(0)
        return payload

    monkeypatch.setattr(worker.reb, "collect", reb_collect)
    monkeypatch.setattr(worker.competition, "run_once", competition)
    monkeypatch.setattr(worker, "enrich_notice", enrich)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        cycle = asyncio.create_task(worker.run_once(today=TODAY, client=client))
        await asyncio.wait_for(archival_started.wait(), timeout=5)
        await asyncio.wait_for(rates_started.wait(), timeout=5)
        with factory() as session:
            state = session.get(SourceStatus, "cheongyak_home")
            assert state.status == "partial" and state.record_count == 0
            assert state.last_success_at.replace(tzinfo=timezone.utc) > BEFORE
            assert "과거 공고 가격 조회 중" in state.message
        cycle.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cycle


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [asyncio.CancelledError, RuntimeError])
async def test_final_repeat_prefix_cannot_lower_already_durable_current_count(store, monkeypatch, failure):
    factory, _ = store
    current = rows_for("cheongyak_home", 2)
    with factory() as session:
        for row in current:
            row["document_hash"] = f"known-{row['external_id']}"
            upsert_notice(session, row)
            session.add(DocumentExtractionState(source=row["source"], external_id=row["external_id"], audited_on=TODAY))
        record_source_status(session, "cheongyak_home", "running", "현재 접수 공고 2건 저장", record_count=2)
        session.commit()
    attempted = []

    async def enrich(payload, **kwargs):
        attempted.append(payload["external_id"])
        return payload

    def stop_after_first_repeat(payload):
        raise failure()

    monkeypatch.setattr(worker, "enrich_notice", enrich)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        with pytest.raises(failure):
            await worker._save_rows("cheongyak_home", copy.deepcopy(current), client, TODAY,
                persist_before_audit=True, progress_floor=2, on_raw_saved=stop_after_first_repeat)
    assert not attempted
    with factory() as session:
        state = session.get(SourceStatus, "cheongyak_home")
        assert state.record_count == 2 and state.last_success_at.replace(tzinfo=timezone.utc) == BEFORE
        assert "공식 공고 2건 저장" in state.message
        assert len(session.scalars(select(Notice).where(Notice.source == "cheongyak_home")).all()) == 2


@pytest.mark.asyncio
async def test_stop_during_first_pdf_keeps_its_raw_row_and_all_feed_attempts_without_fake_success(store, monkeypatch):
    factory, engine = store
    rows = {source: rows_for(source, 4 if source == "cheongyak_home" else 1) for source in SOURCES}
    observed_feeds = []
    mock_feeds(monkeypatch, rows, observed_feeds)
    started = asyncio.Event()
    competition_cancelled = asyncio.Event()
    competition_started = asyncio.Event()
    document_cancelled = asyncio.Event()

    async def competition(**kwargs):
        competition_started.set()
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
        await asyncio.wait_for(competition_started.wait(), timeout=5)
        for _ in range(20):
            with factory() as session:
                if len(session.scalars(select(Notice)).all()) == sum(map(len, rows.values())):
                    break
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert engine.pool.checkedout() == 0  # No connection while awaiting a PDF/turn.
        cycle.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cycle
    assert competition_cancelled.is_set() and document_cancelled.is_set()
    assert observed_feeds == list(SOURCES)
    with factory() as session:
        # Every ready raw feed can finish while the first PDF is suspended.
        expected_ids = {row["external_id"] for source_rows in rows.values() for row in source_rows}
        assert set(session.scalars(select(Notice.external_id))) == expected_ids
        pending = session.scalars(select(DocumentExtractionState)).all()
        assert len(pending) == len(expected_ids)
        assert all(state.audited_on is None and state.deferred_until is None for state in pending)
        for source in SOURCES:
            state = session.get(SourceStatus, source)
            assert state.status == "partial"
            assert state.record_count == len(rows[source])
            assert state.last_success_at.replace(tzinfo=timezone.utc) > BEFORE
            assert "문서 확인" in state.message
    assert engine.pool.checkedout() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("reb_state", ["disabled", "empty", "failed", "invalid"])
async def test_competition_gate_finishes_without_any_valid_reb_row(store, monkeypatch, reb_state):
    factory, _ = store
    rows = {source: rows_for(source) for source in SOURCES}
    observed = []
    if reb_state == "empty":
        rows["cheongyak_home"] = []
    if reb_state == "invalid":
        rows["cheongyak_home"][0]["title"] = ""
    mock_feeds(monkeypatch, rows, observed)
    if reb_state == "disabled":
        monkeypatch.setattr(worker, "_api_key", lambda source: "" if source == "cheongyak_home" else "mock-key")
    if reb_state == "failed":
        async def failed(*args, **kwargs):
            observed.append("cheongyak_home")
            raise FeedError("공식 API 수집 실패")
        monkeypatch.setattr(worker.reb, "collect", failed)
    competition_calls = []

    async def competition(**kwargs):
        competition_calls.append(True)
        with factory() as session:
            assert not session.scalars(select(Notice).where(Notice.source == "cheongyak_home")).all()
        return {"status": "ok", "count": 0}

    async def enrich(payload, **kwargs):
        await asyncio.sleep(0)
        return payload

    monkeypatch.setattr(worker.competition, "run_once", competition)
    monkeypatch.setattr(worker, "enrich_notice", enrich)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        result = await asyncio.wait_for(worker.run_once(today=TODAY, client=client), timeout=5)
    assert competition_calls == [True]
    assert result["cheongyak_home"]["status"] == {
        "disabled": "disabled", "empty": "partial", "failed": "error", "invalid": "partial",
    }[reb_state]


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


@pytest.mark.asyncio
async def test_document_timeout_does_not_block_other_sources_and_retains_raw_success(store, monkeypatch):
    factory, engine = store
    rows = {source: rows_for(source) for source in SOURCES}
    mock_feeds(monkeypatch, rows, [])
    monkeypatch.setattr(worker, "DOCUMENT_TIMEOUT_SECONDS", .02)
    calls = []
    async def competition(**kwargs):
        return {"status": "ok", "count": 0}
    async def enrich(payload, **kwargs):
        calls.append(payload["source"])
        if payload["source"] == "cheongyak_home":
            await asyncio.Event().wait()
        return {**payload, "document_hash": "read-" + payload["source"]}
    monkeypatch.setattr(worker.competition, "run_once", competition)
    monkeypatch.setattr(worker, "enrich_notice", enrich)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        result = await asyncio.wait_for(worker.run_once(today=TODAY, client=client), timeout=5)
        assert set(calls) == set(SOURCES)
        assert result["cheongyak_home"]["documents_pending"] == 1
        with factory() as session:
            state = session.get(SourceStatus, "cheongyak_home")
            assert state.status == "partial" and state.record_count == 1
            assert state.last_success_at.replace(tzinfo=timezone.utc) > BEFORE
            pending = session.get(DocumentExtractionState, ("cheongyak_home", rows["cheongyak_home"][0]["external_id"]))
            assert pending.audited_on is None and pending.deferred_until is not None
            notice = session.scalar(select(Notice).where(Notice.source == "cheongyak_home"))
            assert notice.prices[0].amount_krw == rows["cheongyak_home"][0]["prices"][0]["amount_krw"]
            diagnostic = next(rule for rule in notice.rules if rule.get("kind") == "document_diagnostics")
            assert diagnostic["diagnostics"][0]["code"] == "audit_timeout"
            assert all(session.get(DocumentExtractionState, (source, rows[source][0]["external_id"])).audited_on == TODAY for source in SOURCES[1:])
        # A fresh cycle skips both completed documents and the timed-out row's
        # cooldown. A poison notice cannot consume every restart's first turn.
        calls.clear()
        await worker.run_once(today=TODAY, client=client)
        assert calls == []
    assert engine.pool.checkedout() == 0


@pytest.mark.asyncio
async def test_zero_document_budget_finishes_raw_feeds_then_resumes_pending_archive(store, monkeypatch):
    factory, _ = store
    rows = {source: rows_for(source, 2) for source in SOURCES}
    for source_rows in rows.values():
        source_rows[1]["announcement_date"] = "2026-05-01"
        source_rows[1]["events"] = [{"kind": "general", "label": "접수", "start_date": "2026-05-10"}]
    mock_feeds(monkeypatch, rows, [])
    calls = []
    async def competition(**kwargs):
        return {"status": "ok", "count": 0}
    async def enrich(payload, **kwargs):
        calls.append(payload["external_id"])
        return {**payload, "document_hash": "reviewed-" + payload["external_id"]}
    monkeypatch.setattr(worker.competition, "run_once", competition)
    monkeypatch.setattr(worker, "enrich_notice", enrich)
    monkeypatch.setattr(worker, "DOCUMENT_BUDGET_SECONDS", 0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        first = await worker.run_once(today=TODAY, client=client)
        assert calls == [] and all(first[source]["documents_pending"] == 2 for source in SOURCES)
        with factory() as session:
            assert len(session.scalars(select(Notice)).all()) == 12
            assert all(session.get(SourceStatus, source).status == "partial" and session.get(SourceStatus, source).record_count == 2 for source in SOURCES)
            assert all(state.audited_on is None for state in session.scalars(select(DocumentExtractionState)))
        monkeypatch.setattr(worker, "DOCUMENT_BUDGET_SECONDS", 30)
        second = await worker.run_once(today=TODAY, client=client)
        assert len(calls) == 12 and all(second[source]["documents_pending"] == 0 for source in SOURCES)
        calls.clear()
        await worker.run_once(today=TODAY, client=client)
        assert calls == []


@pytest.mark.asyncio
async def test_feed_timeout_is_bounded_and_retains_already_saved_current_batch(store, monkeypatch):
    factory, _ = store
    rows = {source: rows_for(source) for source in SOURCES}
    mock_feeds(monkeypatch, rows, [])
    monkeypatch.setattr(worker, "FEED_TIMEOUT_SECONDS", .02)
    async def reb_collect(client, key, start, end, *, today, on_current_rows, on_rows=None):
        await on_current_rows(copy.deepcopy(rows["cheongyak_home"]))
        await asyncio.Event().wait()
    async def competition(**kwargs):
        return {"status": "ok", "count": 0}
    async def enrich(payload, **kwargs):
        return {**payload, "document_hash": "reviewed-" + payload["source"]}
    monkeypatch.setattr(worker.reb, "collect", reb_collect)
    monkeypatch.setattr(worker.competition, "run_once", competition)
    monkeypatch.setattr(worker, "enrich_notice", enrich)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        result = await asyncio.wait_for(worker.run_once(today=TODAY, client=client), timeout=5)
    assert result["cheongyak_home"]["status"] == "partial" and result["cheongyak_home"]["count"] == 1
    with factory() as session:
        state = session.get(SourceStatus, "cheongyak_home")
        assert "나머지 공고 조회 미완료" in state.message and "시간 초과" in state.message
        assert state.last_success_at.replace(tzinfo=timezone.utc) > BEFORE
        assert session.get(DocumentExtractionState, ("cheongyak_home", rows["cheongyak_home"][0]["external_id"])).audited_on == TODAY
        assert all(session.get(SourceStatus, source).status != "running" for source in SOURCES)


@pytest.mark.asyncio
async def test_competition_timeout_does_not_keep_complete_feeds_running(store, monkeypatch):
    factory, _ = store
    rows = {source: rows_for(source) for source in SOURCES}
    mock_feeds(monkeypatch, rows, [])
    monkeypatch.setattr(worker, "COMPETITION_TIMEOUT_SECONDS", .02)
    async def competition(**kwargs):
        await asyncio.Event().wait()
    async def enrich(payload, **kwargs):
        return payload
    monkeypatch.setattr(worker.competition, "run_once", competition)
    monkeypatch.setattr(worker, "enrich_notice", enrich)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        result = await asyncio.wait_for(worker.run_once(today=TODAY, client=client), timeout=5)
    assert result[worker.competition.SOURCE]["status"] == "partial"
    with factory() as session:
        assert all(session.get(SourceStatus, source).status != "running" for source in SOURCES)
        assert "시간 한도" in session.get(SourceStatus, worker.competition.SOURCE).message


@pytest.mark.asyncio
async def test_myhome_list_is_durable_before_slow_detail_timeout_and_next_pass_continues(store, monkeypatch):
    factory, _ = store
    actual_collect = worker.myhome.collect
    rows = {source: rows_for(source) for source in SOURCES}
    row = rows['myhome'][0]
    row.pop('prices', None)
    mock_feeds(monkeypatch, rows, [])
    monkeypatch.setattr(worker.myhome, 'collect', actual_collect)
    monkeypatch.setattr(worker.myhome, 'OPERATIONS', (('public-sale', 'public_sale'),))
    monkeypatch.setattr(worker.myhome, 'normalize', lambda data, category: copy.deepcopy(row))
    async def listing(*args, **kwargs):
        return {'response': {'body': {'item': [{'pblancId': row['external_id']}], 'totalCount': 1}}}
    monkeypatch.setattr(worker.myhome, 'get_json', listing)
    detail_started = asyncio.Event()
    async def blocked_detail(client, payload, notice_id):
        with factory() as session:
            saved = session.scalar(select(Notice).where(Notice.source == 'myhome'))
            assert saved is not None and saved.external_id == row['external_id']
            assert session.get(SourceStatus, 'myhome').last_success_at.replace(tzinfo=timezone.utc) > BEFORE
        detail_started.set()
        # Trigger the timeout only after the page's durable-save assertion.
        # A global 50ms test deadline can expire during unrelated providers'
        # synchronous SQLite commits under full-suite CPU load.
        async with asyncio.timeout(.02):
            await asyncio.Event().wait()
    monkeypatch.setattr(worker.myhome, 'enrich_sale_detail', blocked_detail)
    monkeypatch.setattr(worker, 'FEED_TIMEOUT_SECONDS', 10)
    async def competition(**kwargs):
        return {'status': 'ok', 'count': 0}
    async def enrich(payload, **kwargs):
        return {**payload, 'document_hash': 'reviewed-' + payload['source']}
    monkeypatch.setattr(worker.competition, 'run_once', competition)
    monkeypatch.setattr(worker, 'enrich_notice', enrich)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        first = await asyncio.wait_for(worker.run_once(today=TODAY, client=client), timeout=5)
        assert detail_started.is_set()
        assert first['myhome']['count'] == 1 and first['myhome']['status'] == 'partial'
        with factory() as session:
            assert session.scalar(select(Notice).where(Notice.source == 'myhome')).document_hash == 'reviewed-myhome'
            assert session.get(DocumentExtractionState, ('myhome', row['external_id'])).audited_on == TODAY
        async def ready_detail(client, payload, notice_id):
            payload['prices'] = [{'unit_type': '84', 'amount_krw': 300000000, 'price_kind': 'sale_total', 'verification': 'official', 'basis_label': '공식 공급가격'}]
        monkeypatch.setattr(worker.myhome, 'enrich_sale_detail', ready_detail)
        monkeypatch.setattr(worker, 'FEED_TIMEOUT_SECONDS', 10)
        second = await worker.run_once(today=TODAY, client=client)
        assert second['myhome']['count'] == 1 and second['myhome']['missing_prices'] == 0
        with factory() as session:
            saved = session.scalar(select(Notice).where(Notice.source == 'myhome'))
            assert saved.document_hash == 'reviewed-myhome' and saved.prices[0].amount_krw == 300000000
            assert '나머지 공고 조회 미완료' not in session.get(SourceStatus, 'myhome').message


@pytest.mark.asyncio
async def test_lh_later_page_failure_preserves_first_page_inventory_and_pending_audits(store, monkeypatch):
    factory, _ = store
    actual_collect = worker.lh.collect
    rows = {source: rows_for(source) for source in SOURCES}
    mock_feeds(monkeypatch, rows, [])
    monkeypatch.setattr(worker.lh, 'collect', actual_collect)
    monkeypatch.setattr(worker.lh, 'HOUSING_CATEGORIES', {'05': 'public_sale'})
    batch = rows_for('lh', 100)
    monkeypatch.setattr(worker.lh, 'normalize', lambda data, category: copy.deepcopy(batch[data['index']]))
    async def listing(client, url, params):
        if params['PAGE'] == 2:
            with factory() as session:
                assert len(session.scalars(select(Notice).where(Notice.source == 'lh')).all()) == 100
            raise worker.FeedError('공식 다음 페이지 연결 실패')
        return {'dsList': [{'index': i} for i in range(100)], 'totalCount': 200}
    monkeypatch.setattr(worker.lh, 'get_json', listing)
    monkeypatch.setattr(worker, 'DOCUMENT_BUDGET_SECONDS', 0)
    async def competition(**kwargs):
        return {'status': 'ok', 'count': 0}
    monkeypatch.setattr(worker.competition, 'run_once', competition)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        result = await asyncio.wait_for(worker.run_once(today=TODAY, client=client), timeout=10)
    assert result['lh']['count'] == 100 and result['lh']['status'] == 'partial'
    assert result['lh']['documents_pending'] == 100
    with factory() as session:
        state = session.get(SourceStatus, 'lh')
        assert state.record_count == 100 and state.last_success_at.replace(tzinfo=timezone.utc) > BEFORE
        assert '다음 페이지' in state.message
        assert all(state.audited_on is None for state in session.scalars(select(DocumentExtractionState).where(DocumentExtractionState.source == 'lh')))


@pytest.mark.asyncio
@pytest.mark.parametrize("callback_count", [1, 2])
async def test_streamed_unchanged_rows_are_not_written_again_when_complete_feed_returns(store, monkeypatch, callback_count):
    _, _ = store
    rows = {source: rows_for(source) for source in SOURCES}
    mock_feeds(monkeypatch, rows, [])
    async def streamed(client, key, start, end, *, on_rows):
        for _ in range(callback_count):
            await on_rows(copy.deepcopy(rows['lh']))
        return copy.deepcopy(rows['lh'])
    monkeypatch.setattr(worker.lh, 'collect', streamed)
    writes = []
    actual_upsert = worker.upsert_notice
    def upsert(session, payload):
        writes.append((payload['source'], payload['external_id']))
        return actual_upsert(session, payload)
    monkeypatch.setattr(worker, 'upsert_notice', upsert)
    monkeypatch.setattr(worker, 'DOCUMENT_BUDGET_SECONDS', 0)
    async def competition(**kwargs):
        return {'status': 'ok', 'count': 0}
    monkeypatch.setattr(worker.competition, 'run_once', competition)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        result = await worker.run_once(today=TODAY, client=client)
    assert result['lh']['count'] == 1
    assert writes.count(('lh', rows['lh'][0]['external_id'])) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('source', ['cheongyak_home', 'ih'])
async def test_streamed_feed_batch_survives_next_request_failure_without_erasing_history(store, monkeypatch, source):
    factory, _ = store
    rows = {name: [] for name in SOURCES}
    mock_feeds(monkeypatch, rows, [])
    row = rows_for(source)[0]
    with factory() as session:
        notice = upsert_notice(session, {**row, 'document_hash': 'existing-official-document'})
        notice_id = notice.id
        prior_prices = [(price.unit_type, price.amount_krw) for price in notice.prices]
        prior_revision_count = len(notice.revisions)
        session.commit()
    ready = copy.deepcopy(row)
    ready['title'] = '새로 받은 공식 제목'
    ready.pop('prices')
    ready.pop('rules')
    async def failing_feed(client, key, start, end, *, on_rows, **kwargs):
        await on_rows([ready])
        with factory() as session:
            saved = session.get(Notice, notice_id)
            assert saved.title == ready['title']
            assert [(price.unit_type, price.amount_krw) for price in saved.prices] == prior_prices
            assert saved.document_hash == 'existing-official-document'
            assert len(saved.revisions) >= prior_revision_count
        raise FeedError('상위 API 연결 실패: ConnectError', retryable=True)
    monkeypatch.setattr(worker.reb if source == 'cheongyak_home' else worker.ih, 'collect', failing_feed)
    monkeypatch.setattr(worker, 'DOCUMENT_BUDGET_SECONDS', 0)
    async def competition(**kwargs):
        return {'status': 'ok', 'count': 0}
    monkeypatch.setattr(worker.competition, 'run_once', competition)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        result = await worker.run_once(today=TODAY, client=client)
    assert result[source]['status'] == 'partial' and result[source]['count'] == 1
    with factory() as session:
        state = session.get(SourceStatus, source)
        assert state.record_count == 1 and state.status == 'partial'
        assert 'ConnectError' in state.message and '나머지 공고 조회 미완료' in state.message
        assert state.last_success_at.replace(tzinfo=timezone.utc) > BEFORE
        saved = session.get(Notice, notice_id)
        assert [(price.unit_type, price.amount_krw) for price in saved.prices] == prior_prices
        assert saved.document_hash == 'existing-official-document'
        assert len(saved.revisions) >= prior_revision_count


@pytest.mark.asyncio
async def test_worker_does_not_write_streamed_current_rows_again_on_current_and_final_callbacks(store, monkeypatch):
    factory, _ = store
    mock_feeds(monkeypatch, {source: [] for source in SOURCES}, [])
    current, archive = rows_for('cheongyak_home', 2)
    archive['announcement_date'] = '2026-05-01'
    archive['events'] = [{'kind': 'general', 'label': '접수', 'start_date': '2026-05-12'}]
    writes = []
    save_rows = worker._save_rows
    async def observe_rows(source, rows, *args, **kwargs):
        if source == 'cheongyak_home' and kwargs.get('audit_documents') is False:
            writes.extend(row['external_id'] for row in rows)
        return await save_rows(source, rows, *args, **kwargs)
    monkeypatch.setattr(worker, '_save_rows', observe_rows)
    async def feed(client, key, start, end, *, on_rows, on_current_rows, **kwargs):
        await on_rows([copy.deepcopy(current)])
        await on_current_rows([copy.deepcopy(current)])
        await on_rows([copy.deepcopy(archive)])
        return copy.deepcopy([current, archive])
    monkeypatch.setattr(worker.reb, 'collect', feed)
    monkeypatch.setattr(worker, 'DOCUMENT_BUDGET_SECONDS', 0)
    async def competition(**kwargs):
        return {'status': 'ok', 'count': 0}
    monkeypatch.setattr(worker.competition, 'run_once', competition)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        result = await worker.run_once(today=TODAY, client=client)
    assert writes == [current['external_id'], archive['external_id']]
    assert result['cheongyak_home']['count'] == 2
    with factory() as session:
        assert len(list(session.scalars(select(Notice).where(Notice.source == 'cheongyak_home')))) == 2
