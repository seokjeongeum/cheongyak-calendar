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

    async def gh(*args):
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
            assert set(session.scalars(select(Notice.external_id))) == {rows["cheongyak_home"][0]["external_id"]}
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
            assert state.status == "running"
            assert state.record_count == sum(source == payload["source"] for source, identity in documents)
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
    assert competition_started
    assert {identity for source, identity in documents} == expected_ids
    assert result["cheongyak_home"]["count"] == 30
    assert result["cheongyak_home"]["missing_detail"] == 1
    assert result["gh"]["status"] == "partial"
    with factory() as session:
        assert set(session.scalars(select(Notice.external_id))) == expected_ids
        assert session.get(SourceStatus, "cheongyak_home").record_count == 30
        assert "문서 확인" not in session.get(SourceStatus, "cheongyak_home").message
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

    async def blocked(*args):
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
        assert session.get(SourceStatus, hold_source).last_success_at.replace(tzinfo=timezone.utc) == BEFORE
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

    async def reb_collect(client, key, start, end, *, today, on_current_rows):
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
            assert state.status == "running" and state.record_count == 2
            assert state.last_success_at.replace(tzinfo=timezone.utc) == BEFORE
            assert state.message == "현재 접수 공고 2건 저장 · 과거 공고 가격 조회 중"
            for current_row in current:
                notice = session.scalar(select(Notice).where(Notice.external_id == current_row["external_id"]))
                assert notice.document_hash == f"reviewed-{current_row['external_id']}"
                assert any(rule.get("kind") == "applicant_regions" for rule in notice.rules)
                assert notice.prices[0].amount_krw == current_row["prices"][0]["amount_krw"]
            assert session.scalar(select(Notice).where(Notice.external_id == archive["external_id"])) is None
        assert competition_calls == [True] and engine.pool.checkedout() == 0
        if outcome == "cancel":
            cycle.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cycle
            assert archive_cancelled.is_set()
            expected_count, expected_status = 2, "running"
        else:
            release_archive.set()
            result = await asyncio.wait_for(cycle, timeout=5)
            expected_count, expected_status = (2, "error") if outcome == "failure" else (3, "partial")
            assert result["cheongyak_home"]["count"] == expected_count
            assert result["cheongyak_home"]["status"] == expected_status
        with factory() as session:
            state = session.get(SourceStatus, "cheongyak_home")
            assert state.record_count == expected_count and state.status == expected_status
            assert (state.last_success_at.replace(tzinfo=timezone.utc) > BEFORE) == (outcome == "success")
            for current_row in current:
                assert audited.count(current_row["external_id"]) == 1
                notice = session.scalar(select(Notice).where(Notice.external_id == current_row["external_id"]))
                assert notice.document_hash == f"reviewed-{current_row['external_id']}"
                assert any(rule.get("kind") == "applicant_regions" for rule in notice.rules)
    assert competition_calls == [True] and engine.pool.checkedout() == 0


@pytest.mark.asyncio
async def test_empty_current_callback_releases_rates_while_archival_models_wait(store, monkeypatch):
    factory, _ = store
    mock_feeds(monkeypatch, {source: rows_for(source) for source in SOURCES}, [])
    archival_started = asyncio.Event()
    rates_started = asyncio.Event()

    async def reb_collect(client, key, start, end, *, today, on_current_rows):
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
            assert state.status == "running" and state.record_count == 0
            assert state.last_success_at.replace(tzinfo=timezone.utc) == BEFORE
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
        assert engine.pool.checkedout() == 0  # No connection while awaiting a PDF/turn.
        cycle.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cycle
    assert competition_cancelled.is_set() and document_cancelled.is_set()
    assert observed_feeds == list(SOURCES)
    with factory() as session:
        assert set(session.scalars(select(Notice.external_id))) == {rows["cheongyak_home"][0]["external_id"]}
        pending = session.scalars(select(DocumentExtractionState)).all()
        assert len(pending) == 1
        assert all(state.audited_on is None and state.deferred_until is None for state in pending)
        for source in SOURCES:
            state = session.get(SourceStatus, source)
            assert state.status == "running"
            assert state.record_count == (1 if source == "cheongyak_home" else 99)
            assert state.last_success_at.replace(tzinfo=timezone.utc) == BEFORE
            assert state.last_attempt_at.replace(tzinfo=timezone.utc) > BEFORE
            assert "1/4건 저장" in state.message if source == "cheongyak_home" else "저장 순서 대기" in state.message
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
