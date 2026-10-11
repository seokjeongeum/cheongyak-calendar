"""Unchanged feed polls transfer scalar retry facts, retaining full archives."""
from __future__ import annotations

import copy
import re
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import sessionmaker

from app.db import init_db, make_engine
from app.extract.pipeline import DOCUMENT_PIPELINE_VERSION, _diagnostics_rule
from app.extract.official_rules import PARSER_VERSION
from app.ingest import worker
from app.models import DocumentExtractionState, Notice, NoticeRevision, UnitCompetition
from app.repository import feed_payload_hash, feed_review_hash, upsert_notice
from test_repository_api import example_notice

TODAY = date(2026, 10, 10)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'worker-transfer.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "extraction_configured", lambda: False)
    async def unchanged(payload, **kwargs):
        return payload
    monkeypatch.setattr(worker, "enrich_detail_link", unchanged)
    yield engine, factory
    engine.dispose()


def raw_row(*, active=False):
    row = example_notice("lh", "future-source-identifier")
    row["announcement_date"] = "2026-10-09" if active else "2026-05-01"
    row["events"] = [{"kind": "general", "label": "접수", "start_date": "2026-10-20" if active else "2026-05-20"}]
    row["rules"] = [{"kind": "housing_classification", "effect": "metadata", "housing_kind": "public", "verification": "official"}]
    return row


def reviewed_rules():
    return [{"kind": "official_additional_condition", "source": "official_document_parser",
             "verification": "official", "document_hash": "archived-source-hash",
             "evidence_url": "https://official.example/future-document.pdf", "evidence_text": "공식 원문과 검토된 조건 " * 20000}]


async def save(row, **kwargs):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError("no live requests")))) as client:
        return await worker._save_rows(row["source"], [copy.deepcopy(row)], client, TODAY, **kwargs)


def sql_capture(engine):
    statements = []
    def captured(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())
    event.listen(engine, "before_cursor_execute", captured)
    return statements, captured


def assert_no_full_documents(statements):
    reads = [statement for statement in statements if statement.lstrip().startswith("select")]
    assert reads
    assert all(not re.search(r"notices\.rules\b|notice_revisions\.payload\b|competition_revisions\.payload\b|unit_competitions\.", statement) for statement in reads)
    assert all(not re.search(r"update notices set .*\brules\s*=", statement) for statement in statements)


@pytest.mark.asyncio
@pytest.mark.parametrize("with_state", [False, True])
async def test_repeated_huge_archival_poll_avoids_document_transfer_and_revision_write(store, with_state):
    engine, factory = store
    row, retained = raw_row(), reviewed_rules()
    with factory() as session:
        notice = upsert_notice(session, {**row, "document_hash": "archived-source-hash", "rules": row["rules"] + retained})
        if with_state:
            session.add(DocumentExtractionState(source=row["source"], external_id=row["external_id"], audited_on=TODAY))
        session.commit()
        notice_id = notice.id
    await save(row, audit_documents=False)
    with factory() as session:
        before = session.get(Notice, notice_id)
        version, revisions = before.version, session.scalar(select(func.count()).select_from(NoticeRevision))
        expected_rules, expected_prices = before.rules, [price.amount_krw for price in before.prices]
    statements, captured = sql_capture(engine)
    try:
        await save(row, audit_documents=False)
        await save(row, audit_documents=True)
    finally:
        event.remove(engine, "before_cursor_execute", captured)
    assert_no_full_documents(statements)
    with factory() as session:
        after = session.get(Notice, notice_id)
        assert after.version == version and after.rules == expected_rules
        assert [price.amount_krw for price in after.prices] == expected_prices
        assert session.scalar(select(func.count()).select_from(NoticeRevision)) == revisions
        state = session.get(DocumentExtractionState, (row["source"], row["external_id"]))
        assert (state.audited_on == TODAY) if with_state else state is None


