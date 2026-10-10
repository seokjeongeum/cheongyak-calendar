"""Copy application data once from a read-only snapshot into an empty database.

Credentials are supplied only to this offline command. The source is never
upgraded or written to; the destination is never cleared or overwritten.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import MetaData, Table, bindparam, create_engine, func, inspect, select, text, update
from sqlalchemy.engine import Connection, Engine, make_url

from app import models  # noqa: F401
from app.db import Base, protect_app_tables


class MigrationError(RuntimeError):
    """A fixed public error code, without connection or record contents."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class CopyReport:
    status: str
    copied_rows: dict[str, int]
    verified_rows: dict[str, int]


def _same_database(source: Engine, target: Engine):
    if source is target:
        return True
    if source.dialect.name != target.dialect.name:
        return False
    if source.dialect.name == "sqlite":
        # Independent in-memory engines are different databases.
        if not source.url.database or source.url.database == ":memory:":
            return False
        return Path(source.url.database).resolve() == Path(target.url.database or "").resolve()
    return ((source.url.host or "").lower(), source.url.port or 5432, source.url.database) == (
        (target.url.host or "").lower(), target.url.port or 5432, target.url.database)


def _source_tables(connection: Connection):
    inspector = inspect(connection)
    names = set(inspector.get_table_names())
    managed = set(Base.metadata.tables)
    if "notices" not in names:
        raise MigrationError("source_application_missing")
    # Do not quietly discard data from an unrecognized application table.
    if names - managed:
        raise MigrationError("source_schema_unsupported")
    metadata = MetaData()
    result = {}
    for target in Base.metadata.sorted_tables:
        if target.name not in names:
            continue
        source = Table(target.name, metadata, autoload_with=connection, resolve_fks=False)
        if set(source.columns.keys()) - set(target.columns.keys()):
            raise MigrationError("source_schema_unsupported")
        for column in target.columns:
            if column.name not in source.columns and not (column.nullable or column.default or column.server_default):
                raise MigrationError("source_schema_unsupported")
        result[target.name] = source
    return result


