"""Unit tests for the BullMQ review queue wrapper (workers/review_queue.py).

The queue/event connections are faked — no Redis involved — so these
cover the events constructor, job status/cancel/retry/stats and the
close paths without a broker.
"""

import importlib

from app.workers.review_queue import ReviewQueue

# NOT `import app.workers.review_queue as rq_module`: app/workers/__init__
# re-exports the `review_queue` instance, which shadows the submodule
# attribute on the package — importlib resolves the real module.
rq_module = importlib.import_module("app.workers.review_queue")


class _FakeJob:
    def __init__(self, job_id="job-1"):
        self.id = job_id
        self.data = {"review_id": "r-1"}
        self.progress = 42
        self.returnvalue = {"success": True}
        self.failedReason = None
        self.removed = False
        self.retried = False

    async def getState(self):
        return "completed"

    async def remove(self):
        self.removed = True
        return True

    async def retry(self):
        self.retried = True
        return True


class _FakeQueue:
    def __init__(self, job=None):
        self._job = job
        self.closed = False
        self.count_names = None

    async def getJob(self, job_id):
        return self._job

    async def getJobCounts(self, *names):
        self.count_names = names
        return {
            "waiting": 1,
            "active": 0,
            "completed": 5,
            "failed": 2,
            "delayed": 0,
        }

    async def close(self):
        self.closed = True


class _FakeQueueEvents:
    def __init__(self, name, opts):
        self.name = name
        self.opts = opts
        self.closed = False

    async def close(self):
        self.closed = True


def test_events_property_constructs_and_caches_listener(monkeypatch):
    monkeypatch.setattr(rq_module, "QueueEvents", _FakeQueueEvents)
    rq = ReviewQueue()
    events = rq.events
    assert isinstance(events, _FakeQueueEvents)
    assert events.name == rq.queue_name
    assert events.opts["connection"] == rq.redis_url
    assert rq.events is events  # cached, not rebuilt


async def test_get_job_status_present_and_missing():
    rq = ReviewQueue()
    rq._queue = _FakeQueue(_FakeJob())
    status = await rq.get_job_status("job-1")
    assert status == {
        "id": "job-1",
        "state": "completed",
        "data": {"review_id": "r-1"},
        "progress": 42,
        "result": {"success": True},
        "failed_reason": None,
    }

    rq._queue = _FakeQueue(None)
    assert await rq.get_job_status("missing") is None


async def test_cancel_and_retry_job_present_and_missing():
    rq = ReviewQueue()
    job = _FakeJob()
    rq._queue = _FakeQueue(job)
    assert await rq.cancel_job("job-1") is True
    assert job.removed is True
    assert await rq.retry_failed("job-1") is True
    assert job.retried is True

    rq._queue = _FakeQueue(None)
    assert await rq.cancel_job("missing") is False
    assert await rq.retry_failed("missing") is False


async def test_get_queue_stats_requests_all_counts():
    rq = ReviewQueue()
    fake = _FakeQueue(_FakeJob())
    rq._queue = fake
    counts = await rq.get_queue_stats()
    assert counts["failed"] == 2
    assert fake.count_names == (
        "waiting",
        "active",
        "completed",
        "failed",
        "delayed",
    )


async def test_close_resets_connections_and_is_idempotent():
    rq = ReviewQueue()
    queue = _FakeQueue()
    events = _FakeQueueEvents(rq.queue_name, {})
    rq._queue = queue
    rq._events = events
    await rq.close()
    assert queue.closed is True
    assert events.closed is True
    assert rq._queue is None
    assert rq._events is None
    await rq.close()  # nothing set → no-op


async def test_get_review_job_status_uses_global_queue(monkeypatch):
    rq = ReviewQueue()
    rq._queue = _FakeQueue(_FakeJob())
    monkeypatch.setattr(rq_module, "review_queue", rq)
    status = await rq_module.get_review_job_status("r-1")
    assert status is not None
    assert status["id"] == "job-1"