@pytest.mark.asyncio
async def test_large_archival_batch_never_downloads_reviews_or_saved_competition_rows(store):
    engine, factory = store
    rows = []
    with factory() as session:
        for index in range(24):
            row = {**raw_row(), "external_id": f"archive-{index}", "title": f"이전 공식 공고 {index}"}
            rows.append(row)
            notice = upsert_notice(session, {**row, "document_hash": "archived-source-hash", "rules": row["rules"] + reviewed_rules()})
            session.add(DocumentExtractionState(source=row["source"], external_id=row["external_id"], audited_on=TODAY))
            session.add(UnitCompetition(notice_id=notice.id, unit_type="084A", competition_rate="12.8",
                                        evidence_url="https://official.example/archived-result"))
        session.commit()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError("no live requests")))) as client:
        # One normalization establishes the raw-feed checksum on an older DB.
        await worker._save_rows("lh", copy.deepcopy(rows), client, TODAY, audit_documents=False)
        with factory() as session:
            baseline = [(notice.id, notice.version, notice.content_hash) for notice in session.scalars(select(Notice))]
            # A legacy/recovered checkpoint need not fetch an inactive review.
            for state in session.scalars(select(DocumentExtractionState)):
                state.document_checkpoint = None
            revision_count = session.scalar(select(func.count()).select_from(NoticeRevision))
            session.commit()
        statements, captured = sql_capture(engine)
        try:
            await worker._save_rows("lh", copy.deepcopy(rows), client, TODAY, audit_documents=True)
            await worker._save_rows("lh", copy.deepcopy(rows), client, TODAY, audit_documents=False)
        finally:
            event.remove(engine, "before_cursor_execute", captured)
    assert_no_full_documents(statements)
    with factory() as session:
        assert [(notice.id, notice.version, notice.content_hash) for notice in session.scalars(select(Notice))] == baseline
        assert session.scalar(select(func.count()).select_from(NoticeRevision)) == revision_count
        assert session.scalar(select(func.count()).select_from(UnitCompetition)) == len(rows)
        assert all(reviewed_rules()[0] in notice.rules for notice in session.scalars(select(Notice)))


@pytest.mark.asyncio
async def test_unchanged_pending_task_is_queued_without_loading_review_then_audited(store, monkeypatch):
    engine, factory = store
    row = raw_row(active=True)
    await save(row, audit_documents=False)
    pending, metrics = [], []
    statements, captured = sql_capture(engine)
    try:
        await save(row, audit_documents=False, on_audit_pending=lambda payload, checkpoint: pending.append((payload, checkpoint)),
                   on_row_result=metrics.append)
    finally:
        event.remove(engine, "before_cursor_execute", captured)
    assert_no_full_documents(statements)
    assert pending == [(row, None)] and metrics[0]["external_id"] == row["external_id"]
    attempts = []
    async def reviewed(payload, **kwargs):
        attempts.append(payload["external_id"])
        return {**payload, "document_hash": "archived-source-hash", "rules": payload["rules"] + reviewed_rules()
                + [_diagnostics_rule([], "partial", "archived-source-hash")]}
    monkeypatch.setattr(worker, "enrich_notice", reviewed)
    await save(pending[0][0])
    await save(row)
    assert attempts == [row["external_id"]]
    with factory() as session:
        notice = session.scalar(select(Notice))
        state = session.get(DocumentExtractionState, (row["source"], row["external_id"]))
        assert state.audited_on == TODAY and state.document_checkpoint["notice_version"] == notice.version
        assert state.document_checkpoint["diagnostics"][0]["pipeline_version"] == DOCUMENT_PIPELINE_VERSION
        assert notice.last_feed_hash == feed_payload_hash(row) and notice.last_feed_version == notice.version
        assert reviewed_rules()[0] in notice.rules


