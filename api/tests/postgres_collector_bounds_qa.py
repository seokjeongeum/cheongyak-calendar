"""Check collector limits using temporary data and a unique advisory lock.

Run with the API environment and DATABASE_URL configured. No application table,
database role or persistent schema is changed. Connection strings stay private.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import database_url, make_engine


def state(connection) -> tuple[str, str]:
    return tuple(connection.execute(text(
        "SELECT current_setting('lock_timeout'), current_setting('statement_timeout')"
    )).one())


def main() -> None:
    ordinary = make_engine(database_url())
    limited = make_engine(database_url(), collector=True)
    checks = []
    try:
        assert ordinary.dialect.name == 'postgresql', 'PostgreSQL is required'
        with ordinary.connect() as control, limited.connect() as connection:
            before = state(control)
            control.rollback()
            assert state(connection) == ('5s', '30s')
            connection.rollback()
            checks.append('actual collector transactions have 5s lock and 30s statement limits')

            # This table is private to one DB connection and vanishes on close.
            with connection.begin():
                connection.execute(text('CREATE TEMP TABLE collector_bound_qa (value INTEGER)'))
                connection.execute(text('INSERT INTO collector_bound_qa VALUES (1)'))
            try:
                with connection.begin():
                    connection.execute(text("SELECT set_config('statement_timeout', '100', true)"))
                    connection.execute(text('INSERT INTO collector_bound_qa VALUES (2)'))
                    connection.execute(text('SELECT pg_sleep(0.3)'))
            except DBAPIError as error:
                assert getattr(error.orig, 'sqlstate', None) == '57014'
            else:
                raise AssertionError('Overdue statement was not cancelled')
            assert connection.execute(text('SELECT value FROM collector_bound_qa')).scalars().all() == [1]
            connection.rollback()
            checks.append('a query timeout rolls back unfinished rows and preserves committed rows')

            key = uuid4().int & ((1 << 63) - 1)
            with control.begin():
                control.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})
                try:
                    with connection.begin():
                        connection.execute(text("SELECT set_config('lock_timeout', '100', true)"))
                        connection.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})
                except DBAPIError as error:
                    assert getattr(error.orig, 'sqlstate', None) == '55P03'
                else:
                    raise AssertionError('Overdue lock wait was not cancelled')
            assert connection.execute(text('SELECT value FROM collector_bound_qa')).scalars().all() == [1]
            assert state(connection) == ('5s', '30s')
            connection.rollback()
            checks.append('a lock timeout cancels a unique test lock and the next transaction can be reused')

            assert state(control) == before
            control.rollback()
            checks.append('ordinary database sessions retain their original timeout settings')
        print(json.dumps({'checks_passed': len(checks), 'checks': checks}))
    finally:
        limited.dispose()
        ordinary.dispose()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # DB exception text can contain connection/request details.
        print(json.dumps({'result': 'failed', 'error_category': type(error).__name__}))
        raise SystemExit(1)
