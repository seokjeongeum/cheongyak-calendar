"""A one-time copy preserves real table relationships and sensitive originals."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, event, func, inspect, select, text

from app import migrate_database as migration
from app.db import Base
from app.models import (CollectionRun, CompetitionRevision, CompetitionState, DocumentExtractionState,
                        IntegrationSetting, Notice, NoticeEvent, NoticeRevision, SourceStatus,
                        UnitCompetition, UnitPrice)


SECRET = "synthetic-secret-never-logged"
NOW = datetime(2026, 10, 10, 3, 0, tzinfo=timezone.utc)


def local_engine():
    engine = create_engine("sqlite:///:memory:", hide_parameters=True)
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
    return engine


def seeded_source():
    engine = local_engine()
    Base.metadata.create_all(engine)
    original = {"raw_response": [{"label": "원본 한국어", "amount": 1032000000, "document": "공식 자료 " * 4000}], "nested": [None, True, {"key": SECRET}]}
    with engine.begin() as connection:
        connection.execute(Notice.__table__.insert(), [
            {"id": "first", "source": "official", "external_id": "initial", "title": "최초 공고", "category": "apt", "content_hash": "original-hash", "rules": [{"kind": "saved_original", "value": original}], "rules_complete": True, "version": 8},
            {"id": "later", "source": "official", "external_id": "corrected", "title": "정정 공고", "category": "apt", "content_hash": "corrected-hash", "rules": [], "rules_complete": False, "version": 2},
        ])
        # An original row can refer forward to a later canonical duplicate;
        # the later correction also refers back to the original. One-row
        # batches cannot load either row with unstaged self references.
        connection.execute(Notice.__table__.update().where(Notice.id == "first").values(duplicate_of_id="later"))
        connection.execute(Notice.__table__.update().where(Notice.id == "later").values(correction_of_id="first", correction_of_external_id="initial"))
        connection.execute(NoticeEvent.__table__.insert(), {"id": 41, "notice_id": "first", "kind": "general", "label": "신청 접수", "start_date": date(2026, 10, 12), "end_date": date(2026, 10, 13)})
        connection.execute(UnitPrice.__table__.insert(), {"id": 51, "notice_id": "first", "unit_type": "084.9800B", "price_kind": "sale", "amount_krw": 1032000000, "verification": "official", "evidence_text": "보존할 공급금액", "document_hash": "original-document"})
        connection.execute(NoticeRevision.__table__.insert(), {"id": 71, "notice_id": "first", "version": 7, "content_hash": "historic-hash", "payload": original, "seen_at": NOW})
        connection.execute(UnitCompetition.__table__.insert(), {"id": 91, "notice_id": "first", "unit_type": "084.9800B", "application_count": 170, "supply_count": 10, "competition_rate": "17.00", "evidence_url": "https://www.applyhome.co.kr/official", "observed_at": NOW})
        connection.execute(CompetitionState.__table__.insert(), {"notice_id": "first", "status": "partial", "complete": False, "proof_invalidated": True, "unit_types": ["084.9800B"], "last_success_at": NOW})
        connection.execute(CompetitionRevision.__table__.insert(), {"id": 121, "notice_id": "first", "content_hash": "result-hash", "payload": {"rows": [{"competition_rate": "17.00"}], "source": original}, "seen_at": NOW})
        connection.execute(IntegrationSetting.__table__.insert(), [{"name": "public_data_key", "value": SECRET}, {"name": "integrations_admin_hash", "value": "sha256-existing-admin-hash"}])
        connection.execute(SourceStatus.__table__.insert(), {"source": "official", "status": "partial", "message": "원문 확인 대기", "last_success_at": NOW, "record_count": 2})
        connection.execute(CollectionRun.__table__.insert(), {"name": "official", "job_id": "existing-job", "status": "interrupted", "trigger": "scheduled", "started_at": NOW, "message": "이전 수집 체크포인트"})
        connection.execute(DocumentExtractionState.__table__.insert(), {"source": "official", "external_id": "initial", "audited_on": date(2026, 10, 9), "deferred_until": NOW})
    return engine, original


def snapshot(engine):
    with engine.connect() as connection:
        return {table.name: [dict(row) for row in connection.execute(select(table)).mappings()] for table in Base.metadata.sorted_tables}


def test_copy_preserves_every_table_original_json_credentials_and_self_references(capsys):
    source, original = seeded_source()
    target = local_engine()
    before = snapshot(source)
    result = migration.copy_application_database(source, target, batch_size=1)
    assert result.status == "complete"
    assert result.copied_rows == result.verified_rows
    assert result.copied_rows["notices"] == 2
    assert all(result.copied_rows.values())
    assert snapshot(target) == before
    assert snapshot(source) == before
    with target.begin() as connection:
        assert connection.scalar(select(NoticeRevision.payload)) == original
        assert connection.scalar(select(IntegrationSetting.value).where(IntegrationSetting.name == "public_data_key")) == SECRET
        inserted = connection.execute(NoticeEvent.__table__.insert(), {"notice_id": "first", "kind": "general", "label": "다음 일정", "start_date": date(2026, 10, 20)})
        assert inserted.inserted_primary_key[0] > 41
    assert SECRET not in capsys.readouterr().out


def test_nonempty_target_is_rejected_without_changing_either_database():
    source, _ = seeded_source()
    target = local_engine()
    Base.metadata.create_all(target)
    with target.begin() as connection:
        connection.execute(IntegrationSetting.__table__.insert(), {"name": "existing_key", "value": "retain-target-setting"})
    before_source, before_target = snapshot(source), snapshot(target)
    with pytest.raises(migration.MigrationError, match="target_application_not_empty"):
        migration.copy_application_database(source, target)
    assert snapshot(source) == before_source and snapshot(target) == before_target


def test_source_connection_failure_does_not_connect_to_or_prepare_the_target(monkeypatch):
    source, _ = seeded_source()
    target = local_engine()
    def blocked_source():
        raise RuntimeError("quota blocked " + SECRET)
    def forbid_target():
        pytest.fail("A blocked source must not prepare the target")
    monkeypatch.setattr(source, "connect", blocked_source)
    monkeypatch.setattr(target, "begin", forbid_target)
    with pytest.raises(migration.MigrationError, match="source_unavailable") as error:
        migration.copy_application_database(source, target)
    assert SECRET not in str(error.value)


def test_mid_copy_failure_rolls_back_all_rows_and_schema_changes(monkeypatch):
    source, _ = seeded_source()
    target = local_engine()
    before_source = snapshot(source)
    real_copy = migration._copy_snapshot
    def fail_after_some_rows(read, write, tables, batch_size):
        copied = real_copy(read, write, tables, batch_size)
        assert copied.copied_rows["notices"] == 2
        raise migration.MigrationError("source_read_failed")
    monkeypatch.setattr(migration, "_copy_snapshot", fail_after_some_rows)
    with pytest.raises(migration.MigrationError, match="source_read_failed"):
        migration.copy_application_database(source, target)
    with target.connect() as connection:
        assert inspect(connection).get_table_names() == []
    assert snapshot(source) == before_source


def test_read_snapshot_rejects_an_attempted_source_write(monkeypatch):
    source, _ = seeded_source()
    target = local_engine()
    before_source = snapshot(source)
    def unexpected_source_write(read, _write, _tables, _batch_size):
        read.execute(IntegrationSetting.__table__.update().values(value="wrong"))
    monkeypatch.setattr(migration, "_copy_snapshot", unexpected_source_write)
    with pytest.raises(migration.MigrationError, match="target_transaction_failed"):
        migration.copy_application_database(source, target)
    assert snapshot(source) == before_source
    with target.connect() as connection:
        assert inspect(connection).get_table_names() == []


def test_older_source_without_new_nullable_checkpoint_column_is_not_upgraded():
    source, _ = seeded_source()
    with source.begin() as connection:
        connection.execute(text("ALTER TABLE document_extraction_state DROP COLUMN audited_on"))
    target = local_engine()
    result = migration.copy_application_database(source, target)
    assert result.status == "complete"
    with source.connect() as connection:
        assert "audited_on" not in {column["name"] for column in inspect(connection).get_columns("document_extraction_state")}
    with target.connect() as connection:
        assert connection.scalar(select(DocumentExtractionState.deferred_until)) == NOW.replace(tzinfo=None)
        assert connection.scalar(select(DocumentExtractionState.audited_on)) is None


def test_unknown_original_columns_or_tables_cannot_be_silently_discarded():
    for statement in ("ALTER TABLE notices ADD COLUMN preserved_unknown TEXT", "CREATE TABLE future_application_records (id INTEGER PRIMARY KEY)"):
        source, _ = seeded_source()
        with source.begin() as connection:
            connection.execute(text(statement))
        target = local_engine()
        with pytest.raises(migration.MigrationError, match="source_schema_unsupported"):
            migration.copy_application_database(source, target)
        with target.connect() as connection:
            assert inspect(connection).get_table_names() == []


def test_same_database_is_rejected_before_any_read_or_write():
    source, _ = seeded_source()
    with pytest.raises(migration.MigrationError, match="source_and_target_match"):
        migration.copy_application_database(source, source)


def test_command_reports_only_fixed_codes_for_private_connection_failures(monkeypatch, capsys):
    def invalid_connection(_value):
        raise RuntimeError("postgresql://private:" + SECRET + "@private.invalid/database")
    monkeypatch.setattr(migration, "_configured_engine", invalid_connection)
    assert migration.main() == 1
    assert capsys.readouterr().out == '{"status": "failed", "code": "migration_failed"}\n'


def test_placeholder_password_is_rejected_without_connecting():
    with pytest.raises(migration.MigrationError, match="database_password_placeholder"):
        migration._configured_engine("postgresql://postgres.test:[YOUR-PASSWORD]@example.invalid:5432/postgres")


def test_target_connection_preflight_stops_before_source_reads(monkeypatch, capsys):
    source, _ = seeded_source()
    target = local_engine()
    engines = iter((source, target))
    monkeypatch.setattr(migration, "_configured_engine", lambda _: next(engines))
    def unavailable():
        raise RuntimeError("private address " + SECRET)
    monkeypatch.setattr(target, "connect", unavailable)
    monkeypatch.setattr(source, "connect", lambda: pytest.fail("Source must not be read before target connectivity is established"))
    assert migration.main() == 1
    assert capsys.readouterr().out == '{"status": "failed", "code": "target_unavailable"}\n'


@pytest.mark.parametrize("message,code", [
    ("Network is unreachable", "target_ipv6_unreachable"),
    ("could not translate host name", "target_host_unresolved"),
    ("Tenant or user not found", "target_pooler_user_invalid"),
    ("password authentication failed", "target_authentication_failed"),
    ("connection timeout expired", "target_connection_timed_out"),
])
def test_connection_failure_reports_only_public_protocol_cause(monkeypatch, message, code):
    target = local_engine()
    def failed():
        raise RuntimeError(message + " private address/password " + SECRET)
    monkeypatch.setattr(target, "connect", failed)
    with pytest.raises(migration.MigrationError) as error:
        migration._check_target_connection(target)
    assert str(error.value) == code and SECRET not in str(error.value)
