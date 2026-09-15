"""Classify Thesis fragment roles and content types after extraction."""

from common.thesis_classifier import classify_file
from common.thesis_placements import generate_for_file
from db.db import set_status

QUEUE_NAME = "thesis_classify"
QUEUE_TIMEOUT = 300


def handle(task_id, payload):
    set_status(task_id, "running", increment_attempts=True)
    try:
        result = classify_file(payload["project_id"], payload["file_id"])
        placement_result = generate_for_file(payload["project_id"], payload["file_id"])
        result["placement"] = placement_result
        set_status(task_id, "completed", result=result)
        return result
    except Exception as exc:
        set_status(task_id, "failed", error=str(exc))
        raise
