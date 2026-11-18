import asyncio
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from app.core.config import settings

QuoteFn = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]] | Dict[str, Any]]


class JobQueueFull(Exception):
    pass


class JobManager:
    def __init__(self, maxsize: int | None = None):
        self.maxsize = int(maxsize if maxsize is not None else settings.INGEST_QUEUE_MAX)
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self.maxsize)
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self._running = False

    def enqueue(self, events: List[Dict[str, Any]]) -> str:
        job_id = str(uuid.uuid4())
        self.jobs[job_id] = {"job_id": job_id, "status": "queued", "events": events}
        try:
            self.queue.put_nowait(job_id)
        except asyncio.QueueFull:
            self.jobs.pop(job_id, None)
            raise JobQueueFull("ingest queue is full")
        return job_id

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        payload = {
            "job_id": job["job_id"],
            "status": job["status"],
        }
        if "results" in job:
            payload["results"] = job["results"]
            payload["count"] = len(job["results"])
        if "error" in job:
            payload["error"] = job["error"]
        return payload

    async def run_worker(self, quote_fn: QuoteFn) -> None:
        self._running = True
        while self._running:
            job_id = await self.queue.get()
            job = self.jobs[job_id]
            job["status"] = "running"
            try:
                results = []
                for event in job["events"]:
                    results.append(await asyncio.to_thread(quote_fn, event))
                job["results"] = results
                job["status"] = "done"
            except Exception as exc:
                job["status"] = "failed"
                job["error"] = str(exc)
            finally:
                job.pop("events", None)
                self.queue.task_done()

    def stop(self) -> None:
        self._running = False
