from common.thesis_generation import verify_version
from db.db import set_status

QUEUE_NAME = "thesis_verify"
QUEUE_TIMEOUT = 300


def handle(task_id, payload):
    set_status(task_id, "running", increment_attempts=True)
    try:
        result = verify_version(payload["project_id"], payload["version_id"])
        set_status(task_id, "completed", result=result)
        return result
    except Exception as exc:
        set_status(task_id, "failed", error=str(exc)); raise
