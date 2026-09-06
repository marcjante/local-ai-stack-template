"""
process_jobs.py

Worker especializado en PROCESAR (la parte pesada: llamadas al LLM vía el
gateway, cálculo, transformación de datos ya obtenidos por "fetch").

Separarlo de "fetch" y "notify" es justo el cambio pedido en el roadmap:
en vez de 3 workers idénticos que podían acabar todos llamando al LLM sin
control, solo este worker lo hace, y siempre a través de llm_gateway
(que limita cuántas llamadas concurrentes llegan a Ollama).

Arrancar este worker (procesa solo la cola "process"):
    rq worker process --url redis://127.0.0.1:6379/0
"""

import sys
import os
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.db import set_status  # noqa: E402
from common.logging_setup import get_logger  # noqa: E402

LLM_GATEWAY_URL = os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1:8091")
log = get_logger(__name__)


def process_task(task_id: str, payload: dict) -> dict:
    log.info("empezando", extra={"task_id": task_id})
    set_status(task_id, "running", increment_attempts=True)
    try:
        # Ejemplo: pide al gateway (no a Ollama directamente) que genere algo.
        # El gateway es quien controla cuántas llamadas concurrentes acepta.
        resp = requests.post(
            f"{LLM_GATEWAY_URL}/generate",
            json={"prompt": payload.get("prompt", "")},
            timeout=90,
        )
        resp.raise_for_status()
        result = resp.json()
        set_status(task_id, "completed", result=result)
        log.info("completada", extra={"task_id": task_id})
        return result
    except Exception as e:
        set_status(task_id, "failed", error=str(e))
        log.error(f"fallida: {e}", extra={"task_id": task_id})
        raise
