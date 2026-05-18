"""
Review Queue
BullMQ queue for managing code review jobs.
"""

from typing import Optional

from bullmq import Queue, QueueEvents

from app.config import settings


class ReviewQueue:
    """
    BullMQ queue for code review processing.
    
    Handles job creation, scheduling, and event handling.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        queue_name: Optional[str] = None,
    ):
        self.redis_url = redis_url or settings.REDIS_URL
        self.queue_name = queue_name or settings.BULLMQ_REVIEW_QUEUE
        
        self._queue: Optional[Queue] = None
        self._events: Optional[QueueEvents] = None

    @property
    def queue(self) -> Queue:
        """Get or create the BullMQ queue."""
        if self._queue is None:
            self._queue = Queue(
                self.queue_name,
                {"connection": {"url": self.redis_url}},
            )
        return self._queue

    @property
    def events(self) -> QueueEvents:
        """Get or create queue events listener."""
        if self._events is None:
            self._events = QueueEvents(
                self.queue_name,
                {"connection": {"url": self.redis_url}},
            )
        return self._events

    async def add_job(
        self,
        job_name: str,
        data: dict,
        options: Optional[dict] = None,
    ) -> str:
        """
        Add a job to the queue.
        
        Args:
            job_name: Name of the job handler
            data: Job data payload
            options: Optional BullMQ job options
            
        Returns:
            Job ID
        """
        job_options = {
            "attempts": 3,
            "backoff": {
                "type": "exponential",
                "delay": 2000,
            },
            "removeOnComplete": 100,  # Keep last 100 completed jobs
            "removeOnFail": 50,  # Keep last 50 failed jobs
        }
        
        if options:
            job_options.update(options)
        
        job = await self.queue.add(job_name, data, job_options)
        return job.id

    async def get_job_status(self, job_id: str) -> Optional[dict]:
        """
        Get job status and result.
        
        Args:
            job_id: Job ID
            
        Returns:
            Job state and data
        """
        job = await self.queue.getJob(job_id)
        if not job:
            return None
        
        state = await job.getState()
        return {
            "id": job.id,
            "state": state,
            "data": job.data,
            "progress": job.progress,
            "result": job.returnvalue,
            "failed_reason": job.failedReason,
        }

    async def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a pending job.
        
        Args:
            job_id: Job ID
            
        Returns:
            True if cancelled successfully
        """
        job = await self.queue.getJob(job_id)
        if not job:
            return False
        
        return await job.remove()

    async def retry_failed(self, job_id: str) -> bool:
        """
        Retry a failed job.
        
        Args:
            job_id: Job ID
            
        Returns:
            True if retried successfully
        """
        job = await self.queue.getJob(job_id)
        if not job:
            return False
        
        return await job.retry()

    async def get_queue_stats(self) -> dict:
        """
        Get queue statistics.
        
        Returns:
            Counts of waiting, active, completed, failed jobs
        """
        counts = await self.queue.getJobCounts(
            "waiting", "active", "completed", "failed", "delayed"
        )
        return counts

    async def close(self) -> None:
        """Close queue and event connections."""
        if self._queue:
            await self._queue.close()
            self._queue = None
        if self._events:
            await self._events.close()
            self._events = None


# Global queue instance
review_queue = ReviewQueue()


async def queue_review(review_id: str) -> str:
    """
    Queue a code review for processing.
    
    Args:
        review_id: UUID of the review to process
        
    Returns:
        Job ID
    """
    return await review_queue.add_job(
        "process-review",
        {"review_id": review_id},
        {"jobId": f"review-{review_id}"},
    )


async def get_review_job_status(review_id: str) -> Optional[dict]:
    """
    Get the status of a review job.
    
    Args:
        review_id: UUID of the review
        
    Returns:
        Job status or None
    """
    return await review_queue.get_job_status(f"review-{review_id}")