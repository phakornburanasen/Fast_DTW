# queue_manager.py — In-process asyncio job queue
from __future__ import annotations

import asyncio
import sys
import traceback
from dataclasses import dataclass

from schemas import TFRequest


# ---------------------------------------------------------------------------
# Queue + payload
# ---------------------------------------------------------------------------

job_queue: asyncio.Queue = asyncio.Queue()


@dataclass
class JobPayload:
    job_id: int
    request: TFRequest


# ---------------------------------------------------------------------------
# Producer
# ---------------------------------------------------------------------------

async def enqueue_job(job_id: int, request: TFRequest) -> None:
    """Put a JobPayload onto the queue."""
    await job_queue.put(JobPayload(job_id=job_id, request=request))


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------

async def worker_loop(tf_service_instance) -> None:  # type: ignore[type-arg]
    """Infinite loop: dequeue and process one job at a time."""
    print("[worker_loop] Started background job worker", flush=True)
    while True:
        payload: JobPayload = await job_queue.get()
        print(f"[worker_loop] Dequeued job {payload.job_id}", flush=True)
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                tf_service_instance.process_queued_job,
                payload.job_id,
                payload.request,
            )
            print(
                (
                    f"[worker_loop] Job {payload.job_id} finished: "
                    f"success={getattr(result, 'success', None)} "
                    f"message={getattr(result, 'message', '')}"
                ),
                flush=True,
            )
        except Exception as exc:
            print(f"[worker_loop] Unhandled error for job {payload.job_id}: {exc}",
                  file=sys.stderr)
            traceback.print_exc()
        finally:
            job_queue.task_done()


# ---------------------------------------------------------------------------
# Startup helper
# ---------------------------------------------------------------------------

def start_worker(app, tf_service_instance) -> None:  # type: ignore[type-arg]
    """Schedule the background worker as an asyncio task on app startup."""
    loop = asyncio.get_event_loop()
    task = loop.create_task(worker_loop(tf_service_instance))
    # Keep a reference on the app so the task is not garbage-collected.
    app.state.worker_task = task
    print("[worker_loop] Background worker scheduled", flush=True)
