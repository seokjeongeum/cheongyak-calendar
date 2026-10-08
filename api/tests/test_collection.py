import asyncio
import hashlib
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import collection, integration_settings
from app.db import get_session, init_db, make_engine
from app.ingest import worker
from app.models import CollectionRun, IntegrationSetting, SourceStatus

TOKEN = "fictional-collection-owner-token"


@pytest.fixture
def store(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'collection.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(collection, "SessionLocal", factory)
    monkeypatch.setattr(worker, "init_db", lambda: None)
    with factory() as session:
        session.add(IntegrationSetting(name=integration_settings.ADMIN_HASH, value=hashlib.sha256(TOKEN.encode()).hexdigest()))
        session.commit()
    yield factory
    engine.dispose()


@pytest.fixture
def client(store, monkeypatch):
    app = FastAPI()
    app.include_router(collection.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    def dependency():
        with store() as session:
            yield session

    app.dependency_overrides[get_session] = dependency
    starts = []
    monkeypatch.setattr(collection.manual_collector, "start", starts.append)
    test_client = TestClient(app)
    test_client.starts = starts
    return test_client


def start(client):
    return client.post("/api/collection", headers={"Authorization": f"Bearer {TOKEN}"})


def test_public_can_view_sanitized_status_but_cannot_start(client):
    response = client.get("/api/collection")
    assert response.json()["status"] == "idle"
    assert response.headers["cache-control"] == "no-store"
    for headers in ({}, {"Authorization": "Bearer fictional-wrong-token"}):
        response = client.post("/api/collection", headers=headers)
        assert response.status_code == 401
        assert "fictional-wrong-token" not in response.text
    assert client.starts == []
    assert TOKEN not in client.get("/api/collection").text


def test_owner_start_returns_202_and_deduplicates_existing_job(client):
    first = start(client)
    second = start(client)
    assert first.status_code == second.status_code == 202
    assert first.headers["cache-control"] == "no-store"
    assert first.json()["status"] == "running"
    assert first.json()["job_id"] == second.json()["job_id"]
    assert len(client.starts) == 1
    assert TOKEN not in first.text
    assert first.json()["started_at"].endswith("Z")
    assert client.get("/api/health").json() == {"status": "ok"}


def test_concurrent_claims_across_collectors_have_one_owner(store):
    with ThreadPoolExecutor(max_workers=6) as executor:
        outcomes = list(executor.map(lambda _: collection.claim_collection("scheduled"), range(6)))
    assert sum(claimed for _, claimed in outcomes) == 1
    assert len({state.job_id for state, _ in outcomes}) == 1


def test_stale_deployment_is_interrupted_and_late_finish_cannot_replace_new_job(store):
    first, _ = collection.claim_collection("manual")
    with store() as session:
        session.get(CollectionRun, collection.NAME).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    stale = collection.collection_state()
    assert stale.status == "interrupted"
    assert stale.finished_at is not None
    assert not collection.renew_collection(first.job_id)
    replacement, claimed = collection.claim_collection("scheduled")
    assert claimed and replacement.job_id != first.job_id
    collection.finish_collection(first.job_id, "completed", "late stale success")
    assert collection.collection_state().job_id == replacement.job_id
    assert collection.collection_state().status == "running"
    assert collection.renew_collection(replacement.job_id)


@pytest.mark.parametrize("termination", ["error", "interrupted", "expired"])
def test_interrupted_source_cleanup_preserves_history_and_newer_attempts(store, termination):
    state, _ = collection.claim_collection("manual")
    attempted = state.started_at + timedelta(milliseconds=1)
    before_job = state.started_at - timedelta(days=1)
    future_job = state.started_at + timedelta(days=1)
    with store() as session:
        for source, when in (("current", attempted), ("older", before_job), ("newer", future_job)):
            session.add(SourceStatus(source=source, status="running", last_attempt_at=when,
                                     last_success_at=before_job, record_count=123, message="running"))
        if termination == "expired":
            session.get(CollectionRun, collection.NAME).lease_expires_at = before_job
        session.commit()
    if termination == "expired":
        collection.collection_state()
    else:
        collection.finish_collection(state.job_id, termination, "fictional interruption")
    with store() as session:
        current = session.get(SourceStatus, "current")
        assert current.status == "error"
        assert "중단" in current.message
        assert current.record_count == 123
        assert current.last_success_at.replace(tzinfo=timezone.utc) == before_job
        assert session.get(SourceStatus, "older").status == "running"
        assert session.get(SourceStatus, "newer").status == "running"


def test_replacing_expired_job_clears_its_running_source_without_a_status_read(store):
    previous, _ = collection.claim_collection("manual")
    with store() as session:
        session.get(CollectionRun, collection.NAME).lease_expires_at = previous.started_at - timedelta(seconds=1)
        session.add(SourceStatus(source="lh", status="running", last_attempt_at=previous.started_at,
                                 record_count=10, message="수집 중"))
        session.commit()
    replacement, claimed = collection.claim_collection("scheduled")
    assert claimed and replacement.job_id != previous.job_id
    with store() as session:
        assert session.get(SourceStatus, "lh").status == "error"
        assert session.get(SourceStatus, "lh").record_count == 10


def test_failed_spawn_is_safe_and_retryable(store, monkeypatch, caplog):
    def fail(*_, **__):
        raise OSError("fictional-secret-database-url")
    monkeypatch.setattr(collection.subprocess, "Popen", fail)
    manager = collection.ManualCollector()
    state, _ = collection.claim_collection("manual")
    manager.start(state.job_id)
    assert collection.collection_state().status == "error"
    assert "fictional-secret-database-url" not in caplog.text
    assert "fictional-secret-database-url" not in collection.collection_state().model_dump_json()
    assert collection.claim_collection("manual")[1]


def test_worker_shares_lease_and_records_partial_results(store, monkeypatch):
    calls = []
    async def fake_run():
        calls.append(True)
        return {"sh": {"status": "error"}, "gh": {"status": "ok"}, "lh": {"status": "disabled"}}
    monkeypatch.setattr(worker, "run_once", fake_run)
    existing, _ = collection.claim_collection("manual")
    assert asyncio.run(worker.run_cycle()) is None
    assert calls == []
    assert asyncio.run(worker.run_cycle(job_id="not-the-owner-job")) is None
    assert calls == []
    asyncio.run(worker.run_cycle(job_id=existing.job_id))
    state = collection.collection_state()
    assert state.status == "completed"
    assert "1개 출처" in state.message
    assert state.finished_at is not None
    assert calls == [True]


@pytest.mark.parametrize("failure,status", [(ValueError("fictional-secret"), "error"), (asyncio.CancelledError(), "interrupted")])
def test_worker_failure_finishes_state_without_echoing_exceptions(store, monkeypatch, failure, status):
    async def fake_run():
        raise failure
    monkeypatch.setattr(worker, "run_once", fake_run)
    with pytest.raises(type(failure)):
        asyncio.run(worker.run_cycle())
    state = collection.collection_state()
    assert state.status == status
    assert "fictional-secret" not in state.model_dump_json()


def test_manual_subprocess_keeps_api_responsive_and_shutdown_reaps_group(client, store, monkeypatch, tmp_path):
    real_popen = subprocess.Popen
    child_pid = tmp_path / "child.pid"
    parent_pid = tmp_path / "parent.pid"
    calls = []

    def fake_feed_process(command, **kwargs):
        calls.append(command)
        script = (
            "import os, pathlib, subprocess, sys, time\n"
            f"pathlib.Path({str(parent_pid)!r}).write_text(str(os.getpid()))\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
            f"pathlib.Path({str(child_pid)!r}).write_text(str(child.pid))\n"
            "time.sleep(120)\n"
        )
        return real_popen([sys.executable, "-c", script], **kwargs)

    monkeypatch.setattr(collection.subprocess, "Popen", fake_feed_process)
    manager = collection.ManualCollector()
    monkeypatch.setattr(collection, "manual_collector", manager)
    try:
        response = start(client)
        assert response.status_code == 202
        deadline = time.monotonic() + 5
        while not child_pid.exists() or not parent_pid.exists():
            assert time.monotonic() < deadline
            time.sleep(0.02)
        health_started = time.monotonic()
        assert client.get("/api/health").status_code == 200
        assert time.monotonic() - health_started < 1
        assert client.get("/api/collection").json()["status"] == "running"
        assert calls == [[sys.executable, "-m", "app.ingest.worker", "--once", "--job-id", response.json()["job_id"]]]
        assert TOKEN not in str(calls)
        manager.shutdown()
        assert collection.collection_state().status == "interrupted"
        parent = int(parent_pid.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(parent, 0)
        # Both were in the new process group; the grandchild may briefly be a
        # zombie awaiting PID1 but cannot still run after group termination.
        proc_stat = f"/proc/{int(child_pid.read_text())}/stat"
        if os.path.exists(proc_stat):
            assert open(proc_stat).read().split()[2] == "Z"
    finally:
        manager.shutdown()
