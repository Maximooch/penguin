"""Temporal worker for ITUV activities.

The worker registers activities and handles their execution.
"""

import asyncio
import logging
import signal
from typing import Optional

logger = logging.getLogger(__name__)

# Check if temporalio is available
try:
    from temporalio.client import Client
    from temporalio.worker import Worker
    TEMPORAL_AVAILABLE = True
except ImportError:
    TEMPORAL_AVAILABLE = False
    Client = None
    Worker = None

from .activities import ACTIVITIES
from .workflows import ITUVWorkflow


class ITUVWorker:
    """Worker for executing ITUV workflow activities."""
    
    def __init__(
        self,
        client: "Client",
        task_queue: str = "penguin-ituv",
    ):
        """Initialize worker.
        
        Args:
            client: Temporal client instance.
            task_queue: Task queue name.
        """
        if not TEMPORAL_AVAILABLE:
            raise ImportError(
                "temporalio package not installed. "
                "Install with: pip install temporalio"
            )
        
        self.client = client
        self.task_queue = task_queue
        self._worker: Optional[Worker] = None
        self._running = False
    
    async def start(self) -> None:
        """Start the worker."""
        if self._running:
            return
        
        self._worker = Worker(
            self.client,
            task_queue=self.task_queue,
            workflows=[ITUVWorkflow],
            activities=ACTIVITIES,
        )
        
        self._running = True
        logger.info(f"Starting ITUV worker on task queue: {self.task_queue}")
        
        # Run worker
        await self._worker.run()
    
    async def stop(self) -> None:
        """Stop the worker gracefully."""
        if not self._running:
            return
        
        self._running = False
        
        if self._worker:
            # Worker will stop after completing current activities
            logger.info("Stopping ITUV worker...")
    
    @property
    def running(self) -> bool:
        """Check if worker is running."""
        return self._running


async def run_worker(
    address: str = "localhost:7233",
    namespace: str = "penguin",
    task_queue: str = "penguin-ituv",
) -> None:
    """Run the ITUV worker.
    
    This is a standalone function for running the worker as a separate process.
    
    Args:
        address: Temporal server address.
        namespace: Temporal namespace.
        task_queue: Task queue name.
    """
    if not TEMPORAL_AVAILABLE:
        raise ImportError(
            "temporalio package not installed. "
            "Install with: pip install temporalio"
        )
    
    # Connect to Temporal
    client = await Client.connect(address, namespace=namespace)
    
    # Create worker
    worker = ITUVWorker(client, task_queue)
    
    # Handle shutdown signals
    shutdown_event = asyncio.Event()
    
    def handle_shutdown(sig):
        logger.info(f"Received signal {sig}, shutting down...")
        shutdown_event.set()
    
    # Register signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: handle_shutdown(s))
    
    # Start worker in background
    worker_task = asyncio.create_task(worker.start())
    
    # Wait for shutdown
    await shutdown_event.wait()
    
    # Stop worker
    await worker.stop()
    worker_task.cancel()
    
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    
    logger.info("Worker stopped")


# CLI entry point
def main():
    """CLI entry point for running the worker."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run ITUV Temporal worker")
    parser.add_argument(
        "--address",
        default="localhost:7233",
        help="Temporal server address",
    )
    parser.add_argument(
        "--namespace",
        default="penguin",
        help="Temporal namespace",
    )
    parser.add_argument(
        "--task-queue",
        default="penguin-ituv",
        help="Task queue name",
    )
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    asyncio.run(run_worker(
        address=args.address,
        namespace=args.namespace,
        task_queue=args.task_queue,
    ))


if __name__ == "__main__":
    main()

