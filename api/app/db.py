"""Database configuration shared by API and collection workers."""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///./cheongyak.db")
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def make_engine(url: str | URL | None = None, *, collector: bool = False) -> Engine:
    url = url or database_url()
    kwargs: dict = {"pool_pre_ping": True, "hide_parameters": True}
    backend = make_url(url).get_backend_name()
    if backend == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False}
    elif backend == "postgresql" and collector:
        kwargs["connect_args"] = {"connect_timeout": 10}
    selected = create_engine(url, **kwargs)
    if backend == "postgresql" and collector:
        @event.listens_for(selected, "begin")
        def bounded_collector_transaction(connection):
            # SET LOCAL applies only inside this collector transaction, never
            # to a database role, the web engine or schema/migration startup.
            connection.exec_driver_sql(
                "SELECT set_config('lock_timeout', '5000', true), "
                "set_config('statement_timeout', '30000', true)"
            )
    return selected


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def collector_session_limits(factory=SessionLocal):
    """Bind CLI collection and its finalizers to a separate bounded engine."""
    previous = factory.kw["bind"]
    if previous.dialect.name != "postgresql":
        # Recreating SQLite in-memory/StaticPool engines would discard their
        # database and custom pool configuration; these limits are PG-only.
        yield previous
        return
    selected = make_engine(previous.url, collector=True)
    # Existing imports share this factory, including the heartbeat and saved
    # key lookup. Rebinding the module variable would miss those consumers.
    factory.configure(bind=selected)
    try:
        yield selected
    finally:
        factory.configure(bind=previous)
        selected.dispose()


def protect_app_tables(connection) -> None:
    """Keep backend tables private on hosts that also expose a Data API."""
    if connection.dialect.name != 'postgresql':
        return
    quote = connection.dialect.identifier_preparer.quote
    for table in Base.metadata.sorted_tables:
        name = quote(table.name)
        if table.schema:
            name = quote(table.schema) + '.' + name
        # The backend table owner retains access. Browser/Data API roles have
        # no policies and cannot read keys, originals or application state.
        protected = connection.execute(text(
            "SELECT relrowsecurity FROM pg_catalog.pg_class WHERE oid = to_regclass(:relation)"
        ), {"relation": name}).scalar_one()
        # Even a redundant ALTER takes AccessExclusiveLock. A rolling web
        # restart must not acquire those locks while collection uses the tables.
        if not protected:
            connection.execute(text(f'ALTER TABLE {name} ENABLE ROW LEVEL SECURITY'))


def init_db(target_engine: Engine | None = None) -> None:
    # Import models here so API startup and worker startup register the same tables.
    from app import models  # noqa: F401

    selected = target_engine or engine
    # Additive upgrade for existing installations. No notice or result rows
    # are replaced. Serialize table creation as well as upgrades because
    # Compose can start the API and worker together against an older database.
    with selected.begin() as connection:
        if selected.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(hashtext('cheongyak_schema'))"))
        Base.metadata.create_all(connection)
        protect_app_tables(connection)
        if selected.dialect.name == "postgresql":
            upgrades = {
                "competition_state": [("proof_invalidated", "BOOLEAN NOT NULL DEFAULT FALSE")],
                "document_extraction_state": [("audited_on", "DATE"), ("document_checkpoint", "JSON")],
                "notices": [("last_feed_hash", "VARCHAR(64)"), ("last_feed_version", "INTEGER"),
                            ("last_feed_review_hash", "VARCHAR(64)")],
            }
            schema = inspect(connection)
            for table_name, columns in upgrades.items():
                present = {column["name"] for column in schema.get_columns(table_name)}
                for column_name, sql_type in columns:
                    # IF NOT EXISTS also locks an already upgraded table. Check
                    # the catalog under the schema advisory lock before DDL.
                    if column_name not in present:
                        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_name} {sql_type}"))
        elif "proof_invalidated" not in {c["name"] for c in inspect(connection).get_columns("competition_state")}:
            connection.execute(text("ALTER TABLE competition_state ADD COLUMN proof_invalidated BOOLEAN NOT NULL DEFAULT FALSE"))
        if selected.dialect.name == 'sqlite' and 'audited_on' not in {
                column['name'] for column in inspect(connection).get_columns('document_extraction_state')}:
            connection.execute(text('ALTER TABLE document_extraction_state ADD COLUMN audited_on DATE'))
        if selected.dialect.name == 'sqlite':
            notice_columns = {column['name'] for column in inspect(connection).get_columns('notices')}
            for name, sql_type in (('last_feed_hash', 'VARCHAR(64)'), ('last_feed_version', 'INTEGER'), ('last_feed_review_hash', 'VARCHAR(64)')):
                if name not in notice_columns:
                    connection.execute(text(f'ALTER TABLE notices ADD COLUMN {name} {sql_type}'))
            if 'document_checkpoint' not in {column['name'] for column in inspect(connection).get_columns('document_extraction_state')}:
                connection.execute(text('ALTER TABLE document_extraction_state ADD COLUMN document_checkpoint JSON'))
        # Legacy pending states created by a notice correction must not become
        # valid historical evidence merely because a later retry failed.
        connection.execute(text("UPDATE competition_state SET proof_invalidated = TRUE WHERE message = :message AND proof_invalidated = FALSE"), {"message": "공고 변경 후 경쟁률 재확인 대기"})


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
