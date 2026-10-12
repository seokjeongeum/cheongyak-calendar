"""Bounded official-feed passes preserve inventory and advance their backlog."""

import asyncio
import copy
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from app import integration_settings
from app.db import init_db, make_engine
from app.ingest import competition, myhome
from app.models import CompetitionState
from app.repository import upsert_notice


@pytest.mark.asyncio
async def test_myhome_all_list_pages_and_rental_survive_persistently_blocked_sale_details(monkeypatch):
    requests = []
    snapshots = []
    detail_started = asyncio.Event()

    async def listing(client, url, params):
        operation = url.rsplit("/", 1)[-1]
        requests.append((operation, params["pageNo"]))
        sale = operation == "ltRsdtRcritNtcList"
        page = params["pageNo"]
        size = 100 if sale and page == 1 else 1
        return {"response": {"body": {"item": [
            {"pblancId": f"{operation}-{page}-{index}", "pblancNm": "공식 공고"}
            for index in range(size)
        ], "totalCount": 101 if sale else 1}}}

    async def blocked_detail(client, payload, notice_id):
        assert requests[-1] == ("rsdtRcritNtcList", 1)
        assert len([row for batch in snapshots for row in batch]) == 102
        detail_started.set()
        await asyncio.Event().wait()

    async def save(rows):
        snapshots.append(copy.deepcopy(rows))

    monkeypatch.setattr(myhome, "get_json", listing)
    monkeypatch.setattr(myhome, "enrich_sale_detail", blocked_detail)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("No live HTTP"))) as client:
        for _ in range(2):
            requests.clear()
            snapshots.clear()
            detail_started.clear()
            task = asyncio.create_task(myhome.collect(client, "fictional", date(2026, 4, 1),
                date(2026, 10, 12), on_rows=save))
            try:
                await asyncio.wait_for(detail_started.wait(), timeout=2)
                assert requests == [("ltRsdtRcritNtcList", 1), ("ltRsdtRcritNtcList", 2),
                    ("rsdtRcritNtcList", 1)]
                assert snapshots[-1][0]["category"] == "public_rental"
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task


@pytest.mark.asyncio
async def test_myhome_ready_detail_batch_is_durable_before_later_detail_failure(monkeypatch):
    snapshots = []
    active = 0
    maximum_active = 0

    async def listing(client, url, params):
        operation = url.rsplit("/", 1)[-1]
        size = 7 if operation == "ltRsdtRcritNtcList" else 1
        return {"response": {"body": {"item": [
            {"pblancId": str(index), "pblancNm": "공식 공고"} for index in range(size)
        ], "totalCount": size}}}

    async def detail(client, payload, notice_id):
        nonlocal active, maximum_active
        if notice_id == "6":
            assert len(snapshots) == 3
            assert all(row.get("prices") for row in snapshots[-1])
            raise TimeoutError
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0)
        payload["prices"] = [{"unit_type": "84", "price_kind": "sale_total",
            "amount_krw": 300_000_000, "verification": "official"}]
        active -= 1

    async def save(rows):
        snapshots.append(copy.deepcopy(rows))
        # A consumer's normalization cannot alter the collector's final data.
        for row in rows:
            row["title"] = "consumer copy"

    monkeypatch.setattr(myhome, "get_json", listing)
    monkeypatch.setattr(myhome, "enrich_sale_detail", detail)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("No live HTTP"))) as client:
        with pytest.raises(TimeoutError):
            await myhome.collect(client, "fictional", date(2026, 4, 1), date(2026, 10, 12), on_rows=save)
    assert maximum_active == myhome.DETAIL_CONCURRENCY
    assert len(snapshots[-1]) == myhome.DETAIL_BATCH_SIZE
    assert all(row["title"] == "공식 공고" and row["prices"] for row in snapshots[-1])


@pytest.mark.asyncio
async def test_competition_next_bounded_pass_attempts_unvisited_notice(monkeypatch, tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'rotation.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    identities = {}
    with factory() as session:
        for number, announced in (("1001", "2026-10-01"), ("1002", "2026-09-01")):
            notice = upsert_notice(session, {
                "source": "cheongyak_home", "external_id": f"getUrbtyOfctlLttotPblancDetail:{number}:{number}",
                "title": f"공식 오피스텔 {number}", "category": "officetel", "address": f"서울 {number}",
                "announcement_date": announced, "official_url": f"https://official.example/{number}",
                "events": [{"kind": "general", "label": "신청 접수", "start_date": "2026-10-01"}],
            })
            identities[number] = notice.id
        session.commit()
    monkeypatch.setattr(competition, "SessionLocal", factory)
    monkeypatch.setattr(competition, "init_db", lambda: None)
    monkeypatch.setattr(integration_settings, "setting_value", lambda _: "fictional")
    starts = []
    started = asyncio.Event()

    async def blocked_api(client, key, operation, house_no, notice_no, observed_at):
        starts.append(house_no)
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(competition, "collect_api", blocked_api)
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("No live HTTP"))) as client:
            for expected in ("1001", "1002"):
                started.clear()
                task = asyncio.create_task(competition.run_once(today=date(2026, 10, 12), client=client))
                try:
                    await asyncio.wait_for(started.wait(), timeout=2)
                    assert starts[-1] == expected
                    with factory() as session:
                        state = session.get(CompetitionState, identities[expected])
                        assert state.status == "running" and state.last_attempt_at is not None
                finally:
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
        assert starts == ["1001", "1002"]
    finally:
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["error", "pending", "success"])
async def test_competition_oldest_attempt_rotates_every_result_status(monkeypatch, tmp_path, status):
    engine = make_engine(f"sqlite:///{tmp_path / 'attempts.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    with factory() as session:
        for number, days in (("1001", 1), ("1002", 2)):
            notice = upsert_notice(session, {
                "source": "cheongyak_home", "external_id": f"getUrbtyOfctlLttotPblancDetail:{number}:{number}",
                "title": f"공식 오피스텔 {number}", "category": "officetel", "address": f"서울 {number}",
                "announcement_date": "2026-10-01" if number == "1001" else "2026-09-01",
                "official_url": f"https://official.example/{number}",
                "events": [{"kind": "general", "label": "신청 접수", "start_date": "2026-10-01"}],
            })
            session.add(CompetitionState(notice_id=notice.id, status=status,
                last_attempt_at=now - timedelta(days=days)))
        session.commit()
    monkeypatch.setattr(competition, "SessionLocal", factory)
    monkeypatch.setattr(competition, "init_db", lambda: None)
    monkeypatch.setattr(integration_settings, "setting_value", lambda _: "fictional")
    starts = []

    async def empty_api(client, key, operation, house_no, notice_no, observed_at):
        starts.append(house_no)
        return []

    monkeypatch.setattr(competition, "collect_api", empty_api)
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("No live HTTP"))) as client:
            await competition.run_once(today=date(2026, 10, 12), client=client)
        assert starts == ["1002", "1001"]
    finally:
        engine.dispose()
