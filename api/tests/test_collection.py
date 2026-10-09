import asyncio
import hashlib
import os
import subprocess
import sys
import threading
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


def test_shutdown_between_resume_claim_and_child_start_keeps_interruption(store, monkeypatch):
    manager = collection.ManualCollector()
    state, _ = collection.claim_collection("manual")
    calls = []
    monkeypatch.setattr(collection.subprocess, "Popen", lambda *args, **kwargs: calls.append(args))
    manager.shutdown()
    manager.start(state.job_id)
    assert calls == []
    assert collection.collection_state().status == "interrupted"


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


def interrupted_manual(store):
    previous, _ = collection.claim_collection("manual")
    collection.finish_collection(previous.job_id, "interrupted", "fictional deployment interruption")
    with store() as session:
        session.add(IntegrationSetting(name="DATA_GO_KR_API_KEY", value="fictional-saved-feed-key"))
        session.commit()
    return previous


def test_startup_resumes_saved_owner_job_once_for_each_code_version(store, monkeypatch):
    previous = interrupted_manual(store)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "fictional-deployment-one")
    starts = []
    manager = collection.ManualCollector()
    monkeypatch.setattr(manager, "start", starts.append)

    manager.startup()
    resumed = collection.collection_state()
    assert starts == [resumed.job_id]
    assert resumed.job_id != previous.job_id
    assert resumed.status == "running"
    assert resumed.trigger.startswith("manual-resume:")
    assert len(resumed.trigger) <= 32
    assert "중단된 수집" in resumed.message
    assert "fictional-saved-feed-key" not in resumed.model_dump_json()
    assert "fictional-deployment-one" not in resumed.model_dump_json()

    # A deployment or sleep interruption of this retry must not create a
    # restart loop on the same code. An explicit owner start still works.
    collection.finish_collection(resumed.job_id, "interrupted", "fictional retry interruption")
    manager.startup()
    assert starts == [resumed.job_id]
    assert collection.collection_state().status == "interrupted"

    monkeypatch.setenv("RENDER_GIT_COMMIT", "fictional-deployment-two")
    manager.startup()
    upgraded = collection.collection_state()
    assert starts == [resumed.job_id, upgraded.job_id]
    assert upgraded.trigger != resumed.trigger
    assert upgraded.job_id != resumed.job_id

    collection.finish_collection(upgraded.job_id, "interrupted", "fictional retry interruption")
    explicit, claimed = collection.claim_collection("manual")
    assert claimed and explicit.trigger == "manual"


@pytest.mark.parametrize("status", ["idle", "completed", "error"])
def test_startup_does_not_resume_other_job_states(store, monkeypatch, status):
    interrupted_manual(store)
    with store() as session:
        row = session.get(CollectionRun, collection.NAME)
        row.status = status
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        session.commit()
    manager = collection.ManualCollector()
    starts = []
    monkeypatch.setattr(manager, "start", starts.append)
    manager.startup()
    assert starts == []
    with store() as session:
        assert session.get(CollectionRun, collection.NAME).status == status


def test_startup_resumes_when_old_api_records_shutdown_after_new_api_start(store, monkeypatch):
    interrupted_manual(store)
    previous, _ = collection.claim_collection("manual")
    monkeypatch.setattr(collection, "STARTUP_RESUME_POLL_SECONDS", 0.01)
    starts = []
    resumed = threading.Event()
    managers = [collection.ManualCollector(), collection.ManualCollector()]
    for manager in managers:
        monkeypatch.setattr(manager, "start", lambda job_id: (starts.append(job_id), resumed.set()))

    try:
        for manager in managers:
            manager.startup()
        # A successor cannot take the predecessor's valid lease.
        assert not resumed.wait(0.03)
        assert collection.collection_state().job_id == previous.job_id
        assert collection.collection_state().status == "running"

        collection.finish_collection(previous.job_id, "interrupted", "fictional old API shutdown")
        assert resumed.wait(2)
        for manager in managers:
            thread = manager.resume_thread
            if thread:
                thread.join(timeout=2)
        state = collection.collection_state()
        assert starts == [state.job_id]
        assert state.job_id != previous.job_id
        assert state.trigger == collection._resume_trigger()

        collection.finish_collection(state.job_id, "interrupted", "fictional repeated shutdown")
        for manager in managers:
            manager.startup()
        assert starts == [state.job_id]
        assert collection.collection_state().status == "interrupted"
    finally:
        for manager in managers:
            manager.shutdown()


@pytest.mark.parametrize("transition", ["completed", "replacement", "cancelled", "watch-expired"])
def test_startup_running_monitor_stops_without_replacing_uninterrupted_work(store, monkeypatch, transition):
    interrupted_manual(store)
    previous, _ = collection.claim_collection("manual")
    monkeypatch.setattr(collection, "STARTUP_RESUME_POLL_SECONDS", 0.01)
    monkeypatch.setattr(collection, "STARTUP_RESUME_WATCH_SECONDS", 0.1)
    manager = collection.ManualCollector()
    starts = []
    monkeypatch.setattr(manager, "start", starts.append)
    try:
        manager.startup()
        thread = manager.resume_thread
        assert thread is not None
        if transition == "completed":
            collection.finish_collection(previous.job_id, "completed", "fictional completed collection")
        elif transition == "replacement":
            # The singleton changes atomically, as it does when another API
            # wins a claim before this monitor can observe the interruption.
            with store() as session:
                session.get(CollectionRun, collection.NAME).job_id = "fictional-replacement-job"
                session.commit()
        elif transition == "cancelled":
            manager.shutdown()
            collection.finish_collection(previous.job_id, "interrupted", "fictional old API shutdown")
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert starts == []
        state = collection.collection_state()
        assert state.job_id == ("fictional-replacement-job" if transition == "replacement" else previous.job_id)
        assert state.status == {"completed": "completed", "cancelled": "interrupted"}.get(transition, "running")
    finally:
        manager.shutdown()


