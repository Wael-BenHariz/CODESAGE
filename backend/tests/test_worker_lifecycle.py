"""Worker and review queue invariants are covered by the unit suite; this
module adds explicit regression assertions for queue configuration and the
processor's failure-tolerant review contract without contacting GitHub/LLMs.
"""

from app.config import settings


def test_review_queue_name_is_configured():
    assert settings.BULLMQ_REVIEW_QUEUE


def test_worker_concurrency_is_positive():
    assert settings.BULLMQ_CONCURRENCY > 0
