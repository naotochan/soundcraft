"""In-memory job queue for asynchronous generation.

Kept deliberately small: generation is slow and IO-bound, so a bounded thread
pool plus a dict of job records covers every supported deployment without
dragging in a broker.
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

#: Generations retained in history before the oldest is dropped.
MAX_JOBS = 200


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


@dataclass
class Job:
    id: str
    status: JobStatus
    created_at: str
    request: dict[str, Any]
    updated_at: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None
    progress: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at or self.created_at,
            "request": self.request,
            "result": self.result,
            "error": self.error,
            "progress": self.progress,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobQueue:
    """Thread-safe job store with a bounded worker pool."""

    def __init__(self, max_workers: int = 2) -> None:
        self._lock = threading.Lock()
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="soundcraft-job"
        )

    def submit(
        self,
        request: dict[str, Any],
        work: Callable[[Job], dict[str, Any]],
    ) -> Job:
        """Register a job and run ``work(job)`` on a worker thread."""
        job = Job(
            id=uuid.uuid4().hex[:12],
            status=JobStatus.queued,
            created_at=_now(),
            updated_at=_now(),
            request=request,
        )
        with self._lock:
            self._jobs[job.id] = job
            while len(self._jobs) > MAX_JOBS:
                self._jobs.popitem(last=False)

        self._pool.submit(self._run, job, work)
        return job

    def _run(self, job: Job, work: Callable[[Job], dict[str, Any]]) -> None:
        self._update(job.id, status=JobStatus.running)
        try:
            result = work(job)
        except Exception as e:  # Surfaced to the client as job.error.
            self._update(job.id, status=JobStatus.failed, error=str(e) or type(e).__name__)
        else:
            self._update(job.id, status=JobStatus.succeeded, result=result)

    def _update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in fields.items():
                setattr(job, key, value)
            job.updated_at = _now()

    def set_progress(self, job_id: str, done: int, total: int) -> None:
        self._update(job_id, progress={"done": done, "total": total})

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, limit: int = 50) -> list[Job]:
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