def test_startup_resumes_expired_owner_lease_without_waiting_for_shutdown(store, monkeypatch):
    interrupted_manual(store)
    previous, _ = collection.claim_collection("manual")
    with store() as session:
        session.get(CollectionRun, collection.NAME).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    manager = collection.ManualCollector()
    starts = []
    monkeypatch.setattr(manager, "start", starts.append)
    manager.startup()
    state = collection.collection_state()
    assert starts == [state.job_id]
    assert state.job_id != previous.job_id
    assert state.status == "running"
    assert state.trigger == collection._resume_trigger()


def test_startup_running_monitor_cannot_resume_after_saved_feed_key_removed(store, monkeypatch):
    interrupted_manual(store)
    previous, _ = collection.claim_collection("manual")
    monkeypatch.setattr(collection, "STARTUP_RESUME_POLL_SECONDS", 0.01)
    manager = collection.ManualCollector()
    starts = []
    monkeypatch.setattr(manager, "start", starts.append)
    try:
        manager.startup()
        thread = manager.resume_thread
        with store() as session:
            session.get(IntegrationSetting, "DATA_GO_KR_API_KEY").value = ""
            session.commit()
        collection.finish_collection(previous.job_id, "interrupted", "fictional old API shutdown")
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert starts == []
        assert collection.collection_state().job_id == previous.job_id
    finally:
        manager.shutdown()


@pytest.mark.parametrize("trigger", ["scheduled", "manual-resume:invalid", None])
@pytest.mark.parametrize("status", ["running", "interrupted"])
def test_startup_does_not_resume_non_owner_job(store, monkeypatch, trigger, status):
    interrupted_manual(store)
    with store() as session:
        row = session.get(CollectionRun, collection.NAME)
        row.trigger = trigger
        row.status = status
        if status == "running":
            row.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        session.commit()
    manager = collection.ManualCollector()
    starts = []
    monkeypatch.setattr(manager, "start", starts.append)
    manager.startup()
    assert starts == []
    assert manager.resume_thread is None
    assert collection.collection_state().status == status


@pytest.mark.parametrize("saved_key", [None, "", "   ", "gemini-only"])
def test_startup_requires_nonempty_feed_key_saved_on_server(store, monkeypatch, saved_key):
    previous, _ = collection.claim_collection("manual")
    collection.finish_collection(previous.job_id, "interrupted", "fictional interruption")
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "fictional-environment-only-key")
    if saved_key is not None:
        with store() as session:
            name = "GEMINI_API_KEY" if saved_key == "gemini-only" else "DATA_GO_KR_API_KEY"
            session.add(IntegrationSetting(name=name, value=saved_key))
            session.commit()
    manager = collection.ManualCollector()
    starts = []
    monkeypatch.setattr(manager, "start", starts.append)
    manager.startup()
    assert starts == []
    assert collection.collection_state().job_id == previous.job_id


def test_startup_resume_is_atomic_across_api_instances(store, monkeypatch):
    previous = interrupted_manual(store)
    starts = []
    monkeypatch.setattr(collection.ManualCollector, "start", lambda _, job_id: starts.append(job_id))
    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(lambda _: collection.ManualCollector().startup(), range(6)))
    assert len(starts) == 1
    state = collection.collection_state()
    assert state.status == "running"
    assert state.job_id == starts[0] and state.job_id != previous.job_id


def test_pipeline_upgrade_allows_one_resume_without_host_deployment_metadata(store, monkeypatch):
    from app.extract import pipeline

    interrupted_manual(store)
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    starts = []
    manager = collection.ManualCollector()
    monkeypatch.setattr(manager, "start", starts.append)
    manager.startup()
    first = collection.collection_state()
    collection.finish_collection(first.job_id, "interrupted", "fictional interruption")
    manager.startup()
    assert starts == [first.job_id]

    monkeypatch.setattr(pipeline, "DOCUMENT_PIPELINE_VERSION", "fictional-new-pipeline-version")
    manager.startup()
    upgraded = collection.collection_state()
    assert starts == [first.job_id, upgraded.job_id]
    assert upgraded.trigger != first.trigger


def test_resume_claim_cannot_replace_concurrent_explicit_start_or_deleted_key(store):
    interrupted_manual(store)
    previous = collection.collection_state()
    explicit, _ = collection.claim_collection("manual")
    state, claimed = collection.claim_collection(collection._resume_trigger(), interrupted_from=previous)
    assert not claimed and state.job_id == explicit.job_id

    collection.finish_collection(explicit.job_id, "interrupted", "fictional interruption")
    previous = collection.collection_state()
    with store() as session:
        session.get(IntegrationSetting, "DATA_GO_KR_API_KEY").value = ""
        session.commit()
    state, claimed = collection.claim_collection(collection._resume_trigger(), interrupted_from=previous)
    assert not claimed and state.job_id == previous.job_id


def test_startup_resume_failure_keeps_api_available_without_echoing_error(monkeypatch, caplog):
    def unavailable():
        raise OSError("fictional-private-database-url")
    monkeypatch.setattr(collection, "_claim_interrupted_manual_resume", unavailable)
    manager = collection.ManualCollector()
    manager.stopping = True
    manager.startup()
    assert not manager.stopping
    assert "OSError" in caplog.text
    assert "fictional-private-database-url" not in caplog.text
