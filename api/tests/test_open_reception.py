"""Official open reception must not inherit a fabricated end from its start."""

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app.db import init_db, make_engine
from app.extract import reprocess
from app.ingest import competition
from app.repository import upsert_notice


def test_open_apt_reception_is_not_classified_as_ended_for_result_collection():
    event = SimpleNamespace(kind="application", label="상시 접수", start_date=date(2026, 9, 1), end_date=None)
    notice = SimpleNamespace(events=[event], competitions=[])
    assert not competition._is_published_window(notice, date(2026, 10, 6), "getAPTLttotPblancCmpet")
    event.label = "일반공급"
    assert competition._is_published_window(notice, date(2026, 10, 6), "getAPTLttotPblancCmpet")


@pytest.mark.asyncio
async def test_active_reprocessing_includes_only_explicit_open_reception_before_limit(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'open.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(reprocess, "SessionLocal", factory)
    try:
        with factory() as session:
            for index, label in enumerate(["상시 접수", "일반공급", "마감 안내 시 주의", "상시 계약일"]):
                upsert_notice(session, {
                    "source": "cheongyak_home", "external_id": f"open-{index}", "title": label,
                    "category": "apt", "announcement_date": f"2000-01-0{index + 1}",
                    "official_url": "https://www.applyhome.co.kr/notice/open",
                    "events": [{"kind": "application", "label": label, "start_date": "2000-01-01", "end_date": None}],
                    "rules": [], "prices": [],
                })
            session.commit()
        seen = []

        async def enrich(snapshot, **kwargs):
            seen.append(snapshot["external_id"])
            return snapshot

        monkeypatch.setattr(reprocess, "enrich_notice", enrich)
        summary = await reprocess.reprocess(active=True, limit=1, dry_run=True)
        assert summary["attempted"] == 1
        assert summary["failed"] == 0
        assert seen == ["open-0"]
    finally:
        engine.dispose()