def _prepare_target(connection: Connection):
    if connection.dialect.name == "postgresql":
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtext('cheongyak_schema'))"))
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        # sqlite3 otherwise leaves DDL outside its lazy transaction start.
        connection.exec_driver_sql("BEGIN")
    existing = set(inspect(connection).get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name in existing and connection.scalar(select(func.count()).select_from(table)):
            raise MigrationError("target_application_not_empty")
    Base.metadata.create_all(connection)
    protect_app_tables(connection)
    if connection.dialect.name == "postgresql":
        # No concurrent backend write can race the empty check or row counts.
        tables = ", ".join(connection.dialect.identifier_preparer.format_table(table) for table in Base.metadata.sorted_tables)
        connection.execute(text(f"LOCK TABLE {tables} IN ACCESS EXCLUSIVE MODE"))
        for table in Base.metadata.sorted_tables:
            if connection.scalar(select(func.count()).select_from(table)):
                raise MigrationError("target_application_not_empty")


def _restore_self_references(connection: Connection, table: Table, rows, columns, batch_size):
    if not rows:
        return
    keys = list(table.primary_key.columns)
    statement = update(table).where(*[column == bindparam("migration_key_" + column.name) for column in keys]).values(
        **{column.name: bindparam("migration_reference_" + column.name) for column in columns})
    for offset in range(0, len(rows), batch_size):
        connection.execute(statement, rows[offset:offset + batch_size])


def _reset_sequences(connection: Connection):
    if connection.dialect.name != "postgresql":
        # SQLite's implicit rowid allocator already advances above copied IDs.
        return
    formatter = connection.dialect.identifier_preparer
    for table in Base.metadata.sorted_tables:
        column = table.autoincrement_column
        if column is None:
            continue
        sequence = connection.scalar(select(func.pg_get_serial_sequence(formatter.format_table(table), column.name)))
        if not sequence:
            continue
        quoted = connection.scalar(text("""SELECT quote_ident(n.nspname) || '.' || quote_ident(c.relname)
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.oid = CAST(:sequence_name AS regclass)"""), {"sequence_name": sequence})
        maximum = connection.scalar(select(func.max(column)))
        next_value = max(1, int(maximum) + 1 if maximum is not None else 1)
        # Unlike setval(), RESTART participates in the destination transaction.
        connection.execute(text(f"ALTER SEQUENCE {quoted} RESTART WITH {next_value}"))


def _copy_snapshot(source: Connection, target: Connection, tables, batch_size):
    copied, restore = {}, []
    for table in Base.metadata.sorted_tables:
        selected = tables.get(table.name)
        copied[table.name] = 0
        if selected is None:
            continue
        self_references = [column for column in table.columns
                           if any(key.column.table is table for key in column.foreign_keys)]
        if any(not column.nullable for column in self_references):
            raise MigrationError("source_schema_unsupported")
        restore_rows = []
        try:
            result = source.execution_options(stream_results=True, max_row_buffer=batch_size).execute(select(selected)).mappings()
            try:
                for batch in result.partitions(batch_size):
                    staged = []
                    for original in batch:
                        row = dict(original)
                        if any(row.get(column.name) is not None for column in self_references):
                            restore_rows.append({**{"migration_key_" + column.name: row[column.name] for column in table.primary_key.columns},
                                                 **{"migration_reference_" + column.name: row.get(column.name) for column in self_references}})
                        for column in self_references:
                            row[column.name] = None
                        staged.append(row)
                    try:
                        target.execute(table.insert(), staged)
                    except Exception:
                        raise MigrationError("target_copy_failed") from None
                    copied[table.name] += len(staged)
            finally:
                result.close()
        except MigrationError:
            raise
        except Exception:
            raise MigrationError("source_read_failed") from None
        restore.append((table, restore_rows, self_references))
    for table, rows, columns in restore:
        _restore_self_references(target, table, rows, columns, batch_size)
    verified = {table.name: target.scalar(select(func.count()).select_from(table)) for table in Base.metadata.sorted_tables}
    if verified != copied:
        raise MigrationError("row_count_mismatch")
    _reset_sequences(target)
    return CopyReport("complete", copied, verified)


def copy_application_database(source_engine: Engine, target_engine: Engine, *, batch_size=128):
    """Preserve all supported application rows in one atomic destination commit."""
    if _same_database(source_engine, target_engine):
        raise MigrationError("source_and_target_match")
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or not 1 <= batch_size <= 1000:
        raise MigrationError("invalid_batch_size")
    if source_engine.dialect.name not in {"sqlite", "postgresql"} or target_engine.dialect.name not in {"sqlite", "postgresql"}:
        raise MigrationError("unsupported_database")
    source = None
    original_query_only = None
    try:
        try:
            source = source_engine.connect()
            if source.dialect.name == "postgresql":
                source = source.execution_options(isolation_level="REPEATABLE READ")
        except Exception:
            raise MigrationError("source_unavailable") from None
        with source.begin() as snapshot:
            if source.dialect.name == "postgresql":
                source.execute(text("SET TRANSACTION READ ONLY"))
            else:
                original_query_only = source.exec_driver_sql("PRAGMA query_only").scalar()
                source.exec_driver_sql("PRAGMA query_only=ON")
                source.exec_driver_sql("BEGIN")
            try:
                tables = _source_tables(source)
            except MigrationError:
                raise
            except Exception:
                raise MigrationError("source_unavailable") from None
            try:
                with target_engine.begin() as target:
                    _prepare_target(target)
                    report = _copy_snapshot(source, target, tables, batch_size)
                    # End the read-only snapshot before the destination can
                    # commit. A source connection failure still rolls back
                    # the entire destination; the source needs no commit.
                    snapshot.rollback()
            except MigrationError:
                raise
            except Exception:
                raise MigrationError("target_copy_failed") from None
            return report
    finally:
        if source is not None:
            if original_query_only is not None:
                try:
                    source.exec_driver_sql("PRAGMA query_only=" + ("ON" if original_query_only else "OFF"))
                except Exception:
                    pass
            source.close()


def _configured_engine(value):
    if not value:
        raise MigrationError("database_secret_missing")
    if value.startswith("postgres://"):
        value = "postgresql+psycopg://" + value[len("postgres://"):]
    elif value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://"):]
    try:
        url = make_url(value)
        options = {"hide_parameters": True, "pool_pre_ping": True, "echo": False}
        if url.get_backend_name() == "postgresql":
            options["connect_args"] = {"connect_timeout": 10, "application_name": "cheongyak_database_copy"}
        return create_engine(url, **options)
    except Exception:
        raise MigrationError("database_secret_invalid") from None


def main():
    source, target = None, None
    try:
        source = _configured_engine(os.getenv("SOURCE_DATABASE_URL"))
        target = _configured_engine(os.getenv("TARGET_DATABASE_URL"))
        report = copy_application_database(source, target)
        print(json.dumps(asdict(report), sort_keys=True))
        return 0
    except MigrationError as error:
        print(json.dumps({"status": "failed", "code": error.code}))
        return 1
    except Exception:
        # SQL errors may contain credentials or parameter values. Never print
        # the exception, traceback, URL, setting contents or source records.
        print(json.dumps({"status": "failed", "code": "migration_failed"}))
        return 1
    finally:
        for selected in (source, target):
            if selected is not None:
                selected.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
