# PostgreSQL startup lock regression

Render failed to start after `ALTER TABLE notices ENABLE ROW LEVEL SECURITY`
deadlocked with an active collector. PostgreSQL takes an exclusive table lock
even when RLS is already enabled or `ADD COLUMN IF NOT EXISTS` adds nothing.

Startup now checks the PostgreSQL catalog under the existing schema advisory
lock and runs DDL only for missing columns or disabled RLS. The legacy
competition-proof correction updates only rows that still need invalidation.
Fresh installations retain RLS and additive upgrades; existing records are
preserved.

Validated against PostgreSQL 16.15 in disposable QA schemas on 2026-10-11:

- Already-upgraded startup completes while another transaction holds a notice
  write lock, runs no `ALTER TABLE`, and permits the collector's subsequent
  document-state read.
- Concurrent startup restores one missing column and disabled RLS exactly
  once, preserving a synthetic original record.
- A SQLite update trigger confirms legacy invalidation writes once across
  repeated startup calls.

`api/tests/test_postgres_startup.py`: 3 passed. PostgreSQL checks are opt-in via
`PG_TEST_DATABASE_URL`; the tests create and remove only their own random QA
schemas. Earlier targeted startup/schema/API checks: 68 passed.

Read-only production catalog verification confirmed RLS already enabled on
all 11 application tables. No production schema or original records were
modified for these tests.
