from common.thesis_generation import generate_chapter
from db.db import set_status

QUEUE_NAME = "thesis_generate"
QUEUE_TIMEOUT = 300


def handle(task_id, payload):
    set_status(task_id, "running", increment_attempts=True)
    try:
        result = generate_chapter(payload["project_id"], payload["chapter_id"], payload.get("instructions", ""))
        set_status(task_id, "completed", result=result)
        return result
    except Exception as exc:
        set_status(task_id, "failed", error=str(exc)); raise
