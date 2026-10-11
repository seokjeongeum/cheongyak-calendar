"""Opt-in real PostgreSQL checks, confined to a disposable schema."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, inspect, text

from app.db import init_db


@pytest.fixture
def postgres():
    url = os.getenv("PG_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set PG_TEST_DATABASE_URL for isolated PostgreSQL checks")
    schema = "startup_qa_" + uuid4().hex
    admin = create_engine(url, hide_parameters=True)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, hide_parameters=True,
                           connect_args={"options": f"-csearch_path={schema} -clock_timeout=3000"})
    try:
        init_db(engine)
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO notices (id,source,external_id,title,category,rules,rules_complete,"
                "first_seen_at,last_seen_at,version,content_hash,price_cap_status) VALUES "
                "('synthetic','qa','qa','original','apt','[]',FALSE,now(),now(),1,'original','unknown')"))
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_ready_startup_finishes_while_collector_holds_notice_lock(postgres):
    statements = []
    def record(_connection, _cursor, statement, *_args):
        statements.append(statement)
    event.listen(postgres, "before_cursor_execute", record)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with postgres.connect() as collector:
                transaction = collector.begin()
                try:
                    collector.execute(text("UPDATE notices SET title='uncommitted' WHERE id='synthetic'"))
                    startup = pool.submit(init_db, postgres)
                    # A redundant ALTER TABLE would wait for this collector,
                    # although the catalog already contains the desired schema.
                    startup.result(timeout=5)
                    collector.execute(text("SELECT source FROM document_extraction_state LIMIT 1"))
                    assert not any(statement.lstrip().upper().startswith("ALTER TABLE") for statement in statements)
                finally:
                    transaction.rollback()
        with postgres.connect() as connection:
            assert connection.execute(text("SELECT title FROM notices WHERE id='synthetic'")).scalar_one() == "original"
    finally:
        event.remove(postgres, "before_cursor_execute", record)


def test_concurrent_old_schema_upgrades_once_and_retains_rows(postgres):
    with postgres.begin() as connection:
        connection.execute(text("ALTER TABLE notices DROP COLUMN last_feed_review_hash"))
        connection.execute(text("ALTER TABLE notices DISABLE ROW LEVEL SECURITY"))
    statements = []
    def record(_connection, _cursor, statement, *_args):
        statements.append(statement)
    event.listen(postgres, "before_cursor_execute", record)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(init_db, postgres) for _ in range(2)]
            for future in futures:
                future.result(timeout=10)
        alters = [statement for statement in statements if statement.lstrip().upper().startswith("ALTER TABLE")]
        assert len(alters) == 2
        with postgres.connect() as connection:
            assert "last_feed_review_hash" in {column["name"] for column in inspect(connection).get_columns("notices")}
            assert connection.execute(text("SELECT relrowsecurity FROM pg_class WHERE oid=to_regclass('notices')")).scalar_one()
            assert connection.execute(text("SELECT title FROM notices WHERE id='synthetic'")).scalar_one() == "original"
    finally:
        event.remove(postgres, "before_cursor_execute", record)


def test_legacy_invalidation_writes_only_once(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'synthetic.db'}")
    init_db(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE invalidation_updates (notice_id TEXT)"))
        connection.execute(text("CREATE TRIGGER invalidation_log AFTER UPDATE ON competition_state BEGIN "
                                "INSERT INTO invalidation_updates VALUES (new.notice_id); END"))
        connection.execute(text("INSERT INTO competition_state (notice_id,status,complete,proof_invalidated,unit_types,message) "
            "VALUES ('synthetic','pending',0,0,'[]',:message)"), {"message": "공고 변경 후 경쟁률 재확인 대기"})
    init_db(engine)
    init_db(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM invalidation_updates")).scalar_one() == 1
        assert connection.execute(text("SELECT proof_invalidated FROM competition_state")).scalar_one() == 1
    engine.dispose()
