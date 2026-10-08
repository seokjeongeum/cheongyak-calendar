from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import hosted_runner
from app.static_web import mount_static_web


@pytest.fixture
def browser(tmp_path):
    (tmp_path / "index.html").write_text('<html><body>Browser app</body></html>')
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-AbCd1234.js").write_text('console.log("loaded")')
    (tmp_path / ".private").write_text("must not be served")
    return tmp_path


def make_app(directory):
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    mount_static_web(app, str(directory))
    return app


def test_hosted_web_index_and_browser_route_keep_api_same_origin(browser):
    client = TestClient(make_app(browser))
    for path in ("/", "/coverage"):
        response = client.get(path)
        assert response.status_code == 200
        assert "Browser app" in response.text
        assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.head("/coverage").status_code == 200


def test_hashed_asset_has_javascript_content_and_immutable_cache(browser):
    response = TestClient(make_app(browser)).get("/assets/index-AbCd1234.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


@pytest.mark.parametrize("path", ["/api/missing", "/assets/removed.js", "/assets/missing", "/missing.css", "/.private", "/folder/.private", "/%2e%2e/private.txt"])
def test_missing_api_assets_and_private_files_never_return_the_browser_app(browser, path):
    response = TestClient(make_app(browser)).get(path)
    assert response.status_code == 404
    assert "Browser app" not in response.text
    assert "must not be served" not in response.text


def test_disabled_hosted_web_preserves_local_api_routes(monkeypatch):
    monkeypatch.delenv("STATIC_WEB_DIR", raising=False)
    app = FastAPI()
    assert mount_static_web(app) is False
    assert TestClient(app).get("/").status_code == 404


def test_bad_configured_build_fails_at_startup(tmp_path):
    with pytest.raises(RuntimeError, match="built browser app"):
        mount_static_web(FastAPI(), str(tmp_path))


def _wait_files(files, process):
    deadline = time.monotonic() + 8
    while not all(path.is_file() for path in files):
        assert process.poll() is None, "supervisor exited before child startup"
        assert time.monotonic() < deadline, "child startup timed out"
        time.sleep(0.02)


def _child_script(tmp_path, name, *, ignore_term=False):
    script = tmp_path / f"{name}.py"
    script.write_text(
        "import os, signal, time\n"
        "from pathlib import Path\n"
        f"pid = Path({str(tmp_path / (name + '.pid'))!r})\n"
        f"stopped = Path({str(tmp_path / (name + '.stopped'))!r})\n"
        "def stop(signum, frame):\n"
        "    stopped.write_text('terminated')\n"
        "    raise SystemExit(0)\n"
        + ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n" if ignore_term else "signal.signal(signal.SIGTERM, stop)\n")
        + "pid.write_text(str(os.getpid()))\n"
        "while True: time.sleep(0.05)\n"
    )
    return [sys.executable, str(script)]


def _supervisor(commands, *, timeout=2):
    script = "from app.hosted_runner import run_services\nraise SystemExit(run_services(" + repr(commands) + f", shutdown_timeout={timeout!r}))"
    return subprocess.Popen([sys.executable, "-c", script], cwd=Path(__file__).parents[1], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _assert_gone(pid_file):
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


def test_signal_terminates_and_reaps_both_hosted_services(tmp_path):
    commands = {name: _child_script(tmp_path, name) for name in ("api", "worker")}
    process = _supervisor(commands)
    try:
        _wait_files([tmp_path / "api.pid", tmp_path / "worker.pid"], process)
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=5)
        assert process.returncode == 0
        for name in commands:
            assert (tmp_path / f"{name}.stopped").read_text() == "terminated"
            _assert_gone(tmp_path / f"{name}.pid")
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=5)


def test_unexpected_worker_exit_fails_container_and_stops_api(tmp_path):
    api = _child_script(tmp_path, "api")
    crash = tmp_path / "crash.py"
    crash.write_text("from pathlib import Path\nimport time\n" + f"while not Path({str(tmp_path / 'api.pid')!r}).is_file(): time.sleep(0.01)\nraise SystemExit(0)\n")
    process = _supervisor({"api": api, "worker": [sys.executable, str(crash)]})
    _, error = process.communicate(timeout=8)
    assert process.returncode == 1  # Even a clean, unexpected exit needs a restart.
    assert "worker process stopped (exit 0)" in error
    assert (tmp_path / "api.stopped").read_text() == "terminated"
    _assert_gone(tmp_path / "api.pid")


def test_shutdown_kills_and_reaps_a_child_that_ignores_sigterm(tmp_path):
    process = _supervisor({"worker": _child_script(tmp_path, "worker", ignore_term=True)}, timeout=0.1)
    try:
        _wait_files([tmp_path / "worker.pid"], process)
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=4)
        assert process.returncode == 0
        _assert_gone(tmp_path / "worker.pid")
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=4)


def test_hosted_main_honors_port_and_initializes_managed_database(monkeypatch):
    from app import db

    monkeypatch.setenv("DATABASE_URL", "postgresql://managed-db/fictional")
    monkeypatch.setenv("PORT", "9191")
    events = []
    monkeypatch.setattr(db, "init_db", lambda: events.append("database"))

    def run(commands):
        events.append(commands)
        return 0

    monkeypatch.setattr(hosted_runner, "run_services", run)
    assert hosted_runner.main() == 0
    assert events[0] == "database"
    assert events[1]["api"][-2:] == ["--port", "9191"]
    assert events[1]["worker"] == [sys.executable, "-m", "app.ingest.worker"]


@pytest.mark.parametrize("port", ["bad", "0", "65536"])
def test_invalid_host_port_fails_cleanly(monkeypatch, port):
    monkeypatch.setenv("PORT", port)
    assert hosted_runner.main() == 1


def test_hosted_main_rejects_ephemeral_sqlite(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./temporary.db")
    monkeypatch.delenv("PORT", raising=False)
    assert hosted_runner.main() == 1
