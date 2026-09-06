"""
n8n_client.py

Dirección worker → n8n: cuando un subagente necesita que pase algo fuera
del stack de Python (mandar un email, escribir en una hoja de cálculo,
avisar a Slack, guardar en un sistema externo...), no lo hace él mismo:
dispara un webhook de n8n y deja que el flujo se encargue.

La otra dirección (n8n → worker) vive en backend/main.py, en el endpoint
/webhooks/n8n/<queue>.
"""

import os
import requests

from common.logging_setup import get_logger
from db.db import is_integration_enabled

N8N_BASE_URL = os.environ.get("N8N_BASE_URL", "http://127.0.0.1:5678")
N8N_OUTBOUND_TOKEN = os.environ.get("N8N_OUTBOUND_TOKEN", "")

log = get_logger(__name__)


def trigger_n8n_flow(flow_path: str, payload: dict, task_id: str = None, project_id: str = "default", timeout: float = 10) -> dict:
    """
    Llama a un webhook de n8n (Webhook node) y devuelve su respuesta.
    flow_path es la parte final de la URL configurada en el nodo Webhook
    de n8n, ej. "notificar-resultado" -> POST {N8N_BASE_URL}/webhook/notificar-resultado

    Antes de llamar, comprueba si la integración está ACTIVADA PARA ESE
    PROYECTO (tabla n8n_integrations, gestionable desde /integrations en
    el backend). Si está desactivada, no hace la llamada HTTP en absoluto
    y lo deja registrado como 'omitido' — el proyecto puede apagar un
    flujo sin tocar código ni reiniciar nada, y sin afectar a otros
    proyectos que sí lo tengan activado.

    No lanza excepción si n8n no responde: un fallo en la notificación no
    debería tumbar la tarea principal — se registra y se sigue.
    """
    if not is_integration_enabled(flow_path, project_id=project_id):
        log.info(f"n8n flow '{flow_path}' desactivado para el proyecto '{project_id}', se omite", extra={"task_id": task_id})
        return {"ok": False, "skipped": True, "reason": "integración desactivada"}

    url = f"{N8N_BASE_URL}/webhook/{flow_path}"
    headers = {"Content-Type": "application/json"}
    if N8N_OUTBOUND_TOKEN:
        headers["Authorization"] = f"Bearer {N8N_OUTBOUND_TOKEN}"

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        log.info(f"n8n flow '{flow_path}' OK", extra={"task_id": task_id})
        try:
            return {"ok": True, "response": resp.json()}
        except ValueError:
            return {"ok": True, "response": resp.text}
    except requests.RequestException as e:
        log.error(f"n8n flow '{flow_path}' falló: {e}", extra={"task_id": task_id})
        return {"ok": False, "error": str(e)}
