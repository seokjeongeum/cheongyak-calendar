"""CLI DB limits and cooperative yields preserve durable collection progress."""
import asyncio
import time
import threading
from datetime import date, datetime, timezone

import httpx
import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import sessionmaker

from app import collection, db, integration_settings
from app.ingest import competition, worker
from app.models import Notice, SourceStatus
from app.repository import record_source_status, upsert_notice


def test_collector_engine_bounds_connection_and_one_transaction_without_changing_url_options():
    url = 'postgresql+psycopg://synthetic:private@localhost:5432/synthetic?sslmode=require&application_name=kept'
    ordinary = db.make_engine(url)
    limited = db.make_engine(url, collector=True)
    try:
        assert limited.url == ordinary.url
        assert limited.url.query == {'sslmode': 'require', 'application_name': 'kept'}
        # Engine dialect builds final driver options; no connection is opened.
        _args, options = limited.dialect.create_connect_args(limited.url)
        assert options['sslmode'] == 'require' and options['application_name'] == 'kept'
        assert len(list(ordinary.dispatch.begin)) == 0
        statements = []
        class Connection:
            def exec_driver_sql(self, sql):
                statements.append(sql)
        for listener in limited.dispatch.begin:
            listener(Connection())
        assert statements == ["SELECT set_config('lock_timeout', '5000', true), set_config('statement_timeout', '30000', true)"]
        assert 'private' not in statements[0] and 'SET ROLE' not in statements[0]
        assert limited.hide_parameters and ordinary.hide_parameters
    finally:
        limited.dispose()
        ordinary.dispose()


def test_collector_factory_is_shared_in_process_and_restored_without_changing_schema_engine(tmp_path, monkeypatch):
    original = db.make_engine(f'sqlite:///{tmp_path / "factory.db"}')
    db.init_db(original)
    factory = sessionmaker(bind=original, expire_on_commit=False)
    for module in (db, worker, competition, collection, integration_settings):
        monkeypatch.setattr(module, 'SessionLocal', factory)
    schema_engine = db.engine
    try:
        with db.collector_session_limits(factory) as limited:
            assert limited is original  # SQLite keeps its database/pool intact.
            assert db.engine is schema_engine  # init_db/startup/migration retain their engine.
            assert all(module.SessionLocal.kw['bind'] is limited for module in
                       (worker, competition, collection, integration_settings))
            with factory() as session:
                record_source_status(session, 'synthetic', 'partial', 'durable', record_count=1)
                session.commit()
        assert factory.kw['bind'] is original and db.engine is schema_engine
        with factory() as session:
            assert session.get(SourceStatus, 'synthetic').record_count == 1
    finally:
        original.dispose()


def test_postgres_collector_factory_changes_only_cli_sessions_and_restores_binding(monkeypatch):
    original = db.make_engine('postgresql+psycopg://synthetic:private@localhost/synthetic?sslmode=require')
    factory = sessionmaker(bind=original)
    for module in (worker, competition, collection, integration_settings):
        monkeypatch.setattr(module, 'SessionLocal', factory)
    schema_engine = db.engine
    try:
        with db.collector_session_limits(factory) as limited:
            assert limited is not original and limited.url == original.url
            assert db.engine is schema_engine
            for module in (worker, competition, collection, integration_settings):
                with module.SessionLocal() as session:
                    assert session.get_bind() is limited
            assert len(list(original.dispatch.begin)) == 0
            assert len(list(limited.dispatch.begin)) == 1
        assert factory.kw['bind'] is original and db.engine is schema_engine
    finally:
        original.dispose()


def test_connection_timeout_applies_only_to_collector(monkeypatch):
    calls = []
    create = db.create_engine
    def capture(*args, **kwargs):
        calls.append(kwargs.copy())
        return create(*args, **kwargs)
    monkeypatch.setattr(db, 'create_engine', capture)
    regular = db.make_engine('postgresql+psycopg://synthetic:private@localhost/synthetic')
    limited = db.make_engine('postgresql+psycopg://synthetic:private@localhost/synthetic', collector=True)
    try:
        assert calls[0].get('connect_args', {}) == {}
        assert calls[1]['connect_args'] == {'connect_timeout': 10}
    finally:
        regular.dispose()
        limited.dispose()


def test_raw_progress_is_not_labeled_as_document_work_when_previous_batch_is_larger(tmp_path):
    engine = db.make_engine(f'sqlite:///{tmp_path / "phase.db"}')
    db.init_db(engine)
    factory = sessionmaker(bind=engine)
    try:
        with factory() as session:
            state = record_source_status(session, 'myhome', 'running', 'initial', record_count=86)
            before = state.last_attempt_at
            worker._save_progress(session, state, 'myhome', 1, 100, progress_floor=86, phase='raw')
            assert state.message == '공식 공고 저장 중 · 1/100건 저장'
            assert state.record_count == 86 and state.last_attempt_at == before
            worker._save_progress(session, state, 'myhome', 1, 100, progress_floor=86, phase='document')
            assert state.message == '공식 공고 86건 저장 · 문서 확인 1/100건'
            worker._save_progress(session, state, 'myhome', 1, 100, phase='document')
            assert state.message == '공식 공고 1건 저장 · 문서 확인 1/100건'
    finally:
        engine.dispose()