@pytest.mark.asyncio
async def test_cached_outdated_parser_remains_pending_without_full_json_poll(store, monkeypatch):
    engine, factory = store
    row = raw_row(active=True)
    with factory() as session:
        notice = upsert_notice(session, {**row, "document_hash": "archived-source-hash", "rules": row["rules"] + reviewed_rules()
                     + [{**_diagnostics_rule([], "partial", "archived-source-hash"), "parser_version": "prior-parser"}]})
        session.add(DocumentExtractionState(source=row["source"], external_id=row["external_id"], audited_on=TODAY))
        session.commit()
    await save(row, audit_documents=False)
    pending = []
    statements, captured = sql_capture(engine)
    try:
        await save(row, audit_documents=False, on_audit_pending=lambda payload, checkpoint: pending.append((payload, checkpoint)))
    finally:
        event.remove(engine, "before_cursor_execute", captured)
    assert_no_full_documents(statements)
    assert pending == [(row, None)]
    attempts = []
    async def reviewed(payload, **kwargs):
        attempts.append(True)
        return {**payload, "rules": [rule for rule in payload["rules"] if rule.get("kind") != "document_diagnostics"]
                + [_diagnostics_rule([], "partial", "archived-source-hash")]}
    monkeypatch.setattr(worker, "enrich_notice", reviewed)
    await save(row)
    await save(row)
    assert attempts == [True]
    with factory() as session:
        state = session.get(DocumentExtractionState, (row["source"], row["external_id"]))
        assert state.document_checkpoint["diagnostics"][0]["parser_version"] == PARSER_VERSION


@pytest.mark.asyncio
async def test_raw_changes_and_external_revision_invalidate_scalar_shortcut(store):
    _, factory = store
    row = raw_row()
    await save(row, audit_documents=False)
    changed = copy.deepcopy(row)
    changed["prices"][0]["amount_krw"] += 1
    changed["events"][0]["end_date"] = "2026-05-21"
    await save(changed, audit_documents=False)
    with factory() as session:
        notice = session.scalar(select(Notice))
        assert notice.prices[0].amount_krw == changed["prices"][0]["amount_krw"]
        assert notice.events[0].end_date.isoformat() == "2026-05-21"
        first_version = notice.version
        upsert_notice(session, {**changed, "rules": changed["rules"] + reviewed_rules()})
        session.commit()
        assert notice.version > first_version and notice.last_feed_version < notice.version
    await save(changed, audit_documents=False)
    with factory() as session:
        notice = session.scalar(select(Notice))
        assert reviewed_rules()[0] in notice.rules
        assert notice.last_feed_version == notice.version


@pytest.mark.asyncio
@pytest.mark.parametrize("correction", ["title", "announcement_date", "inventory", "units", "application_date"])
async def test_same_day_source_correction_requeues_one_review_with_unchanged_url(store, monkeypatch, correction):
    engine, factory = store
    row = raw_row(active=True)
    row["rules"].append({"kind": "offered_supplies", "effect": "metadata", "verification": "official", "source": "lh",
                         "supplies": [{"supply_type": "general", "unit_type": "84A", "supply_count": 12}]})
    attempts = []
    async def reviewed(payload, **kwargs):
        attempts.append(payload["title"])
        return {**payload, "document_hash": "archived-source-hash", "rules": payload["rules"] + reviewed_rules()
                + [_diagnostics_rule([], "partial", "archived-source-hash")]}
    monkeypatch.setattr(worker, "enrich_notice", reviewed)
    await save(row)
    changed = copy.deepcopy(row)
    if correction == "title":
        changed["title"] += " (정정)"
    elif correction == "announcement_date":
        changed["announcement_date"] = "2026-10-10"
    elif correction == "inventory":
        changed["rules"][-1]["supplies"][0]["supply_count"] = 15
        with factory() as session:
            state = session.get(DocumentExtractionState, (row["source"], row["external_id"]))
            state.audited_on = None
            state.deferred_until = datetime.now(timezone.utc) + timedelta(hours=3)
            session.commit()
    elif correction == "units":
        changed["prices"][0]["unit_type"] = "059Z"
    else:
        changed["events"][0]["start_date"] = "2026-10-21"
    assert changed["official_url"] == row["official_url"]
    pending = []
    await save(changed, audit_documents=False, on_audit_pending=lambda payload, checkpoint: pending.append((payload, checkpoint)))
    with factory() as session:
        notice = session.scalar(select(Notice))
        assert reviewed_rules()[0] in notice.rules
        state = session.get(DocumentExtractionState, (row["source"], row["external_id"]))
        assert state.audited_on is None and state.deferred_until is None
        assert notice.last_feed_review_hash == feed_review_hash(changed)
    assert pending == [(changed, None)]
    await save(changed)
    statements, captured = sql_capture(engine)
    try:
        await save(changed)
    finally:
        event.remove(engine, "before_cursor_execute", captured)
    assert attempts == [row["title"], changed["title"]]
    assert_no_full_documents(statements)


