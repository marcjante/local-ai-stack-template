"""Generate chapter placement suggestions after fragment classification."""

from common.thesis_placements import generate_for_file
from db.db import set_status

QUEUE_NAME = "thesis_place"
QUEUE_TIMEOUT = 300


def handle(task_id, payload):
    set_status(task_id, "running", increment_attempts=True)
    try:
        result = generate_for_file(payload["project_id"], payload["file_id"])
        set_status(task_id, "completed", result=result)
        return result
    except Exception as exc:
        set_status(task_id, "failed", error=str(exc))
        raise
