"""Background job queue — Redis when configured, in-memory asyncio queue otherwise."""
import asyncio
import json
import logging
from datetime import datetime

from app.core.config import redis_configured, settings
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.workflow_engine import WorkflowJob, WorkflowRun

logger = logging.getLogger("job_queue")

_worker_task: asyncio.Task | None = None
_memory_queue: asyncio.Queue | None = None
_redis_client = None
_QUEUE_KEY = "coordination_engine:jobs"
_stats = {"enqueued": 0, "processed": 0, "failed": 0, "backend": "memory"}


async def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if not redis_configured():
        return None
    try:
        from redis.asyncio import Redis

        _redis_client = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        await asyncio.wait_for(_redis_client.ping(), timeout=3.0)
        _stats["backend"] = "redis"
        logger.info("Job queue connected to Redis.")
        return _redis_client
    except Exception as exc:
        logger.warning(f"Redis unavailable ({exc}) — using in-memory job queue.")
        if _redis_client is not None:
            try:
                await _redis_client.close()
            except Exception:
                pass
        _redis_client = None
        return None


async def enqueue(job_type: str, payload: dict) -> None:
    """Push a job onto the queue."""
    global _memory_queue
    job = {"type": job_type, "payload": payload, "enqueued_at": datetime.utcnow().isoformat()}
    _stats["enqueued"] += 1
    redis = await _get_redis()
    if redis:
        try:
            await redis.lpush(_QUEUE_KEY, json.dumps(job))
            return
        except Exception as exc:
            logger.warning(f"Redis enqueue failed ({exc}) — falling back to memory queue.")
    if _memory_queue is None:
        _memory_queue = asyncio.Queue()
        _stats["backend"] = "memory"
    await _memory_queue.put(job)


async def _dequeue() -> dict | None:
    redis = await _get_redis()
    if redis:
        try:
            item = await redis.brpop(_QUEUE_KEY, timeout=2)
            if item:
                _, raw = item
                return json.loads(raw)
        except Exception as exc:
            logger.warning(f"Redis dequeue failed ({exc}) — trying memory queue.")
    if _memory_queue is None:
        return None
    try:
        return await asyncio.wait_for(_memory_queue.get(), timeout=2.0)
    except asyncio.TimeoutError:
        return None


async def _process_workflow_start(payload: dict) -> None:
    from app.services import workflow_orchestrator_service as wf

    run_id = payload["run_id"]
    user_id = payload["user_id"]
    async with AsyncSessionLocal() as db:
        run = await db.get(WorkflowRun, run_id)
        user = await db.get(User, user_id)
        if not run or not user:
            return
        run.status = "running"
        run.updated_at = datetime.utcnow()
        db.add(run)
        await db.commit()
        await wf.run_workflow_advance(db, run, user)


async def _process_workflow_resume(payload: dict) -> None:
    from app.services import workflow_orchestrator_service as wf

    run_id = payload["run_id"]
    user_id = payload["user_id"]
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if not user:
            return
        await wf.resume_workflow_internal(db, user, run_id)


async def _handle_job(job: dict) -> None:
    job_type = job.get("type")
    payload = job.get("payload") or {}
    if job_type == "workflow_start":
        await _process_workflow_start(payload)
    elif job_type == "workflow_resume":
        await _process_workflow_resume(payload)
    else:
        logger.warning(f"Unknown job type: {job_type}")


async def _worker_loop() -> None:
    logger.info(f"Job queue worker started (backend={_stats['backend']}).")
    while True:
        try:
            job = await _dequeue()
            if not job:
                continue
            await _handle_job(job)
            _stats["processed"] += 1
        except asyncio.CancelledError:
            break
        except Exception as exc:
            _stats["failed"] += 1
            logger.warning(f"Job processing error (non-fatal): {exc}")


async def start_job_worker() -> None:
    global _worker_task, _memory_queue
    if not settings.JOB_QUEUE_ENABLED:
        logger.info("Job queue disabled (JOB_QUEUE_ENABLED=False).")
        return
    if _worker_task and not _worker_task.done():
        return
    redis = await _get_redis()
    if redis is None:
        _memory_queue = asyncio.Queue()
        _stats["backend"] = "memory"
    elif _memory_queue is None:
        _memory_queue = asyncio.Queue()
    _worker_task = asyncio.create_task(_worker_loop())


async def stop_job_worker() -> None:
    global _worker_task, _redis_client, _memory_queue
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    _worker_task = None
    _memory_queue = None
    if _redis_client:
        await _redis_client.close()
        _redis_client = None


def get_queue_stats() -> dict:
    pending = _memory_queue.qsize() if _memory_queue else None
    return {
        "enabled": settings.JOB_QUEUE_ENABLED,
        "backend": _stats["backend"],
        "redis_configured": redis_configured(),
        "worker_running": _worker_task is not None and not _worker_task.done(),
        "pending_memory_jobs": pending,
        "enqueued_total": _stats["enqueued"],
        "processed_total": _stats["processed"],
        "failed_total": _stats["failed"],
    }
