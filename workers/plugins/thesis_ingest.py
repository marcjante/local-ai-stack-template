"""Dispatch extraction using the existing RQ/plugin protocol."""

from rq import Queue

from common.thesis_files import file_detail, fail_ingestion
from db.db import set_status
from workers.queue_conn import redis_conn, DEFAULT_RETRY

QUEUE_NAME = "thesis_ingest"
QUEUE_TIMEOUT = 300


def handle(task_id, payload):
    project_id, file_id = payload["project_id"], payload["file_id"]
    try:
        file = file_detail(project_id, file_id)
        if file["job_id"] != task_id or file["status"] == "indexed":
            return {"status": "already_handled"}
        set_status(task_id, "running", increment_attempts=True)
        Queue("thesis_extract", connection=redis_conn).enqueue(
            "workers.plugins.thesis_extract.handle", task_id, payload,
            job_id=task_id + "-extract", retry=DEFAULT_RETRY, job_timeout=600,
        )
        return {"status": "queued", "file_id": file_id}
    except Exception as exc:
        fail_ingestion(project_id, file_id, task_id, exc)
        raise
