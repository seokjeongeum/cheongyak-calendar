"""Supervise the API and three-hour collector in one hosted app container."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from time import monotonic


LOGGER = logging.getLogger("cheongyak.hosted")


def _signal_group(process: subprocess.Popen, signum: int) -> None:
    # Separate sessions include document conversion descendants in shutdown.
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        pass


def _shutdown(processes: Sequence[subprocess.Popen], timeout: float) -> None:
    for process in processes:
        _signal_group(process, signal.SIGTERM)
    deadline = monotonic() + timeout
    for process in processes:
        try:
            process.wait(timeout=max(0, deadline - monotonic()))
        except subprocess.TimeoutExpired:
            _signal_group(process, signal.SIGKILL)
            process.wait()


def run_services(commands: Mapping[str, Sequence[str]], *, shutdown_timeout: float = 15) -> int:
    """Exit nonzero if either child stops so the host restarts the whole app."""
    stopping = threading.Event()
    previous_handlers = {}
    processes: dict[str, subprocess.Popen] = {}

    def request_shutdown(_signum, _frame):
        stopping.set()

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.signal(signum, request_shutdown)
        for name, command in commands.items():
            if stopping.is_set():
                return 0
            processes[name] = subprocess.Popen(command, start_new_session=True)
        while not stopping.wait(0.2):
            for name, process in processes.items():
                code = process.poll()
                if code is not None:
                    LOGGER.error("Hosted %s process stopped (exit %s)", name, code)
                    return code if code > 0 else 1
        return 0
    finally:
        _shutdown(list(processes.values()), shutdown_timeout)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    try:
        port = int(os.getenv("PORT", "8080"))
        if not 1 <= port <= 65535:
            raise ValueError()
    except ValueError:
        LOGGER.error("PORT must be a valid TCP port")
        return 1
    # The hosted app must not silently store public history and saved keys in
    # an ephemeral SQLite database. Local Compose still uses its own commands.
    if not os.getenv("DATABASE_URL", "").startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        LOGGER.error("Hosted deployment requires a managed PostgreSQL DATABASE_URL")
        return 1
    try:
        from app.db import init_db

        # Serialize the additive schema upgrade before starting both children.
        init_db()
        return run_services({
            "api": [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", str(port)],
            "worker": [sys.executable, "-m", "app.ingest.worker"],
        })
    except Exception as error:
        # Connection exceptions can contain infrastructure credentials.
        LOGGER.error("Hosted startup failed: %s", type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
