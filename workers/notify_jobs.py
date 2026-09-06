"""
notify_jobs.py

Worker especializado en AVISAR cuando algo termina (webhook al cliente,
email, publicar en un websocket/SSE...). Deliberadamente ligero y con
timeout corto: no debería competir por recursos con "process".

Arrancar este worker (procesa solo la cola "notify"):
    rq worker notify --url redis://127.0.0.1:6379/0
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.db import get_task  # noqa: E402


def notify_task(task_id: str, payload: dict) -> dict:
    """
    Ejemplo: sustituye esto por el envío real (POST a webhook_url,
    publicar en el canal SSE/WebSocket del backend, etc.)
    """
    webhook_url = payload.get("webhook_url")
    task = get_task(task_id)
    if webhook_url:
        # --- POST real al webhook_url con el resultado de `task` iría aquí ---
        pass
    return {"notified": True, "task_status": task["status"] if task else "unknown"}
