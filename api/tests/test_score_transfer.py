"""PostgreSQL score merges retain conditions without transferring their JSON."""
import json
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.db import init_db, make_engine
from app.ingest import winning_scores
from app.models import Notice
from app.repository import upsert_notice


class NoticeIdentity:
    id = "notice-identity"
    source = "cheongyak_home"
    external_id = "new-source-record"
    version = 7

    @property
    def rules(self):
        raise AssertionError("PostgreSQL score merge must not read the complete condition document")


class PgSession:
    def __init__(self, previous=None):
        self.notice = NoticeIdentity()
        self.previous = previous or []
        self.reads, self.writes, self.expired = [], [], []

    def get(self, model, identity, **kwargs):
        return self.notice

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def scalar(self, query, params):
        self.reads.append((str(query), params))
        return self.previous

    def execute(self, query, params):
        self.writes.append((str(query), params))

    def expire(self, notice, fields):
        self.expired.append(fields)


@pytest.mark.parametrize("status", ["success", "error"])
def test_server_merge_transfers_only_scores_and_keeps_other_conditions_in_database(monkeypatch, status):
    original = {"kind": "winning_scores", "rows": [{"unit_type": "084A", "min_score": 40}]}
    session = PgSession([original])
    monkeypatch.setattr(winning_scores, "lock_notice", lambda *args, **kwargs: session.notice)
    winning_scores.record_winning_scores(session, session.notice.id, [{"unit_type": "084B", "min_score": 50}], status,
                                        expected_version=7, criterion_date="2027-04-03")
    assert len(session.writes) == 1 and session.expired == [["rules"]]
    query, params = session.writes[0]
    assert "IS DISTINCT FROM 'winning_scores'" in query and "ORDER BY position" in query
    assert "version = :expected_version" in query and params["expected_version"] == 7
    record = json.loads(params["score_rules"])[0]
    assert record["rows"][0]["criterion_date"] == "2027-04-03"
    assert record["rows"][0]["min_score"] == (40 if status == "error" else 50)
    if status == "error":
        assert len(session.reads) == 1 and "item->>'kind' = 'winning_scores'" in session.reads[0][0]
    else:
        assert not session.reads


def test_stale_score_result_does_not_write_over_newer_source_version(monkeypatch):
    session = PgSession()
    monkeypatch.setattr(winning_scores, "lock_notice", lambda *args, **kwargs: session.notice)
    winning_scores.record_winning_scores(session, session.notice.id, [], "success", expected_version=6, criterion_date=None)
    assert not session.writes and not session.reads


def test_fresh_session_stale_score_check_does_not_fetch_full_document(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'score-transfer.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    original_rules = [{"kind": "document_diagnostics", "effect": "metadata", "evidence_text": "공개 공고 원문 " * 10000}]
    with factory() as session:
        notice = upsert_notice(session, {
            "source": "cheongyak_home", "external_id": "new-official-record",
            "title": "새 공고", "category": "apt", "rules": original_rules,
        })
        session.commit()
        notice_id, current_version = notice.id, notice.version

    statements = []

    def captured(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("select"):
            statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", captured)
    try:
        # No retained identity exists: the initial lookup must be narrow too.
        with factory() as session:
            winning_scores.record_winning_scores(session, notice_id, [], "success",
                                                  expected_version=current_version - 1, criterion_date=None)
            session.commit()
    finally:
        event.remove(engine, "before_cursor_execute", captured)
    assert statements and all(not re.search(r"notices\.rules\b|notice_revisions\.payload\b|unit_competitions\.", statement) for statement in statements)
    with factory() as session:
        unchanged = session.get(Notice, notice_id)
        assert unchanged.version == current_version and unchanged.rules == original_rules
    engine.dispose()
