"""Unit tests for the worker entry point (workers/main.py).

The BullMQ worker, the DB, and process signals are faked — these cover
the job-handler plumbing, the lifecycle helpers and main()'s error
handling without a broker or real shutdown signals.
"""

import asyncio
import signal
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import app.db
import app.workers.main as worker_main


def _clear_signal_handlers():
    """main() registers SIGTERM/SIGINT on the running loop; remove them so
    the handlers don't outlive the (per-test) event loop."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.remove_signal_handler(sig)


class _FakeJob:
    id = "job-1"
    data = {"review_id": "r-1"}


def _fake_db_ctx(monkeypatch, db):
    @asynccontextmanager
    async def ctx():
        yield db

    monkeypatch.setattr(app.db, "get_db_context", lambda: ctx())


async def test_process_job_success(monkeypatch):
    db = object()
    _fake_db_ctx(monkeypatch, db)
    seen = {}

    async def fake_process(job_data, db_session):
        seen["data"] = job_data
        seen["db"] = db_session
        return {"success": True}

    monkeypatch.setattr(worker_main, "process_review_job", fake_process)
    result = await worker_main.process_job(_FakeJob())
    assert result == {"success": True}
    assert seen["data"] == {"review_id": "r-1"}
    assert seen["db"] is db


async def test_process_job_failure_result_is_returned(monkeypatch):
    _fake_db_ctx(monkeypatch, object())

    async def fake_process(job_data, db_session):
        return {"success": False, "error": "boom"}

    monkeypatch.setattr(worker_main, "process_review_job", fake_process)
    result = await worker_main.process_job(_FakeJob())
    assert result["success"] is False
    assert result["error"] == "boom"


async def test_process_job_exception_reraises(monkeypatch):
    _fake_db_ctx(monkeypatch, object())

    async def fake_process(job_data, db_session):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(worker_main, "process_review_job", fake_process)
    with pytest.raises(RuntimeError, match="kaboom"):
        await worker_main.process_job(_FakeJob())


class _FakeWorker:
    def __init__(self, name, fn, opts):
        self.name = name
        self.fn = fn
        self.opts = opts
        self.handlers = {}

    def on(self, event, callback):
        self.handlers[event] = callback
        return self


async def test_start_worker_registers_event_handlers(monkeypatch):
    async def noop_init():
        return None

    monkeypatch.setattr(worker_main, "init_db", noop_init)
    monkeypatch.setattr(worker_main, "Worker", _FakeWorker)

    worker = await worker_main.start_worker()

    assert isinstance(worker, _FakeWorker)
    assert worker.name == worker_main.settings.BULLMQ_REVIEW_QUEUE
    assert worker.opts["connection"] == worker_main.settings.REDIS_URL
    assert worker.opts["concurrency"] == worker_main.settings.BULLMQ_CONCURRENCY
    assert set(worker.handlers) == {"completed", "failed", "progress"}

    # Invoke the registered log handlers so their bodies are exercised.
    job = SimpleNamespace(id="job-1")
    worker.handlers["completed"](job, {"ok": True})
    worker.handlers["failed"](job, "boom")
    worker.handlers["progress"](job, 50)


class _Closable:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


async def test_stop_worker_closes_and_clears_global(monkeypatch):
    async def noop_close_db():
        return None

    monkeypatch.setattr(worker_main, "close_db", noop_close_db)

    fake = _Closable()
    monkeypatch.setattr(worker_main, "worker", fake)
    await worker_main.stop_worker()
    assert fake.closed is True
    assert worker_main.worker is None

    # Second call: worker already None → skips close, still closes the DB.
    await worker_main.stop_worker()


async def test_main_runs_until_worker_stops(monkeypatch):
    stopped = {"n": 0}

    async def fake_stop():
        stopped["n"] += 1

    class _Runner:
        async def run(self):
            return None

    async def fake_start():
        return _Runner()

    monkeypatch.setattr(worker_main, "worker", None)
    monkeypatch.setattr(worker_main, "start_worker", fake_start)
    monkeypatch.setattr(worker_main, "stop_worker", fake_stop)

    try:
        await worker_main.main()  # run() returns → clean exit
    finally:
        _clear_signal_handlers()
    assert stopped["n"] == 1


async def test_main_reraises_worker_errors(monkeypatch):
    stopped = {"n": 0}

    async def fake_stop():
        stopped["n"] += 1

    class _Runner:
        async def run(self):
            raise RuntimeError("loop died")

    async def fake_start():
        return _Runner()

    monkeypatch.setattr(worker_main, "worker", None)
    monkeypatch.setattr(worker_main, "start_worker", fake_start)
    monkeypatch.setattr(worker_main, "stop_worker", fake_stop)

    try:
        with pytest.raises(RuntimeError, match="loop died"):
            await worker_main.main()
    finally:
        _clear_signal_handlers()
    assert stopped["n"] == 1  # finally still runs
