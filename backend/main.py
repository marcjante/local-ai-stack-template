"""
main.py — Backend API

Responsabilidades:
  - Autenticar peticiones (API key simple; cambia a JWT si el proyecto
    lo necesita, el punto de enganche es require_api_key()).
  - Encolar tareas en la cola especializada que corresponda (fetch/process/notify),
    en vez de una única cola genérica.
  - Exponer /health, /ready y /metrics reales (no solo "el proceso vive").
  - Dar de alta cada tarea en Postgres con estado 'pending' y dejar que los
    workers la vayan actualizando (running/completed/failed).
  - Exponer /tasks/<id>/stream (Server-Sent Events) para no depender de
    hacer polling manual a /tasks/<id>.

Arrancar: python3 backend/main.py
"""

import os
import sys
import time
import uuid
import functools

from flask import Flask, request, jsonify, Response, stream_with_context

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.db import init_schema, create_task, get_task, get_audit_trail  # noqa: E402
from workers.queue_conn import QUEUES_BY_NAME, DEFAULT_RETRY, redis_conn  # noqa: E402
from workers.fetch_jobs import fetch_task  # noqa: E402
from workers.process_jobs import process_task  # noqa: E402
from workers.notify_jobs import notify_task  # noqa: E402

API_KEY = os.environ.get("API_KEY", "changeme-in-.env")
N8N_INBOUND_SECRET = os.environ.get("N8N_INBOUND_SECRET", "changeme-in-.env")

app = Flask(__name__)


def require_api_key(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        provided = request.headers.get("X-API-Key")
        if provided != API_KEY:
            return jsonify({"error": "API key inválida o ausente (cabecera X-API-Key)"}), 401
        return fn(*args, **kwargs)
    return wrapper


def require_n8n_secret(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        provided = request.headers.get("X-N8N-Secret")
        if provided != N8N_INBOUND_SECRET:
            return jsonify({"error": "secreto inválido o ausente (cabecera X-N8N-Secret)"}), 401
        return fn(*args, **kwargs)
    return wrapper


JOB_FUNCS = {
    "fetch": fetch_task,
    "process": process_task,
    "notify": notify_task,
}


@app.route("/health")
def health():
    """Vivo: el proceso responde. No implica que sus dependencias estén bien."""
    return jsonify({"status": "ok"})


@app.route("/ready")
def ready():
    """Listo de verdad: Redis y Postgres responden."""
    checks = {}
    try:
        redis_conn.ping()
        checks["redis"] = True
    except Exception as e:
        checks["redis"] = False
        checks["redis_error"] = str(e)

    try:
        get_task("__healthcheck__")  # solo comprueba que la conexión/consulta funciona
        checks["postgres"] = True
    except Exception as e:
        checks["postgres"] = False
        checks["postgres_error"] = str(e)

    all_ok = checks.get("redis") and checks.get("postgres")
    return jsonify(checks), (200 if all_ok else 503)


@app.route("/metrics")
def metrics():
    depths = {name: len(q) for name, q in QUEUES_BY_NAME.items()}
    return jsonify({"queue_depth": depths})


@app.route("/enqueue/<queue_name>", methods=["POST"])
@require_api_key
def enqueue(queue_name):
    payload = request.get_json(force=True) or {}
    result, status = _do_enqueue(queue_name, payload)
    return jsonify(result), status


@app.route("/webhooks/n8n/<queue_name>", methods=["POST"])
@require_n8n_secret
def n8n_webhook(queue_name):
    """
    Dirección n8n → worker: un flujo de n8n puede llamar aquí (nodo HTTP
    Request apuntando a esta URL, con la cabecera X-N8N-Secret) para
    disparar una tarea, igual que haría el backend por su cuenta.
    """
    payload = request.get_json(force=True) or {}
    result, status = _do_enqueue(queue_name, payload)
    return jsonify(result), status


def _do_enqueue(queue_name: str, payload: dict):
    if queue_name not in QUEUES_BY_NAME:
        return {"error": f"cola desconocida '{queue_name}'", "colas_validas": list(QUEUES_BY_NAME)}, 400

    task_id = str(uuid.uuid4())
    create_task(task_id, queue_name, payload)

    queue = QUEUES_BY_NAME[queue_name]
    job_fn = JOB_FUNCS[queue_name]
    queue.enqueue(job_fn, task_id, payload, retry=DEFAULT_RETRY, job_id=task_id)

    return {"task_id": task_id, "queue": queue_name, "status": "pending"}, 202


@app.route("/tasks/<task_id>")
@require_api_key
def task_status(task_id):
    task = get_task(task_id)
    if not task:
        return jsonify({"error": "tarea no encontrada"}), 404
    return jsonify(task)


@app.route("/tasks/<task_id>/audit")
@require_api_key
def task_audit(task_id):
    """
    Traza completa del 'circuito de información veraz': qué subagente
    actuó en cada paso, qué veredicto dio y con qué confianza.
    """
    trail = get_audit_trail(task_id)
    return jsonify(trail)


@app.route("/tasks/<task_id>/stream")
@require_api_key
def task_stream(task_id):
    """
    Server-Sent Events: el cliente abre esta conexión una vez y recibe un
    evento cada vez que cambia el estado, en vez de hacer polling manual
    a /tasks/<id> cada X segundos.
    """
    def event_source():
        last_status = None
        for _ in range(120):  # ~2 minutos de margen; ajusta según el proyecto
            task = get_task(task_id)
            if task and task["status"] != last_status:
                last_status = task["status"]
                yield f"data: {task['status']}\n\n"
                if task["status"] in ("completed", "failed"):
                    return
            time.sleep(1)
        yield "event: timeout\ndata: se agotó la espera\n\n"

    return Response(stream_with_context(event_source()), mimetype="text/event-stream")


if __name__ == "__main__":
    init_schema()
    app.run(host="0.0.0.0", port=8080)
