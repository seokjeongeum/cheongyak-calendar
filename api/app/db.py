"""Database configuration shared by API and collection workers."""

from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
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


def make_engine(url: str | None = None) -> Engine:
    url = url or database_url()
    kwargs: dict = {"pool_pre_ping": True, "hide_parameters": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


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
            connection.execute(text("ALTER TABLE competition_state ADD COLUMN IF NOT EXISTS proof_invalidated BOOLEAN NOT NULL DEFAULT FALSE"))
            connection.execute(text("ALTER TABLE document_extraction_state ADD COLUMN IF NOT EXISTS audited_on DATE"))
        elif "proof_invalidated" not in {c["name"] for c in inspect(connection).get_columns("competition_state")}:
            connection.execute(text("ALTER TABLE competition_state ADD COLUMN proof_invalidated BOOLEAN NOT NULL DEFAULT FALSE"))
        if selected.dialect.name == 'sqlite' and 'audited_on' not in {
                column['name'] for column in inspect(connection).get_columns('document_extraction_state')}:
            connection.execute(text('ALTER TABLE document_extraction_state ADD COLUMN audited_on DATE'))
        # Legacy pending states created by a notice correction must not become
        # valid historical evidence merely because a later retry failed.
        connection.execute(text("UPDATE competition_state SET proof_invalidated = TRUE WHERE message = :message"), {"message": "공고 변경 후 경쟁률 재확인 대기"})


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
