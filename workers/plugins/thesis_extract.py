"""Extract and index through the shared document service; no classification."""

from common.thesis_files import extract_file
from common.thesis_classifier import enqueue_classification

QUEUE_NAME = "thesis_extract"
QUEUE_TIMEOUT = 600


def handle(task_id, payload):
    result = extract_file(task_id, payload)
    if result.get("status") == "indexed":
        enqueue_classification(payload["project_id"], payload["file_id"], task_id)
    return result
