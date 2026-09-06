"""
fetch_jobs.py

Worker especializado en TRAER datos (llamadas a APIs externas, scraping,
lectura de ficheros...). Separado de "process" para que una tarea de red
lenta no bloquee el procesamiento pesado, y para poder escalar cada tipo
de trabajo por separado (ej. más workers de fetch si la red es el cuello
de botella, sin tocar los de process).

Arrancar este worker (procesa solo la cola "fetch"):
    rq worker fetch --url redis://127.0.0.1:6379/0
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.db import set_status  # noqa: E402
from common.logging_setup import get_logger  # noqa: E402

log = get_logger(__name__)


def fetch_task(task_id: str, source: str) -> dict:
    """
    Ejemplo: sustituye esto por la llamada real (HTTP request, lectura de
    un bucket, consulta a otro servicio...).
    """
    log.info(f"empezando, source={source}", extra={"task_id": task_id})
    set_status(task_id, "running", increment_attempts=True)
    try:
        # --- lógica real de "traer datos" iría aquí ---
        result = {"source": source, "fetched": True}
        set_status(task_id, "completed", result=result)
        log.info("completada", extra={"task_id": task_id})
        return result
    except Exception as e:
        set_status(task_id, "failed", error=str(e))
        log.error(f"fallida: {e}", extra={"task_id": task_id})
        raise  # RQ necesita el raise para contar el intento y decidir el retry
