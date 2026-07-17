"""
Background task queue for CPU-intensive AI processing.
Decouples request handling from heavy computation.
"""
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger(__name__)


class TaskPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BackgroundTask:
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    payload: dict = field(default_factory=dict)
    result: Any = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    retries: int = 0
    max_retries: int = 3

    @property
    def duration(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return round(self.completed_at - self.started_at, 3)
        return None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "status": self.status.value,
            "priority": self.priority.value,
            "payload": self.payload,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration": self.duration,
            "retries": self.retries,
        }


class TaskQueue:
    """Async task queue with priority support and worker pool."""

    def __init__(self, max_workers: int = 4, max_queue_size: int = 256):
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=max_queue_size)
        self._max_workers = max_workers
        self._workers: list[asyncio.Task] = []
        self._handlers: dict[str, Callable[..., Coroutine]] = {}
        self._running_tasks: dict[str, BackgroundTask] = {}
        self._completed_tasks: list[dict] = []
        self._max_completed = 500
        self._is_running = False
        self._total_processed = 0
        self._total_failed = 0

    def register_handler(self, task_name: str, handler: Callable[..., Coroutine]):
        """Register an async handler for a task type."""
        self._handlers[task_name] = handler
        logger.debug("Registered handler for task: %s", task_name)

    async def start(self):
        """Start worker pool."""
        if self._is_running:
            return
        self._is_running = True
        for i in range(self._max_workers):
            worker = asyncio.create_task(self._worker(f"worker-{i}"))
            self._workers.append(worker)
        logger.info("Task queue started with %d workers", self._max_workers)

    async def stop(self):
        """Gracefully stop all workers."""
        self._is_running = False
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("Task queue stopped")

    async def submit(
        self,
        task_name: str,
        payload: dict | None = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        max_retries: int = 3,
    ) -> BackgroundTask:
        """Submit a task to the queue."""
        task = BackgroundTask(
            name=task_name,
            priority=priority,
            payload=payload or {},
            max_retries=max_retries,
        )
        await self._queue.put((-priority.value, task.created_at, task))
        logger.debug("Task submitted: %s (%s)", task.task_id, task_name)
        return task

    async def _worker(self, worker_id: str):
        """Worker coroutine that processes tasks from the queue."""
        while self._is_running:
            try:
                _, _, task = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            if task.name not in self._handlers:
                task.status = TaskStatus.FAILED
                task.error = f"No handler registered for: {task.name}"
                task.completed_at = time.time()
                self._record_completed(task)
                logger.warning("No handler for task: %s", task.name)
                continue

            task.status = TaskStatus.RUNNING
            task.started_at = time.time()
            self._running_tasks[task.task_id] = task

            try:
                handler = self._handlers[task.name]
                task.result = await handler(task.payload)
                task.status = TaskStatus.COMPLETED
                task.completed_at = time.time()
                self._total_processed += 1
                logger.debug("Task completed: %s in %.3fs", task.task_id, task.duration)
            except Exception as e:
                task.error = str(e)
                if task.retries < task.max_retries:
                    task.retries += 1
                    task.status = TaskStatus.PENDING
                    task.started_at = None
                    await self._queue.put((-task.priority.value, task.created_at, task))
                    logger.warning("Task retry %d/%d: %s", task.retries, task.max_retries, task.task_id)
                    continue
                task.status = TaskStatus.FAILED
                task.completed_at = time.time()
                self._total_failed += 1
                logger.error("Task failed: %s — %s", task.task_id, e)
            finally:
                self._running_tasks.pop(task.task_id, None)
                self._record_completed(task)

    def _record_completed(self, task: BackgroundTask):
        self._completed_tasks.append(task.to_dict())
        if len(self._completed_tasks) > self._max_completed:
            self._completed_tasks = self._completed_tasks[-self._max_completed:]

    def get_status(self) -> dict:
        return {
            "is_running": self._is_running,
            "queue_size": self._queue.qsize(),
            "running_count": len(self._running_tasks),
            "running_tasks": [t.to_dict() for t in self._running_tasks.values()],
            "total_processed": self._total_processed,
            "total_failed": self._total_failed,
            "recent_completed": self._completed_tasks[-20:],
            "registered_handlers": list(self._handlers.keys()),
        }


task_queue = TaskQueue(max_workers=4, max_queue_size=256)
