"""
Worker Entry Point
Main script for running the BullMQ worker process.
"""

import asyncio
import logging
import signal
import sys
from typing import Optional

from bullmq import Worker

from app.config import settings
from app.db import close_db, init_db
from app.workers.review_processor import process_review_job

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global worker instance
worker: Optional[Worker] = None


async def process_job(job: dict) -> dict:
    """
    Job processor handler.
    
    Args:
        job: Job data from BullMQ
        
    Returns:
        Job result
    """
    from app.db import get_db_context
    
    logger.info(f"Processing job {job.get('id', 'unknown')}")
    
    try:
        async with get_db_context() as db:
            result = await process_review_job(job.data, db)
            
            if result.get("success"):
                logger.info(f"Job {job.get('id')} completed successfully")
            else:
                logger.error(f"Job {job.get('id')} failed: {result.get('error')}")
            
            return result
            
    except Exception as e:
        logger.exception(f"Error processing job {job.get('id')}: {e}")
        raise


async def start_worker() -> Worker:
    """
    Start the BullMQ worker.
    
    Returns:
        Worker instance
    """
    logger.info("Starting review worker...")
    
    # Initialize database
    await init_db()
    
    # Create worker
    worker = Worker(
        settings.BULLMQ_REVIEW_QUEUE,
        process_job,
        {
            "connection": {"url": settings.REDIS_URL},
            "concurrency": settings.BULLMQ_CONCURRENCY,
        },
    )
    
    # Event handlers
    @worker.on("completed")
    def handle_completed(job, result):
        logger.info(f"Job {job.id} completed: {result}")
    
    @worker.on("failed")
    def handle_failed(job, err):
        logger.error(f"Job {job.id} failed: {err}")
    
    @worker.on("progress")
    def handle_progress(job, progress):
        logger.debug(f"Job {job.id} progress: {progress}%")
    
    logger.info(f"Worker started, listening on queue: {settings.BULLMQ_REVIEW_QUEUE}")
    
    return worker


async def stop_worker():
    """Stop the worker gracefully."""
    global worker
    
    logger.info("Stopping worker...")
    
    if worker:
        await worker.close()
        worker = None
    
    await close_db()
    
    logger.info("Worker stopped")


async def main():
    """Main entry point for the worker."""
    global worker
    
    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    
    def shutdown_handler(sig):
        logger.info(f"Received signal {sig}, shutting down...")
        asyncio.create_task(stop_worker())
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: shutdown_handler(s))
    
    try:
        worker = await start_worker()
        
        # Keep running until stopped
        while worker and worker.isRunning():
            await asyncio.sleep(1)
            
    except Exception as e:
        logger.exception(f"Worker error: {e}")
        raise
    finally:
        await stop_worker()


if __name__ == "__main__":
    asyncio.run(main())