def test_late_heartbeat_uses_snapshot_after_shared_collector_factory_is_restored(monkeypatch):
    original = db.make_engine('postgresql+psycopg://synthetic:private@localhost/synthetic')
    factory = sessionmaker(bind=original, expire_on_commit=False)
    monkeypatch.setattr(collection, 'SessionLocal', factory)
    monkeypatch.setattr(collection, 'HEARTBEAT_SECONDS', 0.001)
    entered = threading.Event()
    release = threading.Event()
    observed = []
    def paused_renew(job_id, *, session_factory=None):
        entered.set()
        assert release.wait(2)
        with session_factory() as session:
            observed.append(session.get_bind())
        return True
    monkeypatch.setattr(collection, 'renew_collection', paused_renew)
    heartbeat = None
    try:
        with db.collector_session_limits(factory) as limited:
            heartbeat = collection.CollectionHeartbeat('synthetic-job')
            real_join = heartbeat.thread.join
            # Exercise the existing bounded join race without waiting two seconds.
            monkeypatch.setattr(heartbeat.thread, 'join', lambda timeout=None: None)
            with heartbeat:
                assert entered.wait(2)
        assert factory.kw['bind'] is original
        release.set()
        real_join(timeout=2)
        assert not heartbeat.thread.is_alive() and observed == [limited]
        assert len(list(observed[0].dispatch.begin)) == 1
    finally:
        release.set()
        if heartbeat is not None:
            heartbeat.stopped.set()
            real_join(timeout=2)
        original.dispose()


@pytest.mark.asyncio
async def test_positive_yield_observes_overdue_timeout_after_sync_work():
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.005):
            time.sleep(0.015)
            await worker.yield_to_deadlines()
    assert time.monotonic() - started < 0.5


@pytest.mark.asyncio
async def test_raw_saved_row_is_durable_when_overdue_timeout_fires_at_yield(tmp_path, monkeypatch):
    engine = db.make_engine(f'sqlite:///{tmp_path / "row.db"}')
    db.init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, 'SessionLocal', factory)
    row = {'source': 'synthetic', 'external_id': 'one', 'title': 'saved original', 'category': 'apt',
           'announcement_date': '2026-10-11',
           'prices': [{'unit_type': '84', 'price_kind': 'sale', 'amount_krw': 123000000, 'verification': 'official'}],
           'events': [{'kind': 'general', 'label': '접수', 'start_date': '2026-10-12'}]}
    async def no_network(request):
        raise AssertionError('No source HTTP is needed')
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0.005):
                    await worker._save_rows('synthetic', [row], client, date(2026, 10, 11),
                        audit_documents=False, on_raw_saved=lambda _: time.sleep(0.015))
        with factory() as session:
            notice = session.scalar(select(Notice).where(Notice.external_id == 'one'))
            assert notice.title == 'saved original'
            assert notice.prices[0].amount_krw == 123000000
            assert notice.version == 1 and len(notice.revisions) == 1
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_unpublished_competition_branch_yields_and_retains_committed_pending_result(tmp_path, monkeypatch):
    engine = db.make_engine(f'sqlite:///{tmp_path / "pending.db"}')
    db.init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(competition, 'SessionLocal', factory)
    monkeypatch.setattr(competition, 'init_db', lambda: None)
    monkeypatch.setattr(integration_settings, 'setting_value', lambda name: '')
    with factory() as session:
        notice = upsert_notice(session, {'source': 'cheongyak_home',
            'external_id': 'getAPTLttotPblancDetail:123:123', 'title': 'future', 'category': 'apt',
            'announcement_date': '2026-10-11',
            'events': [{'kind': 'general', 'label': '접수', 'start_date': '2026-10-15'}]})
        notice_id = notice.id
        session.commit()
    original = competition.record_competition_result
    def slow_record(*args, **kwargs):
        result = original(*args, **kwargs)
        time.sleep(0.015)
        return result
    monkeypatch.setattr(competition, 'record_competition_result', slow_record)
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail('Unpublished notices do not request HTTP'))) as client:
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0.005):
                    await competition.run_once(today=date(2026, 10, 11), client=client)
        with factory() as session:
            notice = session.get(Notice, notice_id)
            assert notice.competition_state.status == 'pending'
            assert notice.version == 1
    finally:
        engine.dispose()
