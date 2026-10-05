"""Exercise actual PostgreSQL writers in a disposable, isolated schema.

Run inside an API container with this API directory mounted at /qa:
  python /qa/tests/postgres_notice_concurrency_qa.py
Only the newly generated QA schema is created and dropped. Public tables and
production notice/price/result histories are never queried or modified.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.db import Base, database_url
from app.models import Notice, NoticeRevision
from app.repository import upsert_notice


def payload(external_id: str) -> dict:
    return {
        "source": "isolated_concurrency_qa", "external_id": external_id,
        "title": "원래 공식 공고", "category": "apt",
        "events": [{"kind": "general", "label": "원래 접수", "start_date": "2026-10-10"}],
        "prices": [{"unit_type": "59A", "price_kind": "sale_max", "amount_krw": 500000000,
                    "verification": "official"}],
        "rules": [],
    }


def existing_notice_writers(factory) -> None:
    raw = payload("existing-row")
    with factory() as seed:
        notice_id = upsert_notice(seed, raw).id
        seed.commit()
    cached_ready, first_locked, second_start, release_first, second_done = [Event() for _ in range(5)]

    def second_writer():
        with factory() as session:
            cached = session.get(Notice, notice_id)
            assert cached.version == 1 and cached.events[0].label == "원래 접수"
            session.commit()  # Keep the identity map across another writer.
            cached_ready.set()
            assert second_start.wait(10)
            try:
                current = upsert_notice(session, {"source": raw["source"], "external_id": raw["external_id"],
                    "document_hash": "reviewed-document", "rules": [{"kind": "homeless", "value": True,
                    "verification": "official", "document_hash": "reviewed-document"}]})
                session.commit()
                assert current is cached and current.version == 3
                assert current.title == "정정된 최신 공식 공고"
                assert current.events[0].label == "정정된 접수"
                assert current.prices[0].amount_krw == 550000000
            finally:
                second_done.set()

    def first_writer():
        with factory() as session:
            upsert_notice(session, {**raw, "title": "정정된 최신 공식 공고",
                "events": [{"kind": "general", "label": "정정된 접수", "start_date": "2026-10-15"}],
                "prices": [{**raw["prices"][0], "amount_krw": 550000000}]})
            first_locked.set()
            assert release_first.wait(10)
            session.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        second = pool.submit(second_writer)
        assert cached_ready.wait(10)
        first = pool.submit(first_writer)
        assert first_locked.wait(10)
        second_start.set()
        try:
            assert not second_done.wait(0.3), "Second writer must wait for the notice transaction"
        finally:
            release_first.set()
        first.result(timeout=10)
        second.result(timeout=10)
    with factory() as session:
        current = session.get(Notice, notice_id)
        revisions = session.scalars(select(NoticeRevision).where(NoticeRevision.notice_id == notice_id)
                                   .order_by(NoticeRevision.version)).all()
        assert [row.version for row in revisions] == [1, 2, 3]
        assert revisions[0].payload["prices"][0]["amount_krw"] == 500000000
        assert revisions[1].payload["prices"][0]["amount_krw"] == 550000000
        assert current.document_hash == "reviewed-document" and len(current.rules) == 1


def simultaneous_first_insert(factory) -> None:
    raw = payload("new-row")
    first_locked, release_first, second_started, second_done = [Event() for _ in range(4)]

    def first_writer():
        with factory() as session:
            upsert_notice(session, raw)
            first_locked.set()
            assert release_first.wait(10)
            session.commit()

    def second_writer():
        with factory() as session:
            second_started.set()
            try:
                current = upsert_notice(session, {"source": raw["source"], "external_id": raw["external_id"],
                    "rules": [{"kind": "household_head", "value": True, "verification": "official"}]})
                session.commit()
                assert current.version == 2 and current.title == raw["title"]
            finally:
                second_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_writer)
        assert first_locked.wait(10)
        second = pool.submit(second_writer)
        assert second_started.wait(10)
        try:
            assert not second_done.wait(0.3), "Advisory lock must also cover the first insertion"
        finally:
            release_first.set()
        first.result(timeout=10)
        second.result(timeout=10)
    with factory() as session:
        notices = session.scalars(select(Notice).where(Notice.external_id == raw["external_id"])).all()
        assert len(notices) == 1
        assert [revision.version for revision in notices[0].revisions] == [1, 2]


def main() -> None:
    url = database_url()
    admin = create_engine(url, pool_pre_ping=True)
    if admin.dialect.name != "postgresql":
        raise RuntimeError("This isolated concurrency QA requires PostgreSQL")
    schema = "notice_concurrency_qa_" + uuid4().hex
    engine = None
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, pool_pre_ping=True, connect_args={"options": f"-csearch_path={schema}"})
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
        existing_notice_writers(factory)
        simultaneous_first_insert(factory)
        print(json.dumps({"passed": 2, "database": "PostgreSQL", "production_tables_touched": False,
                          "checks": ["cached versions/children refresh under two writers", "first insert serialization"]}))
    finally:
        if engine is not None:
            engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


if __name__ == "__main__":
    main()