@pytest.mark.asyncio
async def test_observation_and_update_timestamps_do_not_reaudit_same_day(store, monkeypatch):
    _, factory = store
    row = raw_row(active=True)
    row["updated_at"] = "2026-10-10T00:00:00Z"
    row["rules"].append({"kind": "offered_supplies", "effect": "metadata", "verification": "official", "source": "lh",
                         "observed_at": "2026-10-10T00:00:00Z", "supplies": [{"supply_type": "general", "unit_type": "84A", "supply_count": 12}]})
    attempts = []
    async def reviewed(payload, **kwargs):
        attempts.append(True)
        return {**payload, "document_hash": "archived-source-hash", "rules": payload["rules"] + reviewed_rules()
                + [_diagnostics_rule([], "partial", "archived-source-hash")]}
    monkeypatch.setattr(worker, "enrich_notice", reviewed)
    await save(row)
    for hour in (3, 6):
        changed = copy.deepcopy(row)
        changed["updated_at"] = changed["rules"][-1]["observed_at"] = f"2026-10-10T{hour:02}:00:00Z"
        assert feed_review_hash(changed) == feed_review_hash(row)
        await save(changed)
    assert attempts == [True]
    with factory() as session:
        notice = session.scalar(select(Notice))
        assert notice.updated_at.hour == 6 and reviewed_rules()[0] in notice.rules


def test_cache_schema_upgrade_preserves_existing_rows_and_is_idempotent(store):
    engine, factory = store
    with factory() as session:
        upsert_notice(session, raw_row())
        session.add(DocumentExtractionState(source="lh", external_id="future-source-identifier", audited_on=TODAY))
        session.commit()
    with engine.begin() as connection:
        for column in ("last_feed_hash", "last_feed_version", "last_feed_review_hash"):
            connection.execute(text(f"ALTER TABLE notices DROP COLUMN {column}"))
        connection.execute(text("ALTER TABLE document_extraction_state DROP COLUMN document_checkpoint"))
    init_db(engine)
    init_db(engine)
    with factory() as session:
        notice = session.scalar(select(Notice))
        assert notice.external_id == "future-source-identifier" and notice.last_feed_hash is None and notice.last_feed_version is None and notice.last_feed_review_hash is None
        state = session.get(DocumentExtractionState, ("lh", notice.external_id))
        assert state.audited_on == TODAY and state.document_checkpoint is None


def test_raw_hash_keeps_explicit_overwrite_semantics_and_validates_inputs():
    row = raw_row()
    assert feed_payload_hash(row) == feed_payload_hash(copy.deepcopy(row))
    assert feed_payload_hash({**row, "replace_rules": True}) != feed_payload_hash(row)
    omitted = {key: value for key, value in row.items() if key != "category"}
    assert feed_payload_hash(omitted) != feed_payload_hash({**omitted, "category": "other"})
    with pytest.raises(ValueError):
        feed_payload_hash({**row, "prices": [{"unit_type": "084A", "amount_krw": "invalid-price"}]})


def test_review_checksum_preserves_ordered_source_qualification_stages():
    row = raw_row()
    row["rules"].append({"kind": "selection_stages", "effect": "metadata", "source": "lh",
                         "stages": ["region", "score", "lottery"]})
    reversed_stages = copy.deepcopy(row)
    reversed_stages["rules"][-1]["stages"] = ["score", "region", "lottery"]
    assert feed_review_hash(row) != feed_review_hash(reversed_stages)
