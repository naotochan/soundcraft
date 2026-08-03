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

#: Finished generations retained in history before the oldest is dropped.
MAX_JOBS = 200

#: Maps an exception to ``(http_status, error_code)``.
Classifier = Callable[[Exception], tuple[int, str]]


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
    #: Machine-readable failure kind, so clients need not parse `error`.
    error_code: str | None = None
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
            "error_code": self.error_code,
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
        *,
        classify: Classifier | None = None,
    ) -> Job:
        """Register a job and run ``work(job)`` on a worker thread.

        ``classify`` turns an exception into ``(status, code)``; only the code is
        recorded, so callers can share one mapping with their HTTP layer.
        """
        job = Job(
            id=uuid.uuid4().hex[:12],
            status=JobStatus.queued,
            created_at=_now(),
            updated_at=_now(),
            request=request,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._evict_finished()

        self._pool.submit(self._run, job, work, classify)
        return job

    def _evict_finished(self) -> None:
        """Drop the oldest *finished* jobs. Callers hold the lock.

        A queued or running job must survive: dropping it would lose the only
        handle the client has on work that is still consuming resources.
        """
        if len(self._jobs) <= MAX_JOBS:
            return
        for job_id, job in list(self._jobs.items()):
            if len(self._jobs) <= MAX_JOBS:
                return
            if job.status in (JobStatus.succeeded, JobStatus.failed):
                del self._jobs[job_id]

    def _run(
        self,
        job: Job,
        work: Callable[[Job], dict[str, Any]],
        classify: Classifier | None,
    ) -> None:
        self._update(job.id, status=JobStatus.running)
        try:
            result = work(job)
        except Exception as e:  # Surfaced to the client as job.error.
            code = classify(e)[1] if classify else None
            self._update(
                job.id,
                status=JobStatus.failed,
                error=str(e) or type(e).__name__,
                error_code=code,
            )
        else:
            self._update(job.id, status=JobStatus.succeeded, result=result)

    def _update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            # `status` last: a client that polls until it sees "succeeded" must
            # never observe that status before `result` has been attached.
            status = fields.pop("status", None)
            for key, value in fields.items():
                setattr(job, key, value)
            job.updated_at = _now()
            if status is not None:
                job.status = status

    def set_progress(self, job_id: str, done: int, total: int) -> None:
        self._update(job_id, progress={"done": done, "total": total})

    def get(self, job_id: str) -> dict[str, Any] | None:
        """A consistent snapshot — serialised while holding the lock."""
        with self._lock:
            job = self._jobs.get(job_id)
            return job.as_dict() if job else None

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Newest first. Insertion order is creation order, so no sort key is
        needed — and isoformat() strings do not sort correctly anyway, since
        it omits `.ffffff` on a whole second."""
        with self._lock:
            jobs = list(self._jobs.values())[::-1]
            return [job.as_dict() for job in jobs[:limit]]

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
