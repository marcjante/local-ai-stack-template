from common.thesis_overlap import check_version
from db.db import set_status

QUEUE_NAME = "thesis_check_overlap"
QUEUE_TIMEOUT = 300


def handle(task_id, payload):
    set_status(task_id, "running", increment_attempts=True)
    try:
        result = check_version(payload["project_id"], payload["version_id"], payload.get("checked_by"))
        set_status(task_id, "completed", result=result)
        return result
    except Exception as exc:
        set_status(task_id, "failed", error=str(exc)); raise
