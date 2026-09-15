"""
dashboard_service.py

Panel de control genérico para el stack local. Añade, sobre la versión
anterior:

  - Control de Docker por servicio (start/stop/restart vía `docker compose`),
    además del arranque nativo que ya había. Si Docker no está instalado o
    el servicio no tiene equivalente en docker-compose.yml, lo dice
    claramente en vez de fallar en silencio.
  - Logs en vivo por servicio vía Server-Sent Events: los procesos nativos
    escriben en logs/<id>.log (redirigidos aquí mismo al arrancarlos);
    los servicios en Docker se leen con `docker compose logs -f`.
  - Salud real (HTTP) + CPU/RAM + profundidad de colas, como ya había.

Nota: este panel asume que se ejecuta de forma NATIVA en la máquina que
tiene Docker (no dentro de un contenedor) — así puede llamar a `docker
compose` como cualquier otro comando del host. Si metes el propio
dashboard dentro de un contenedor, necesitarás montar el socket de Docker
y añadir el cliente `docker` a esa imagen (no incluido a propósito, para
no complicar la plantilla con docker-in-docker si no hace falta).
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psutil
import requests
import yaml
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, Response, stream_with_context, redirect, send_file, session

BASE_DIR = Path(__file__).resolve().parent.parent

# Carga la configuración local antes de importar módulos que leen
# variables de entorno como DATABASE_URL o REDIS_URL.
load_dotenv(BASE_DIR / ".env")

sys.path.insert(0, str(BASE_DIR))
from db.db import (
    list_tasks,
    task_counts_by_status,
    create_task,
    get_task,
)  # noqa: E402
sys.path.insert(0, str(BASE_DIR))
from db.db import list_integrations, set_integration_enabled, get_audit_trail  # noqa: E402
from workers.plugin_loader import discover_plugins  # noqa: E402
from workers.queue_conn import redis_conn, DEFAULT_RETRY  # noqa: E402
from rq import Queue  # noqa: E402
from rag.retrieval import index_document, retrieve  # noqa: E402
from rag.rerank import rerank  # noqa: E402
from rag.citations import format_citations  # noqa: E402
from db.db import get_conn  # noqa: E402
from db.db import (  # noqa: E402
    ensure_default_collection, create_collection, list_collections,
    register_document, list_documents, get_document, delete_document, get_document_chunks,
)
from rag.file_parsers import (
    extract_text,
    extract_structured_text,
)  # noqa: E402
from rag.chunking import split_into_chunks  # noqa: E402
from rag.embeddings import embed_text  # noqa: E402
from rag.vector_store import add_chunks as vs_add_chunks  # noqa: E402
from common.backup import export_backup, import_backup  # noqa: E402
from db.db import (  # noqa: E402
    create_project, list_projects, get_project, get_project_settings,
    update_project_settings, project_recent_errors, list_evaluations, get_latest_evaluation,
)

from common.system_checks import run_all_checks, pull_recommended_model  # noqa: E402
from common.diagnostics import run_diagnostics  # noqa: E402
from common import thesis_files, thesis_service, thesis_placements  # noqa: E402

SETUP_STATE_PATH = BASE_DIR / "data" / "setup_state.json"


def is_onboarding_complete():
    if not SETUP_STATE_PATH.exists():
        return False
    try:
        return json.loads(SETUP_STATE_PATH.read_text()).get("completed", False)
    except (json.JSONDecodeError, OSError):
        return False


def save_setup_state(mode):
    SETUP_STATE_PATH.parent.mkdir(exist_ok=True)
    SETUP_STATE_PATH.write_text(json.dumps({"completed": True, "mode": mode}))

CONFIG_PATH = BASE_DIR / "config" / "services.yaml"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

app = Flask(__name__, template_folder="templates")
app.secret_key = os.environ.get("DASHBOARD_SECRET_KEY", "dev-only-change-in-prod")

PROJECT_TEMPLATES = {
    "blank": {"label": "Blank project", "system_prompt": ""},
    "rag_qa": {"label": "RAG / Document Q&A", "system_prompt": "Responde solo con lo que digan los documentos indexados, citando la fuente."},
    "research": {"label": "Research assistant", "system_prompt": "Eres un asistente de investigación. Sintetiza y contrasta fuentes."},
    "support": {"label": "Customer support", "system_prompt": "Responde de forma breve y orientada a resolver el problema del cliente."},
    "clinical": {"label": "Clinical/health project", "system_prompt": "Responde con precisión clínica, citando siempre la fuente, y deja claro cuándo la información no es concluyente."},
    "kb": {"label": "Knowledge base", "system_prompt": "Actúa como una base de conocimiento interna: respuestas concisas con referencia al documento de origen."},
    "doc_analysis": {"label": "Document analysis", "system_prompt": "Analiza el documento indicado y extrae los puntos clave solicitados."},
    "agent": {"label": "Agent workflow", "system_prompt": "Actúa como agente autónomo: decide qué pasos seguir para completar la tarea."},
}


def current_project_id() -> str:
    return session.get("project_id", "default")


def _review_in_current_project(review_id: str) -> bool:
    """Comprueba que la revisión pertenece al proyecto activo."""
    if not review_id:
        return False

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM systematic_reviews
            WHERE id = %s
              AND project_id = %s
            """,
            (review_id, current_project_id()),
        )
        return cur.fetchone() is not None


def _article_in_current_project(
    article_id: str,
    review_id: str,
) -> bool:
    """Comprueba artículo + revisión + proyecto activo."""
    if not article_id or not review_id:
        return False

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM review_articles ra
            JOIN systematic_reviews sr
              ON sr.id = ra.review_id
            WHERE ra.id = %s
              AND ra.review_id = %s
              AND sr.project_id = %s
            """,
            (
                article_id,
                review_id,
                current_project_id(),
            ),
        )
        return cur.fetchone() is not None


def _extraction_in_current_project(extraction_id: str) -> bool:
    """Comprueba que una extracción pertenece al proyecto activo."""
    if not extraction_id:
        return False

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM review_extractions re
            JOIN systematic_reviews sr
              ON sr.id = re.review_id
            WHERE re.id = %s
              AND sr.project_id = %s
            """,
            (
                extraction_id,
                current_project_id(),
            ),
        )
        return cur.fetchone() is not None


@app.route("/projects")
def projects_page():
    installed_models, _ = list_installed()
    return render_template("projects.html", page="projects", projects=list_projects(),
                            templates=PROJECT_TEMPLATES, current_project=current_project_id(),
                            installed_models=[m["name"] for m in installed_models])


@app.route("/projects/<project_id>/select", methods=["POST"])
def projects_select(project_id):
    if not get_project(project_id):
        return jsonify({"error": "proyecto desconocido"}), 404
    session["project_id"] = project_id
    return jsonify({"selected": project_id})


@app.route("/api/projects", methods=["POST"])
def projects_create():
    payload = request.get_json(force=True) or {}
    name = payload.get("name", "").strip()
    template = payload.get("template", "blank")
    if not name:
        return jsonify({"error": "el nombre es obligatorio"}), 400
    if template not in PROJECT_TEMPLATES:
        return jsonify({"error": f"plantilla desconocida '{template}'"}), 400
    project_id = payload.get("id") or name.lower().replace(" ", "-")
    create_project(project_id, name, payload.get("description"), template)
    settings_update = {"system_prompt": PROJECT_TEMPLATES[template]["system_prompt"]}
    if payload.get("model"):
        settings_update["default_model"] = payload["model"]
    update_project_settings(project_id, **settings_update)
    ensure_default_collection(project_id=project_id)
    return jsonify({"id": project_id, "name": name}), 201


@app.route("/projects/<project_id>")
def project_dashboard_page(project_id):
    project = get_project(project_id)
    if not project:
        return "Proyecto no encontrado", 404
    settings = get_project_settings(project_id)
    docs = list_documents(project_id=project_id)
    n_chunks = sum(d["n_chunks"] for d in docs)
    task_counts = task_counts_by_status(project_id=project_id)
    errors = project_recent_errors(project_id)
    latest_eval = get_latest_evaluation(project_id)
    return render_template(
        "project_dashboard.html", page="project_dashboard", project=project, settings=settings,
        n_documents=len(docs), n_chunks=n_chunks, task_counts=task_counts, recent_errors=errors,
        latest_eval=latest_eval, eval_history=list_evaluations(project_id, limit=10),
    )


@app.route("/api/projects/<project_id>/settings", methods=["POST"])
def project_settings_save(project_id):
    if not get_project(project_id):
        return jsonify({"error": "proyecto desconocido"}), 404
    payload = request.get_json(force=True) or {}
    allowed = {"default_model", "fallback_model", "embedding_model", "system_prompt",
               "temperature", "top_k", "chunk_size", "chunk_overlap"}
    fields = {k: v for k, v in payload.items() if k in allowed}
    if not fields:
        return jsonify({"error": "nada que guardar"}), 400
    update_project_settings(project_id, **fields)
    return jsonify({"saved": True})


from common.project_export import export_project, import_project  # noqa: E402
from common.systematic_review_export import export_systematic_review_xlsx  # noqa: E402


@app.route("/api/projects/<project_id>/export")
def project_export_route(project_id):
    if not get_project(project_id):
        return jsonify({"error": "proyecto desconocido"}), 404
    try:
        zip_path = export_project(project_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return send_file(zip_path, as_attachment=True, download_name=zip_path.name)



@app.route("/api/systematic-review/<review_id>/export.xlsx")
def systematic_review_export_xlsx(review_id):
    project_id = current_project_id()

    try:
        xlsx_path = export_systematic_review_xlsx(
            review_id=review_id,
            project_id=project_id,
        )
    except ValueError as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 404
    except Exception as exc:
        app.logger.exception(
            "Error exporting systematic review %s",
            review_id,
        )
        return jsonify({
            "ok": False,
            "error": f"Error generando Excel: {exc}",
        }), 500

    return send_file(
        xlsx_path,
        as_attachment=True,
        download_name=f"systematic-review-{review_id}.xlsx",
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
    )


@app.route("/api/projects/import", methods=["POST"])
def project_import_route():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "no se ha recibido ningún fichero"}), 400
    new_id = request.form.get("new_project_id") or None
    include_docs = request.form.get("include_documents", "true") == "true"
    try:
        result = import_project(file, new_project_id=new_id, include_documents=include_docs)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result), 201

# PIDs de los procesos nativos que este panel ha arrancado, para poder
# darles CPU/RAM reales (no de la máquina entera) al pulsar en la tarjeta.
# Se pierde si el panel se reinicia — es una cache en memoria, no un
# registro persistente; para procesos arrancados fuera del panel no hay
# forma de saber su PID sin más información (por diseño, para no andar
# escaneando todos los procesos del sistema por nombre).
_started_pids = {}

# Puerto real usado por el dashboard en esta ejecución.
# Se asigna al arrancar la aplicación y permite que los health-checks
# no dependan del puerto estático definido en services.yaml.
DASHBOARD_RUNTIME_PORT = None


def load_services():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    services = data.get("services", [])

    # No modificamos services.yaml en disco. Solo ajustamos en memoria
    # el servicio dashboard al puerto real elegido en esta ejecución.
    if DASHBOARD_RUNTIME_PORT is not None:
        for service in services:
            if service.get("id") == "dashboard":
                service["port"] = DASHBOARD_RUNTIME_PORT
                break

    return services


def get_service(service_id):
    return next((s for s in load_services() if s["id"] == service_id), None)


def port_is_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_health_ok(host: str, port: int, endpoint: str, timeout: float = 1.5) -> bool:
    try:
        r = requests.get(f"http://{host}:{port}{endpoint}", timeout=timeout)
        return r.status_code < 400
    except requests.RequestException:
        return False


def status_for(service: dict) -> dict:
    endpoint = service.get("health_endpoint")
    port = service.get("port")

    # El dashboard no necesita hacerse un HTTP health-check a sí mismo.
    # Si esta función está renderizando el panel y tenemos un puerto
    # runtime asignado, el servicio dashboard está necesariamente activo.
    if service.get("id") == "dashboard" and DASHBOARD_RUNTIME_PORT is not None:
        check_type = "self"
        status = "up"
    elif endpoint and port:
        up = http_health_ok(service["host"], port, endpoint)
        check_type = "http"
        status = "up" if up else "down"
    elif port:
        up = port_is_open(service["host"], port)
        check_type = "port"
        status = "up" if up else "down"
    else:
        check_type = "n/a"
        status = "unknown"

    return {
        "id": service["id"],
        "name": service["name"],
        "description": service.get("description", ""),
        "port": port,
        "status": status,
        "check_type": check_type,
        "docker_service": service.get("docker_service"),
        "depends_on": service.get("depends_on", []),
    }


def queue_depths():
    try:
        from redis import Redis
        r = Redis(host="127.0.0.1", port=6379, socket_connect_timeout=0.5)
        return {name: r.llen(f"rq:queue:{name}") for name in ("fetch", "process", "notify")}
    except Exception:
        return None


def llm_gateway_metrics():
    try:
        r = requests.get("http://127.0.0.1:8091/metrics", timeout=1)
        if r.status_code == 200:
            return r.json()
    except requests.RequestException:
        pass
    return None


def system_metrics():
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "ram_percent": psutil.virtual_memory().percent,
    }


def docker_available() -> bool:
    return shutil.which("docker") is not None


GATEWAY_URL = os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1:8091")


@app.route("/")
def index():
    if not is_onboarding_complete():
        return redirect("/onboarding")
    services = load_services()
    statuses = [status_for(s) for s in services]
    return render_template(
        "dashboard.html", page="dashboard", services=statuses, metrics=system_metrics(),
        queues=queue_depths(), docker_ok=docker_available(),
        llm_metrics=llm_gateway_metrics(),
        task_summary=task_counts_by_status(
            project_id=current_project_id()
        ),
    )


@app.route("/thesis")
def thesis_page():
    """Vista mínima del dominio Thesis sobre los datos ya ingeridos."""
    project_id = current_project_id()
    filters = {
        "role": request.args.get("role", "").strip(),
        "extraction_status": request.args.get("extraction_status", "").strip(),
        "suggestion_status": request.args.get("suggestion_status", "").strip(),
        "q": request.args.get("q", "").strip(),
    }
    try:
        structure = thesis_service.get_structure(project_id)
        from common import thesis_versions
        versions = []
        for chapter in structure["chapters"]:
            for version in thesis_versions.list_versions(project_id, chapter["id"]):
                version["chapter_code"] = chapter["code"]
                version["chapter_title"] = chapter["title"]
                version["claims"] = thesis_versions.list_claims(project_id, version["id"])
                versions.append(version)
        files = thesis_files.list_files(project_id)
        for item in files:
            detail = thesis_files.file_detail(project_id, item["id"])
            item["fragments"] = detail.get("fragments", [])
        suggestions = thesis_placements.list_suggestions(project_id)
    except thesis_service.ThesisNotFound:
        return render_template("thesis.html", page="thesis", project=get_project(project_id),
                               structure=None, files=[], suggestions=[], versions=[], filters=filters,
                               error="No hay una tesis creada para este proyecto."), 404
    if filters["role"]:
        files = [item for item in files if item.get("source_role") == filters["role"]]
    if filters["extraction_status"]:
        files = [item for item in files if item.get("status") == filters["extraction_status"]]
    if filters["q"]:
        query = filters["q"].casefold()
        files = [item for item in files if query in (item.get("filename") or "").casefold()
                 or any(query in (fragment.get("text") or "").casefold()
                        for fragment in item.get("fragments", []))]
    visible_doc_ids = {item["doc_id"] for item in files}
    if filters["suggestion_status"]:
        suggestions = [item for item in suggestions if item.get("status") == filters["suggestion_status"]]
    if filters["role"] or filters["extraction_status"] or filters["q"]:
        suggestions = [item for item in suggestions if item.get("doc_id") in visible_doc_ids]
    return render_template("thesis.html", page="thesis", project=get_project(project_id),
                           structure=structure, files=files, suggestions=suggestions, versions=versions,
                           filters=filters, error=None)


@app.route("/thesis/placements/<suggestion_id>/review", methods=["POST"])
def thesis_review_placement_page(suggestion_id):
    """Revisión de una propuesta desde la sesión del dashboard."""
    project_id = current_project_id()
    payload = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    if payload.get("corrected_chapter_id") == "":
        payload["corrected_chapter_id"] = None
    reviewer_id = session.get("user_id") or session.get("username") or "dashboard"
    try:
        thesis_placements.review_suggestion(project_id, suggestion_id, payload, reviewer_id)
    except thesis_service.ThesisNotFound:
        return jsonify({"error": "propuesta no encontrada"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if request.accept_mimetypes.best == "application/json" or request.is_json:
        return jsonify({"updated": suggestion_id})
    return redirect("/thesis")


@app.route("/thesis/chapters/<chapter_id>/title", methods=["POST"])
def thesis_update_chapter_title_page(chapter_id):
    """Actualiza solo el título visible; chapter_type permanece estable."""
    payload = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    try:
        chapter = thesis_service.update_chapter_title(
            current_project_id(), chapter_id, payload.get("title")
        )
    except thesis_service.ThesisNotFound:
        return jsonify({"error": "capítulo no encontrado"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if request.accept_mimetypes.best == "application/json" or request.is_json:
        return jsonify({"chapter": chapter})
    return redirect("/thesis")


@app.route("/thesis/files/<file_id>/classify", methods=["POST"])
def thesis_classify_file_page(file_id):
    """Ejecuta la clasificación existente y genera propuestas idempotentes."""
    try:
        thesis_files.file_detail(current_project_id(), file_id)
        from common.thesis_classifier import classify_file
        result = classify_file(current_project_id(), file_id)
        result["placement"] = thesis_placements.generate_for_file(current_project_id(), file_id)
    except thesis_service.ThesisNotFound:
        return jsonify({"error": "archivo no encontrado"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if request.accept_mimetypes.best == "application/json" or request.is_json:
        return jsonify(result)
    return redirect("/thesis")


@app.route("/thesis/versions/<version_id>/verify", methods=["POST"])
def thesis_verify_version_page(version_id):
    try:
        from common.thesis_generation import verify_version
        result = verify_version(current_project_id(), version_id)
    except thesis_service.ThesisNotFound:
        return jsonify({"error": "versión no encontrada"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if request.accept_mimetypes.best == "application/json" or request.is_json:
        return jsonify(result)
    return redirect("/thesis")


@app.route("/onboarding")
def onboarding_page():
    return render_template("onboarding.html", page="onboarding")


@app.route("/api/onboarding/checks")
def onboarding_checks():
    return jsonify(run_all_checks())


@app.route("/api/onboarding/install-model", methods=["POST"])
def onboarding_install_model():
    payload = request.get_json(silent=True) or {}
    return jsonify(pull_recommended_model(payload.get("model", "llama3.1")))


@app.route("/api/onboarding/complete", methods=["POST"])
def onboarding_complete():
    payload = request.get_json(force=True) or {}
    mode = payload.get("mode", "local_only")
    save_setup_state(mode)
    return jsonify({"completed": True, "mode": mode})


# --- Diagnostics ---

@app.route("/diagnostics")
def diagnostics_page():
    return render_template("diagnostics.html", page="diagnostics")


@app.route("/api/diagnostics")
def diagnostics_api():
    return jsonify(run_diagnostics())


# Colas ya cubiertas por una entrada real en services.yaml (arrancan con
# su start_command normal); el resto usa el comando genérico de RQ.
_QUEUE_TO_SERVICE = {"fetch": "worker_fetch", "process": "worker_process", "notify": "worker_notify"}


@app.route("/api/diagnostics/start-worker/<queue_name>", methods=["POST"])
def diagnostics_start_worker(queue_name):
    service_id = _QUEUE_TO_SERVICE.get(queue_name)
    if service_id:
        svc = get_service(service_id)
        if svc:
            logf = _log_file(service_id)
            proc = subprocess.Popen(svc["start_command"], shell=True, cwd=BASE_DIR, stdout=logf, stderr=subprocess.STDOUT)
            _started_pids[service_id] = proc.pid
            return jsonify({"started": True, "queue": queue_name, "pid": proc.pid})

    # Cola de un plugin sin entrada propia en services.yaml: comando genérico.
    cmd = f"rq worker {queue_name} --url redis://127.0.0.1:6379/0"
    logf = _log_file(f"worker_{queue_name}")
    proc = subprocess.Popen(cmd, shell=True, cwd=BASE_DIR, stdout=logf, stderr=subprocess.STDOUT)
    _started_pids[f"worker_{queue_name}"] = proc.pid
    return jsonify({"started": True, "queue": queue_name, "pid": proc.pid, "generic": True})


@app.route("/playground")
def playground_page():
    project_id = current_project_id()
    return render_template("playground.html", page="playground",
                            project=get_project(project_id), project_settings=get_project_settings(project_id))


@app.route("/api/playground/providers")
def playground_providers():
    try:
        r = requests.get(f"{GATEWAY_URL}/providers", timeout=2)
        return jsonify(r.json())
    except requests.RequestException as e:
        return jsonify({"error": f"no se pudo contactar con el LLM Gateway: {e}"}), 502


@app.route("/api/playground/run", methods=["POST"])
def playground_run():
    payload = request.get_json(force=True) or {}
    try:
        r = requests.post(f"{GATEWAY_URL}/generate", json=payload, timeout=125)
        return jsonify(r.json()), r.status_code
    except requests.RequestException as e:
        return jsonify({"error": f"no se pudo contactar con el LLM Gateway: {e}"}), 502


@app.route("/api/playground/compare", methods=["POST"])
def playground_compare():
    """
    Lanza la misma petición contra dos combinaciones proveedor/modelo y
    devuelve ambos resultados para comparar lado a lado. Secuencial, no en
    paralelo — el semáforo del gateway ya limita concurrencia por diseño,
    lanzarlas a la vez solo mediría "cuánto tarda cuando compiten entre
    sí", no el rendimiento real de cada una.
    """
    payload = request.get_json(force=True) or {}
    shared = {k: v for k, v in payload.items() if k not in ("a", "b")}
    results = {}
    for key in ("a", "b"):
        variant = {**shared, **payload.get(key, {})}
        try:
            r = requests.post(f"{GATEWAY_URL}/generate", json=variant, timeout=125)
            results[key] = r.json()
        except requests.RequestException as e:
            results[key] = {"error": str(e)}
    return jsonify(results)


# --- Knowledge (RAG) ---

EMBEDDING_MODEL_NAME = "hashing_trick_256"


def _index_and_register(
    doc_id,
    text,
    collection_id,
    filename=None,
    content_type=None,
    doc_version="v1",
    project_id="default",
    structured_blocks=None,
):
    from common.document_service import index_blocks
    from psycopg2.extras import Json

    from common.document_service import DocumentConflict
    from db.db import document_references
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT project_id FROM documents WHERE doc_id=%s FOR UPDATE", (doc_id,))
            existing = cur.fetchone()
            if existing and (existing[0] != project_id or document_references(cur, doc_id)):
                raise DocumentConflict("documento compartido; no se puede sobrescribir o reindexar")
        chunks, locators = index_blocks(
            conn, doc_id, text, structured_blocks, project_id=project_id, doc_version=doc_version,
        )
        # Preserve the existing entry point for pasted text and reindexing.
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO documents (doc_id, collection_id, project_id, filename, content_type, "
                "doc_version, embedding_model, raw_text, n_chunks, source_metadata) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (doc_id) DO UPDATE SET "
                "collection_id=EXCLUDED.collection_id, filename=EXCLUDED.filename, "
                "content_type=EXCLUDED.content_type, doc_version=EXCLUDED.doc_version, "
                "embedding_model=EXCLUDED.embedding_model, raw_text=EXCLUDED.raw_text, "
                "n_chunks=EXCLUDED.n_chunks, source_metadata=EXCLUDED.source_metadata, indexed_at=now()",
                (doc_id, collection_id, project_id, filename, content_type, doc_version,
                 EMBEDDING_MODEL_NAME, text, len(chunks),
                 Json({"blocks": structured_blocks or [], "chunk_locators": locators})),
            )
    return len(chunks)


@app.route("/knowledge")
def knowledge_page():
    project_id = current_project_id()
    ensure_default_collection(project_id=project_id)
    collection_id = request.args.get("collection", "default")
    collections = list_collections(project_id=project_id)
    documents = list_documents(collection_id, project_id=project_id)
    return render_template("knowledge.html", page="knowledge", collections=collections,
                            current_collection=collection_id, documents=documents,
                            project=get_project(project_id))


@app.route("/knowledge/<doc_id>")
def knowledge_document_page(doc_id):
    doc = get_document(doc_id)
    if not doc:
        return "Documento no encontrado", 404
    return render_template("knowledge_document.html", page="knowledge", doc=doc)


@app.route("/api/knowledge/collections", methods=["POST"])
def knowledge_create_collection():
    payload = request.get_json(force=True) or {}
    name = payload.get("name", "").strip()
    if not name:
        return jsonify({"error": "el nombre es obligatorio"}), 400
    collection_id = payload.get("id") or name.lower().replace(" ", "-")
    create_collection(collection_id, name, project_id=current_project_id(), description=payload.get("description"))
    return jsonify({"id": collection_id, "name": name}), 201


@app.route("/api/knowledge/index", methods=["POST"])
def knowledge_index():
    """Indexar texto pegado directamente (sin fichero)."""
    payload = request.get_json(force=True) or {}
    doc_id = payload.get("doc_id", "").strip()
    text = payload.get("text", "").strip()
    doc_version = payload.get("doc_version", "v1").strip() or "v1"
    collection_id = payload.get("collection_id", "default")
    if not doc_id or not text:
        return jsonify({"error": "doc_id y text son obligatorios"}), 400
    from common.document_service import DocumentConflict
    try:
        n_chunks = _index_and_register(doc_id, text, collection_id, filename=None,
                                        content_type="text/plain", doc_version=doc_version,
                                        project_id=current_project_id())
    except DocumentConflict as exc:
        return jsonify({"error": str(exc)}), 409
    return jsonify({"doc_id": doc_id, "doc_version": doc_version, "n_chunks": n_chunks})


@app.route("/api/knowledge/upload", methods=["POST"])
def knowledge_upload():
    """Sube un fichero real (PDF/DOCX/TXT/MD), lo parsea, trocea e indexa."""
    file = request.files.get("file")
    collection_id = request.form.get("collection_id", "default")
    doc_version = request.form.get("doc_version", "v1")
    if not file or not file.filename:
        return jsonify({"error": "no se ha recibido ningún fichero"}), 400

    from common.document_service import upload_and_index, DocumentConflict
    try:
        doc, reused = upload_and_index(current_project_id(), file, collection_id=collection_id,
                                       requested_doc_id=request.form.get("doc_id"), doc_version=doc_version)
    except DocumentConflict as exc:
        return jsonify({"error": str(exc)}), 409
    except (ValueError, OSError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"doc_id": doc["doc_id"], "filename": doc["filename"],
                    "n_chunks": doc["n_chunks"], "reused": reused}), 201


@app.route("/api/knowledge/documents/<doc_id>/reindex", methods=["POST"])
def knowledge_reindex(doc_id):
    """Vuelve a trocear/embeder el texto ya guardado, sin pedir el fichero otra vez."""
    doc = get_document(doc_id)
    if not doc:
        return jsonify({"error": "documento no encontrado"}), 404
    if not doc.get("raw_text"):
        return jsonify({"error": "este documento no tiene texto guardado para reindexar (indexado antes de esta función)"}), 400
    structured_blocks = None

    source_metadata = doc.get("source_metadata") or {}
    if source_metadata.get("blocks"):
        structured_blocks = source_metadata["blocks"]

    from common.document_service import DocumentConflict
    try:
        n_chunks = _index_and_register(
            doc_id,
            doc["raw_text"],
            doc["collection_id"],
            filename=doc["filename"],
            content_type=doc["content_type"],
            doc_version=doc["doc_version"],
            project_id=doc["project_id"],
            structured_blocks=structured_blocks,
        )
    except DocumentConflict as exc:
        return jsonify({"error": str(exc)}), 409
    return jsonify({"doc_id": doc_id, "n_chunks": n_chunks})


@app.route("/api/knowledge/documents/<doc_id>", methods=["DELETE"])
def knowledge_delete(doc_id):
    doc = get_document(doc_id)
    if not doc or doc["project_id"] != current_project_id():
        return jsonify({"error": "documento no encontrado"}), 404
    if not delete_document(doc_id):
        return jsonify({"error": "documento utilizado por revisión sistemática o Thesis"}), 409
    return jsonify({"deleted": doc_id})


@app.route("/api/knowledge/documents/<doc_id>/chunks")
def knowledge_document_chunks(doc_id):
    return jsonify(get_document_chunks(doc_id))


@app.route("/api/knowledge/search")
def knowledge_search():
    query = request.args.get("q", "")
    top_k = int(request.args.get("top_k", 5))
    doc_id = request.args.get("doc_id")
    if not query:
        return jsonify({"error": "falta ?q="}), 400
    candidates = retrieve(query, top_k=20, doc_id=doc_id, project_id=current_project_id())
    top = rerank(query, candidates, top_n=top_k)
    return jsonify(format_citations(top))


# --- Plugins ---

from common.model_manager import list_installed, list_available, install_model, delete_model, benchmark_model  # noqa: E402


@app.route("/models")
def models_page():
    installed, error = list_installed()
    installed_names = {m["name"] for m in installed}
    available = list_available(installed_names)
    return render_template("models.html", page="models", installed=installed, available=available, ollama_error=error)


@app.route("/api/models/install", methods=["POST"])
def models_install():
    payload = request.get_json(force=True) or {}
    model_name = payload.get("model")
    if not model_name:
        return jsonify({"error": "falta 'model'"}), 400
    return jsonify(install_model(model_name))


@app.route("/api/models/<path:model_name>", methods=["DELETE"])
def models_delete(model_name):
    result = delete_model(model_name)
    if "error" in result:
        return jsonify(result), 502
    return jsonify(result)


@app.route("/api/models/<path:model_name>/benchmark", methods=["POST"])
def models_benchmark(model_name):
    result = benchmark_model(model_name)
    if "error" in result:
        return jsonify(result), 502
    return jsonify(result)


@app.route("/plugins")
def plugins_page():
    registry = discover_plugins()
    active_queues = set()
    try:
        from rq import Worker
        from redis import Redis
        r = Redis(host="127.0.0.1", port=6379, socket_connect_timeout=0.5)
        for w in Worker.all(connection=r):
            active_queues.update(q.name for q in w.queues)
    except Exception:
        pass
    plugins = [
        {"name": name, "module": info["module_name"], "timeout": info["timeout"], "has_worker": name in active_queues}
        for name, info in registry.items()
    ]
    return render_template("plugins.html", page="plugins", plugins=plugins)


# --- Integrations (n8n) ---

@app.route("/integrations")
def integrations_page():
    return render_template("integrations.html", page="integrations",
                            integrations=list_integrations(project_id=current_project_id()))


@app.route("/api/integrations/<flow_name>/<action>", methods=["POST"])
def integrations_toggle(flow_name, action):
    if action not in ("enable", "disable"):
        return jsonify({"error": "accion invalida"}), 400
    set_integration_enabled(flow_name, action == "enable", project_id=current_project_id())
    return jsonify({"flow_name": flow_name, "enabled": action == "enable"})


# --- Tasks (vista completa) ---

@app.route("/tasks-view")
def tasks_view_page():
    status = request.args.get("status")
    project_id = current_project_id()
    tasks = list_tasks(status=status, limit=100, project_id=project_id)
    return render_template("tasks.html", page="tasks", tasks=tasks, status_filter=status,
                            counts=task_counts_by_status(project_id=project_id))


@app.route("/api/tasks/<task_id>/audit")
def task_audit_proxy(task_id):
    task = get_task(task_id)

    if not task:
        return jsonify({
            "error": "Tarea no encontrada",
        }), 404

    if task.get("project_id") != current_project_id():
        return jsonify({
            "error": "Tarea no encontrada en el proyecto activo",
        }), 404

    return jsonify(get_audit_trail(task_id))


# --- Logs unificados ---

@app.route("/logs-view")
def logs_view_page():
    services = load_services()
    return render_template("logs.html", page="logs", services=services)


# --- Evaluation ---

@app.route("/evaluation")
def evaluation_page():
    project_id = current_project_id()
    eval_dir = BASE_DIR / "evaluation"
    case_files = sorted(f.name for f in eval_dir.glob("*.json")) if eval_dir.exists() else []
    plugin_names = list(discover_plugins().keys())
    return render_template("evaluation.html", page="evaluation", case_files=case_files,
                            plugin_names=plugin_names, project=get_project(project_id),
                            history=list_evaluations(project_id))


@app.route("/api/evaluation/run", methods=["POST"])
def evaluation_run():
    payload = request.get_json(force=True) or {}
    cases_file = payload.get("cases_file")
    target = payload.get("target")
    if not cases_file or not target:
        return jsonify({"error": "cases_file y target son obligatorios"}), 400

    cases_path = BASE_DIR / "evaluation" / cases_file
    if not cases_path.exists() or cases_path.parent != (BASE_DIR / "evaluation"):
        return jsonify({"error": "fichero de casos no encontrado"}), 404

    result = subprocess.run(
        ["python3", "scripts/run_evaluation.py", "--cases", str(cases_path), "--target", target,
         "--project", current_project_id()],
        cwd=BASE_DIR, capture_output=True, text=True, timeout=120,
    )
    return jsonify({"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})


# --- Settings ---
@app.route("/systematic-reviews")
def systematic_reviews():
    import psycopg2.extras
    from db.db import get_conn

    project_id = current_project_id()

    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        ) as cur:

            cur.execute(
                """
                SELECT
                    sr.id,
                    sr.project_id,
                    sr.title,
                    sr.review_type,
                    sr.research_question,
                    sr.status,
                    sr.created_at,
                    sr.updated_at,

                    COUNT(ra.id) AS article_count,

                    COUNT(
                        CASE
                            WHEN ra.screening_status = 'reviewed'
                            THEN 1
                        END
                    ) AS reviewed_count

                FROM systematic_reviews sr

                LEFT JOIN review_articles ra
                    ON ra.review_id = sr.id

                WHERE sr.project_id = %s

                GROUP BY
                    sr.id,
                    sr.project_id,
                    sr.title,
                    sr.review_type,
                    sr.research_question,
                    sr.status,
                    sr.created_at,
                    sr.updated_at

                ORDER BY sr.created_at DESC
                """,
                (project_id,),
            )

            reviews = cur.fetchall()

    return render_template(
        "systematic_reviews.html",
        page="systematic_reviews",
        reviews=reviews,
    )


@app.route(
    "/api/systematic-reviews/create",
    methods=["POST"]
)
def systematic_reviews_create():
    import uuid
    from db.db import get_conn

    data = request.get_json(silent=True) or {}

    title = (data.get("title") or "").strip()

    if not title:
        return jsonify({
            "ok": False,
            "error": "El título es obligatorio"
        }), 400

    allowed_review_types = {
        "systematic_review",
        "scoping_review",
        "rapid_review",
        "meta_analysis",
    }

    allowed_statuses = {
        "draft",
        "active",
    }

    review_type = (
        data.get("review_type")
        or "systematic_review"
    )

    status = (
        data.get("status")
        or "draft"
    )

    if review_type not in allowed_review_types:
        return jsonify({
            "ok": False,
            "error": "Tipo de revisión no válido"
        }), 400

    if status not in allowed_statuses:
        return jsonify({
            "ok": False,
            "error": "Estado de revisión no válido"
        }), 400

    review_id = str(uuid.uuid4())

    project_id = current_project_id()

    research_question = (
        data.get("research_question") or ""
    ).strip()

    population = (
        data.get("population") or ""
    ).strip()

    intervention = (
        data.get("intervention") or ""
    ).strip()

    comparator = (
        data.get("comparator") or ""
    ).strip()

    outcomes = (
        data.get("outcomes") or ""
    ).strip()

    inclusion_criteria = (
        data.get("inclusion_criteria") or ""
    ).strip()

    exclusion_criteria = (
        data.get("exclusion_criteria") or ""
    ).strip()

    try:

        with get_conn() as conn:
            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO systematic_reviews (
                        id,
                        project_id,
                        title,
                        review_type,
                        research_question,
                        population,
                        intervention,
                        comparator,
                        outcomes,
                        inclusion_criteria,
                        exclusion_criteria,
                        status
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        review_id,
                        project_id,
                        title,
                        review_type,
                        research_question,
                        population,
                        intervention,
                        comparator,
                        outcomes,
                        inclusion_criteria,
                        exclusion_criteria,
                        status,
                    ),
                )

        return jsonify({
            "ok": True,
            "review_id": review_id,
        })

    except Exception as exc:

        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 500



@app.route(
    "/api/systematic-review/update-protocol",
    methods=["POST"],
)
def systematic_review_update_protocol():
    from db.db import get_conn, log_review_audit

    data = request.get_json(silent=True) or {}

    review_id = (data.get("review_id") or "").strip()

    if not review_id:
        return jsonify({
            "ok": False,
            "error": "review_id es obligatorio",
        }), 400

    if not _review_in_current_project(review_id):
        return jsonify({
            "ok": False,
            "error": "Revisión no encontrada en el proyecto actual",
        }), 404

    fields = {
        "research_question": (
            data.get("research_question") or ""
        ).strip(),
        "population": (
            data.get("population") or ""
        ).strip(),
        "intervention": (
            data.get("intervention") or ""
        ).strip(),
        "comparator": (
            data.get("comparator") or ""
        ).strip(),
        "outcomes": (
            data.get("outcomes") or ""
        ).strip(),
        "inclusion_criteria": (
            data.get("inclusion_criteria") or ""
        ).strip(),
        "exclusion_criteria": (
            data.get("exclusion_criteria") or ""
        ).strip(),
    }

    try:
        project_id = current_project_id()

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        research_question,
                        population,
                        intervention,
                        comparator,
                        outcomes,
                        inclusion_criteria,
                        exclusion_criteria
                    FROM systematic_reviews
                    WHERE id = %s
                      AND project_id = %s
                    FOR UPDATE
                    """,
                    (review_id, project_id),
                )

                previous = cur.fetchone()

                if not previous:
                    return jsonify({
                        "ok": False,
                        "error": "No se pudo actualizar la revisión",
                    }), 404

                before_state = {
                    "research_question": previous[0] or "",
                    "population": previous[1] or "",
                    "intervention": previous[2] or "",
                    "comparator": previous[3] or "",
                    "outcomes": previous[4] or "",
                    "inclusion_criteria": previous[5] or "",
                    "exclusion_criteria": previous[6] or "",
                }

                cur.execute(
                    """
                    UPDATE systematic_reviews
                    SET
                        research_question = %s,
                        population = %s,
                        intervention = %s,
                        comparator = %s,
                        outcomes = %s,
                        inclusion_criteria = %s,
                        exclusion_criteria = %s,
                        updated_at = NOW()
                    WHERE id = %s
                      AND project_id = %s
                    """,
                    (
                        fields["research_question"],
                        fields["population"],
                        fields["intervention"],
                        fields["comparator"],
                        fields["outcomes"],
                        fields["inclusion_criteria"],
                        fields["exclusion_criteria"],
                        review_id,
                        project_id,
                    ),
                )

                if cur.rowcount != 1:
                    raise RuntimeError(
                        "No se pudo actualizar la revisión"
                    )

                log_review_audit(
                    project_id=project_id,
                    review_id=review_id,
                    action="protocol_updated",
                    actor_type="human",
                    before_state=before_state,
                    after_state=fields,
                    details={
                        "source": "systematic_review_protocol_editor",
                    },
                    conn=conn,
                )

        return jsonify({
            "ok": True,
            "review_id": review_id,
        })

    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 500


@app.route(
    "/api/systematic-reviews/save-search-strategy",
    methods=["POST"]
)
def systematic_reviews_save_search_strategy():
    import uuid
    from db.db import get_conn

    data = request.get_json(silent=True) or {}

    review_id = (
        data.get("review_id")
        or ""
    ).strip()

    query = (
        data.get("query")
        or ""
    ).strip()

    database_name = (
        data.get("database_name")
        or "PubMed"
    ).strip()

    if not review_id:
        return jsonify({
            "ok": False,
            "error": "review_id es obligatorio"
        }), 400

    if not _review_in_current_project(review_id):
        return jsonify({
            "ok": False,
            "error": "Revisión no encontrada en el proyecto activo"
        }), 404

    if not query:
        return jsonify({
            "ok": False,
            "error": "La estrategia de búsqueda está vacía"
        }), 400

    is_valid = bool(
        data.get("is_valid")
    )

    accepted_by_database = bool(
        data.get("accepted_by_database")
    )

    total_found = data.get(
        "total_found"
    )

    query_translation = (
        data.get("query_translation")
        or ""
    )

    warnings = (
        data.get("warnings")
        or []
    )

    errors = (
        data.get("errors")
        or []
    )

    removed_terms = (
        data.get("removed_terms")
        or []
    )

    concepts = (
        data.get("concepts")
        or []
    )

    model = (
        data.get("model")
        or ""
    )

    provider = (
        data.get("provider")
        or ""
    )

    try:

        with get_conn() as conn:
            with conn.cursor() as cur:

                # Serializa la creación de versiones para esta revisión.
                # Así dos peticiones simultáneas no pueden calcular
                # el mismo next_version.
                cur.execute(
                    """
                    SELECT id
                    FROM systematic_reviews
                    WHERE id = %s
                      AND project_id = %s
                    FOR UPDATE
                    """,
                    (
                        review_id,
                        current_project_id(),
                    ),
                )

                if not cur.fetchone():
                    return jsonify({
                        "ok": False,
                        "error": "Revisión no encontrada en el proyecto activo"
                    }), 404

                cur.execute(
                    """
                    SELECT COALESCE(
                        MAX(version),
                        0
                    )
                    FROM review_search_strategies
                    WHERE review_id = %s
                      AND database_name = %s
                    """,
                    (
                        review_id,
                        database_name,
                    ),
                )

                current_version = (
                    cur.fetchone()[0]
                    or 0
                )

                next_version = (
                    current_version + 1
                )

                strategy_id = str(
                    uuid.uuid4()
                )

                cur.execute(
                    """
                    INSERT INTO review_search_strategies (
                        id,
                        review_id,
                        database_name,
                        version,
                        query,
                        is_valid,
                        accepted_by_database,
                        total_found,
                        query_translation,
                        warnings,
                        errors,
                        removed_terms,
                        concepts,
                        model,
                        provider,
                        human_confirmed,
                        confirmed_at
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        TRUE,
                        CURRENT_TIMESTAMP
                    )
                    """,
                    (
                        strategy_id,
                        review_id,
                        database_name,
                        next_version,
                        query,
                        is_valid,
                        accepted_by_database,
                        total_found,
                        query_translation,
                        warnings,
                        errors,
                        removed_terms,
                        concepts,
                        model,
                        provider,
                    ),
                )

        return jsonify({
            "ok": True,
            "strategy_id": strategy_id,
            "version": next_version,
        })

    except Exception as exc:

        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 500


@app.route(
    "/api/systematic-reviews/design-protocol",
    methods=["POST"]
)
def systematic_reviews_design_protocol():
    import uuid
    from workers.plugins.protocol_designer import handle as protocol_designer_handle

    data = request.get_json(silent=True) or {}

    topic = (
        data.get("topic")
        or data.get("research_topic")
        or ""
    ).strip()

    review_type = (
        data.get("review_type")
        or "systematic_review"
    ).strip()

    if not topic:
        return jsonify({
            "ok": False,
            "error": "El tema o pregunta inicial es obligatorio"
        }), 400

    allowed_review_types = {
        "systematic_review",
        "scoping_review",
        "rapid_review",
        "meta_analysis",
    }

    if review_type not in allowed_review_types:
        return jsonify({
            "ok": False,
            "error": "Tipo de revisión no válido"
        }), 400

    try:

        task_id = "protocol-ui-" + str(uuid.uuid4())

        result = protocol_designer_handle(
            task_id,
            {
                "topic": topic,
                "review_type": review_type,
            },
        )

        return jsonify({
            "ok": True,
            "result": result,
        })

    except Exception as exc:

        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 500


@app.route(
    "/api/systematic-reviews/design-search-strategy",
    methods=["POST"]
)
def systematic_reviews_design_search_strategy():
    import uuid
    from workers.plugins.search_strategy_designer import handle as search_strategy_handle

    data = request.get_json(silent=True) or {}

    research_question = (
        data.get("research_question")
        or ""
    ).strip()

    population = (
        data.get("population")
        or ""
    ).strip()

    intervention = (
        data.get("intervention")
        or ""
    ).strip()

    comparator = (
        data.get("comparator")
        or ""
    ).strip()

    outcomes = (
        data.get("outcomes")
        or ""
    ).strip()

    if not research_question:
        return jsonify({
            "ok": False,
            "error": "La pregunta de investigación es obligatoria"
        }), 400

    try:

        task_id = "search-strategy-ui-" + str(uuid.uuid4())

        result = search_strategy_handle(
            task_id,
            {
                "research_question": research_question,
                "population": population,
                "intervention": intervention,
                "comparator": comparator,
                "outcomes": outcomes,
            },
        )

        return jsonify({
            "ok": True,
            "result": result,
        })

    except Exception as exc:

        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 500


@app.route("/systematic-review")
def systematic_review():
    from db.db import get_conn
    from dashboard.prisma import calculate_prisma
    from psycopg2.extras import RealDictCursor

    review_id = request.args.get("review_id")

    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:

            if review_id:
                cur.execute(
                    """
                    SELECT *
                    FROM systematic_reviews
                    WHERE id = %s
                      AND project_id = %s
                    """,
                    (
                        review_id,
                        current_project_id(),
                    ),
                )
            else:
                cur.execute(
                    """
                    SELECT *
                    FROM systematic_reviews
                    WHERE project_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (current_project_id(),),
                )

            review = cur.fetchone()

            if not review:
                return render_template(
                    "systematic_review.html",
                    page="systematic_review",
                    review=None,
                    articles=[],
                    search_strategies=[],
                    extractions=[],
                    conflicts=[],
                    stats={
                        "total": 0,
                        "reviewed": 0,
                        "pending": 0,
                        "conflicts": 0,
                        "title_abstract_pending": 0,
                        "full_text_pending": 0,
                        "extraction_total": 0,
                        "extraction_pending": 0,
                        "extraction_validated": 0,
                    },
                    prisma={
                        "records_identified": 0,
                        "records_imported": 0,
                        "duplicates_removed": 0,
                        "records_screened": 0,
                        "records_excluded": 0,
                        "reports_sought": 0,
                        "reports_not_retrieved": None,
                        "reports_assessed": 0,
                        "reports_excluded": 0,
                        "studies_included": 0,
                        "exclusion_reasons": {},
                        "databases": {},
                    },
                )

            cur.execute(
                """
                SELECT
                    ra.id,
                    ra.pmid,
                    ra.doi,
                    ra.title,
                    ra.journal,
                    ra.year,
                    ra.ai_decision,
                    ra.ai_reason,
                    ra.ai_confidence,
                    ra.human_decision,
                    ra.exclusion_reason,
                    ra.exclusion_reason_code,
                    ra.screening_status,
                    ra.screening_stage,
                    ra.title_abstract_status,
                    ra.full_text_status,
                    ra.full_text_available,
                    ra.full_text_retrieval_status,
                    ra.full_text_document_id,
                    ra.final_decision,
                    ra.is_duplicate,
                    ra.duplicate_of_article_id,
                    ra.duplicate_reason,
                    d.filename AS full_text_filename,
                    d.n_chunks AS full_text_n_chunks
                FROM review_articles ra
                LEFT JOIN documents d
                    ON d.doc_id = ra.full_text_document_id
                WHERE ra.review_id = %s
                ORDER BY ra.created_at ASC
                """,
                (review["id"],),
            )

            articles = [dict(row) for row in cur.fetchall()]
            article_map = {article["id"]: article for article in articles}

            for article in articles:
                article["screening_decisions"] = []
                article["decisions_by_stage"] = {
                    "title_abstract": [],
                    "full_text": [],
                }
                article["open_conflicts"] = []
                article["conflicts_by_stage"] = {}

            cur.execute(
                """
                SELECT
                    id,
                    review_id,
                    article_id,
                    stage,
                    reviewer_id,
                    decision,
                    exclusion_reason_code,
                    reason,
                    notes,
                    created_at,
                    updated_at
                FROM review_screening_decisions
                WHERE review_id = %s
                ORDER BY created_at ASC, reviewer_id ASC
                """,
                (review["id"],),
            )

            screening_decisions = [dict(row) for row in cur.fetchall()]

            for decision in screening_decisions:
                article = article_map.get(decision["article_id"])
                if not article:
                    continue

                article["screening_decisions"].append(decision)
                article["decisions_by_stage"].setdefault(
                    decision["stage"],
                    [],
                ).append(decision)

            cur.execute(
                """
                SELECT
                    id,
                    review_id,
                    article_id,
                    stage,
                    status,
                    resolution,
                    resolved_by,
                    resolution_notes,
                    created_at,
                    resolved_at
                FROM review_screening_conflicts
                WHERE review_id = %s
                ORDER BY created_at ASC
                """,
                (review["id"],),
            )

            conflicts = [dict(row) for row in cur.fetchall()]

            for conflict in conflicts:
                article = article_map.get(conflict["article_id"])
                if not article:
                    continue

                article["conflicts_by_stage"][conflict["stage"]] = conflict

                if conflict["status"] == "open":
                    article["open_conflicts"].append(conflict)

            cur.execute(
                """
                SELECT
                    id,
                    database_name,
                    version,
                    query,
                    is_valid,
                    accepted_by_database,
                    total_found,
                    model,
                    provider,
                    human_confirmed,
                    created_at,
                    confirmed_at
                FROM review_search_strategies
                WHERE review_id = %s
                ORDER BY database_name ASC, version DESC
                """,
                (review["id"],),
            )

            search_strategies = cur.fetchall()

            cur.execute(
                """
                SELECT
                    id,
                    review_id,
                    database_name,
                    query,
                    total_found,
                    imported_count,
                    searched_at,
                    strategy_id
                FROM review_searches
                WHERE review_id = %s
                ORDER BY searched_at ASC
                """,
                (review["id"],),
            )

            searches = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT
                    re.id,
                    re.review_id,
                    re.article_id,
                    re.field_id,
                    ref.field_key,
                    ref.label AS field_label,
                    ref.description AS field_description,
                    ref.value_type,
                    ref.required,
                    ref.display_order,
                    re.ai_value,
                    re.ai_reason,
                    re.ai_confidence,
                    re.source_type,
                    re.source_location,
                    re.source_quote,
                    re.human_value,
                    re.validation_status,
                    re.reviewer_id,
                    re.reviewer_notes,
                    re.model,
                    re.provider,
                    re.skills_used,
                    ra.pmid,
                    ra.doi,
                    ra.title AS article_title,
                    ra.journal,
                    ra.year
                FROM review_extractions re
                JOIN review_extraction_fields ref
                  ON ref.id = re.field_id
                JOIN review_articles ra
                  ON ra.id = re.article_id
                WHERE re.review_id = %s
                ORDER BY
                    ra.created_at ASC,
                    ref.display_order ASC,
                    ref.label ASC
                """,
                (review["id"],),
            )

            extractions = cur.fetchall()

    non_duplicate_articles = [
        article for article in articles
        if not article["is_duplicate"]
    ]

    total = len(non_duplicate_articles)

    reviewed = sum(
        1 for article in non_duplicate_articles
        if article["screening_status"] == "reviewed"
    )

    conflict_count = sum(
        1 for conflict in conflicts
        if conflict["status"] == "open"
    )

    title_abstract_pending = sum(
        1 for article in non_duplicate_articles
        if article["title_abstract_status"] in {"pending", "conflict"}
    )

    full_text_pending = sum(
        1 for article in non_duplicate_articles
        if article["full_text_status"] in {"pending", "conflict"}
    )

    pending = max(0, total - reviewed)

    extraction_total = len(extractions)
    extraction_pending = sum(
        1 for extraction in extractions
        if extraction["validation_status"] == "pending"
    )
    extraction_validated = extraction_total - extraction_pending

    stats = {
        "total": total,
        "reviewed": reviewed,
        "pending": pending,
        "conflicts": conflict_count,
        "title_abstract_pending": title_abstract_pending,
        "full_text_pending": full_text_pending,
        "extraction_total": extraction_total,
        "extraction_pending": extraction_pending,
        "extraction_validated": extraction_validated,
    }

    prisma = calculate_prisma(searches, articles)

    return render_template(
        "systematic_review.html",
        page="systematic_review",
        review=review,
        articles=articles,
        search_strategies=search_strategies,
        extractions=extractions,
        conflicts=conflicts,
        stats=stats,
        prisma=prisma,
    )

@app.route("/api/systematic-review/pubmed-search", methods=["POST"])
def systematic_review_pubmed_search():
    from db.db import get_conn
    from workers.plugins.pubmed_search import handle as pubmed_search_handle

    data = request.get_json(silent=True) or {}

    review_id = data.get("review_id")
    strategy_id = data.get("strategy_id")
    query = (data.get("query") or "").strip()
    max_results = data.get("max_results", 20)

    if not review_id:
        return jsonify({
            "ok": False,
            "error": "review_id es obligatorio"
        }), 400

    if not _review_in_current_project(review_id):
        return jsonify({
            "ok": False,
            "error": "Revisión no encontrada en el proyecto activo"
        }), 404

    project_id = current_project_id()

    if not query:
        return jsonify({
            "ok": False,
            "error": "La búsqueda de PubMed no puede estar vacía"
        }), 400

    try:
        max_results = int(max_results)
    except (TypeError, ValueError):
        return jsonify({
            "ok": False,
            "error": "max_results debe ser un número"
        }), 400

    max_results = max(1, min(max_results, 100))

    # Si se ejecuta una estrategia guardada,
    # verificamos que pertenece a esta revisión
    # y que la query no ha sido modificada.
    if strategy_id:

        with get_conn() as conn:
            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        review_id,
                        database_name,
                        query,
                        human_confirmed
                    FROM review_search_strategies rss
                    JOIN systematic_reviews sr
                      ON sr.id = rss.review_id
                    WHERE rss.id = %s
                      AND rss.review_id = %s
                      AND sr.project_id = %s
                    """,
                    (
                        strategy_id,
                        review_id,
                        project_id,
                    ),
                )

                strategy = cur.fetchone()

        if not strategy:
            return jsonify({
                "ok": False,
                "error": "La estrategia indicada no existe"
            }), 404

        (
            strategy_review_id,
            database_name,
            strategy_query,
            human_confirmed,
        ) = strategy

        if strategy_review_id != review_id:
            return jsonify({
                "ok": False,
                "error": "La estrategia no pertenece a esta revisión"
            }), 400

        if database_name != "PubMed":
            return jsonify({
                "ok": False,
                "error": "La estrategia no corresponde a PubMed"
            }), 400

        if not human_confirmed:
            return jsonify({
                "ok": False,
                "error": "La estrategia todavía no tiene confirmación humana"
            }), 400

        if query != (strategy_query or "").strip():
            return jsonify({
                "ok": False,
                "error":
                    "La query no coincide con la estrategia confirmada. "
                    "Vuelve a validar la estrategia antes de ejecutarla."
            }), 400

    try:
        result = pubmed_search_handle(
            f"pubmed-ui-{review_id}",
            {
                "project_id": project_id,
                "review_id": review_id,
                "strategy_id": strategy_id,
                "query": query,
                "max_results": max_results,
            },
        )

        return jsonify({
            "ok": True,
            "result": result,
        })

    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 500


@app.route("/api/systematic-review/ai-screening", methods=["POST"])
def systematic_review_ai_screening():
    from workers.plugins.screening import handle as screening_handle

    data = request.get_json(silent=True) or {}
    review_id = (data.get("review_id") or "").strip()

    if not review_id:
        return jsonify({
            "ok": False,
            "error": "review_id es obligatorio",
        }), 400

    if not _review_in_current_project(review_id):
        return jsonify({
            "ok": False,
            "error": "Revisión no encontrada en el proyecto activo",
        }), 404

    project_id = current_project_id()

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        research_question,
                        population,
                        intervention,
                        comparator,
                        outcomes,
                        inclusion_criteria,
                        exclusion_criteria
                    FROM systematic_reviews
                    WHERE id = %s
                      AND project_id = %s
                    """,
                    (review_id, project_id),
                )
                review = cur.fetchone()

        if not review:
            return jsonify({
                "ok": False,
                "error": "La revisión sistemática no existe",
            }), 404

        (
            research_question,
            population,
            intervention,
            comparator,
            outcomes,
            inclusion_criteria,
            exclusion_criteria,
        ) = review

        missing = []

        if not (research_question or "").strip():
            missing.append("pregunta de investigación")

        if not (inclusion_criteria or "").strip():
            missing.append("criterios de inclusión")

        if not (exclusion_criteria or "").strip():
            missing.append("criterios de exclusión")

        if missing:
            return jsonify({
                "ok": False,
                "error":
                    "No se puede ejecutar el screening IA. "
                    "Completa primero: " + ", ".join(missing),
            }), 400

        # No lanzar dos screenings simultáneos para la misma revisión.
        for task in list_tasks(limit=100, project_id=project_id):
            if task.get("queue") != "screening":
                continue

            if task.get("status") not in {"pending", "running"}:
                continue

            task_payload = task.get("payload") or {}

            if isinstance(task_payload, str):
                try:
                    task_payload = json.loads(task_payload)
                except (TypeError, json.JSONDecodeError):
                    task_payload = {}

            if task_payload.get("review_id") == review_id:
                return jsonify({
                    "ok": True,
                    "task_id": task["id"],
                    "queue": "screening",
                    "status": task["status"],
                    "already_running": True,
                }), 202

        # Comprobar si realmente queda algún artículo que analizar.
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT count(*)
                    FROM review_articles
                    WHERE review_id = %s
                      AND is_duplicate = false
                      AND title_abstract_status = 'pending'
                      AND ai_decision IS NULL
                    """,
                    (review_id,),
                )
                pending_count = cur.fetchone()[0]

        if pending_count == 0:
            return jsonify({
                "ok": True,
                "status": "completed",
                "screened": 0,
                "no_pending": True,
            })

        task_id = str(uuid.uuid4())

        payload = {
            "review_id": review_id,
            "project_id": project_id,
        }

        create_task(
            task_id,
            "screening",
            payload,
            project_id=project_id,
        )

        queue = Queue(
            "screening",
            connection=redis_conn,
            default_timeout=300,
        )

        try:
            queue.enqueue(
                screening_handle,
                task_id,
                payload,
                retry=DEFAULT_RETRY,
                job_id=task_id,
            )
        except Exception:
            from db.db import set_status
            set_status(
                task_id,
                "failed",
                error="No se pudo encolar la tarea de screening IA",
            )
            raise

        return jsonify({
            "ok": True,
            "task_id": task_id,
            "queue": "screening",
            "status": "pending",
            "pending_articles": pending_count,
        }), 202

    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 500


@app.route("/api/systematic-review/tasks/<task_id>", methods=["GET"])
def systematic_review_task_status(task_id):
    task = get_task(task_id)

    if not task:
        return jsonify({
            "ok": False,
            "error": "Tarea no encontrada",
        }), 404

    project_id = current_project_id()

    if task.get("project_id") != project_id:
        return jsonify({
            "ok": False,
            "error": "Tarea no encontrada en el proyecto activo",
        }), 404

    payload = task.get("payload") or {}

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            payload = {}

    review_id = payload.get("review_id")

    if review_id and not _review_in_current_project(review_id):
        return jsonify({
            "ok": False,
            "error": "La tarea no pertenece al proyecto activo",
        }), 404

    result = task.get("result")

    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (TypeError, json.JSONDecodeError):
            pass

    return jsonify({
        "ok": True,
        "task_id": task["id"],
        "queue": task.get("queue"),
        "status": task.get("status"),
        "result": result,
        "error": task.get("error"),
    })


@app.route(
    "/api/systematic-review/full-text-retrieval",
    methods=["POST"],
)
def systematic_review_full_text_retrieval():
    from db.db import log_review_audit

    data = request.get_json(silent=True) or {}

    review_id = data.get("review_id")
    article_id = data.get("article_id")
    status = (
        data.get("status")
        or ""
    ).strip().lower()

    allowed_statuses = {
        "not_sought",
        "sought",
        "retrieved",
        "not_retrieved",
    }

    if not review_id:
        return jsonify({
            "ok": False,
            "error": "review_id es obligatorio",
        }), 400

    if not article_id:
        return jsonify({
            "ok": False,
            "error": "article_id es obligatorio",
        }), 400

    if status not in allowed_statuses:
        return jsonify({
            "ok": False,
            "error":
                "status debe ser not_sought, sought, "
                "retrieved o not_retrieved",
        }), 400

    if not _article_in_current_project(article_id, review_id):
        return jsonify({
            "ok": False,
            "error": "Artículo no encontrado en el proyecto activo",
        }), 404

    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    is_duplicate,
                    full_text_status,
                    full_text_retrieval_status,
                    full_text_available
                FROM review_articles
                WHERE id = %s
                  AND review_id = %s
                """,
                (article_id, review_id),
            )

            article = cur.fetchone()

            if not article:
                return jsonify({
                    "ok": False,
                    "error": "Artículo no encontrado",
                }), 404

            if article[1]:
                return jsonify({
                    "ok": False,
                    "error":
                        "Un artículo duplicado no requiere "
                        "recuperación de texto completo",
                }), 400

            if article[2] == "not_started":
                return jsonify({
                    "ok": False,
                    "error":
                        "El artículo todavía no ha pasado "
                        "a la fase de texto completo",
                }), 409

            cur.execute(
                """
                SELECT COUNT(*)
                FROM review_screening_decisions
                WHERE review_id = %s
                  AND article_id = %s
                  AND stage = 'full_text'
                """,
                (review_id, article_id),
            )

            full_text_decisions = cur.fetchone()[0]

            if (
                full_text_decisions > 0
                and status != "retrieved"
            ):
                return jsonify({
                    "ok": False,
                    "error":
                        "No se puede cambiar el texto completo "
                        "a no disponible porque ya existen "
                        "decisiones de cribado",
                }), 409

            full_text_available = status == "retrieved"

            previous_retrieval_status = article[3]
            previous_full_text_available = article[4]

            cur.execute(
                """
                UPDATE review_articles
                SET
                    full_text_retrieval_status = %s,
                    full_text_available = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                  AND review_id = %s
                """,
                (
                    status,
                    full_text_available,
                    article_id,
                    review_id,
                ),
            )

            log_review_audit(
                project_id=current_project_id(),
                review_id=review_id,
                article_id=article_id,
                action="full_text_retrieval_status_changed",
                actor_type="system",
                actor_id="dashboard_api",
                stage="full_text",
                before_state={
                    "full_text_retrieval_status": previous_retrieval_status,
                    "full_text_available": previous_full_text_available,
                },
                after_state={
                    "full_text_retrieval_status": status,
                    "full_text_available": full_text_available,
                },
                details={
                    "source": "dashboard_api",
                    "requested_status": status,
                },
                conn=conn,
            )

        return jsonify({
            "ok": True,
            "article_id": article_id,
            "status": status,
            "full_text_available": full_text_available,
        })

    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 500



@app.route(
    "/api/systematic-review/full-text-upload",
    methods=["POST"],
)
def systematic_review_full_text_upload():
    """
    Sube e indexa el texto completo de un artículo de una revisión.

    Flujo:
    - valida revisión y artículo,
    - obtiene el project_id real de la revisión,
    - extrae el texto del fichero,
    - lo indexa en documents/rag_chunks,
    - enlaza review_articles.full_text_document_id,
    - marca el informe como recuperado.

    Cada nueva subida recibe un doc_id único para evitar que queden
    chunks obsoletos de versiones anteriores del mismo PDF.
    """
    import uuid
    from db.db import log_review_audit

    file = request.files.get("file")
    review_id = (request.form.get("review_id") or "").strip()
    article_id = (request.form.get("article_id") or "").strip()

    if not review_id:
        return jsonify({
            "ok": False,
            "error": "review_id es obligatorio",
        }), 400

    if not article_id:
        return jsonify({
            "ok": False,
            "error": "article_id es obligatorio",
        }), 400

    if not file or not file.filename:
        return jsonify({
            "ok": False,
            "error": "Debe seleccionarse un archivo de texto completo",
        }), 400

    if not _article_in_current_project(article_id, review_id):
        return jsonify({
            "ok": False,
            "error": "Artículo no encontrado en el proyecto activo",
        }), 404

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                ra.id,
                ra.is_duplicate,
                ra.full_text_status,
                ra.full_text_document_id,
                ra.full_text_retrieval_status,
                ra.full_text_available,
                sr.project_id
            FROM review_articles ra
            JOIN systematic_reviews sr
              ON sr.id = ra.review_id
            WHERE ra.id = %s
              AND ra.review_id = %s
              AND sr.project_id = %s
            """,
            (
                article_id,
                review_id,
                current_project_id(),
            ),
        )

        article = cur.fetchone()

    if not article:
        return jsonify({
            "ok": False,
            "error": "Artículo no encontrado en esta revisión",
        }), 404

    (
        _article_id,
        is_duplicate,
        full_text_status,
        previous_document_id,
        previous_retrieval_status,
        previous_full_text_available,
        project_id,
    ) = article

    if is_duplicate:
        return jsonify({
            "ok": False,
            "error": (
                "No se puede asociar texto completo "
                "a un registro marcado como duplicado"
            ),
        }), 400

    if full_text_status == "not_started":
        return jsonify({
            "ok": False,
            "error": (
                "El artículo todavía no ha alcanzado "
                "la fase de texto completo"
            ),
        }), 409

    from common.document_service import upload_and_index
    document_id = None
    try:
        doc, reused = upload_and_index(project_id, file, role="scientific_evidence")
        document_id = doc["doc_id"]
        n_chunks = doc["n_chunks"]
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE review_articles
                SET
                    full_text_document_id = %s,
                    full_text_retrieval_status = 'retrieved',
                    full_text_available = TRUE,
                    updated_at = NOW()
                WHERE id = %s
                  AND review_id = %s
                """,
                (
                    document_id,
                    article_id,
                    review_id,
                ),
            )

            log_review_audit(
                project_id=project_id,
                review_id=review_id,
                article_id=article_id,
                action="full_text_uploaded",
                actor_type="system",
                actor_id="dashboard_api",
                stage="full_text",
                before_state={
                    "full_text_document_id": previous_document_id,
                    "full_text_retrieval_status": previous_retrieval_status,
                    "full_text_available": previous_full_text_available,
                },
                after_state={
                    "full_text_document_id": document_id,
                    "full_text_retrieval_status": "retrieved",
                    "full_text_available": True,
                },
                details={
                    "filename": file.filename,
                    "content_type": file.content_type,
                    "n_chunks": n_chunks,
                    "replaced_document_id": previous_document_id,
                },
                conn=conn,
            )

        if (
            previous_document_id
            and previous_document_id != document_id
        ):
            try:
                with get_conn() as conn, conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COUNT(*)
                        FROM review_articles
                        WHERE full_text_document_id = %s
                        """,
                        (previous_document_id,),
                    )
                    remaining_references = cur.fetchone()[0]

                if remaining_references == 0:
                    deleted = delete_document(previous_document_id)
                    if not deleted:
                        log_review_audit(
                            project_id=project_id, review_id=review_id, article_id=article_id,
                            action="shared_document_retained", actor_type="system",
                            actor_id="dashboard_api", stage="full_text",
                            details={"document_id": previous_document_id,
                                     "reason": "document still referenced by Thesis"},
                        )
            except Exception:
                app.logger.warning(
                    "No se pudo comprobar/eliminar el documento anterior %s "
                    "del artículo %s",
                    previous_document_id,
                    article_id,
                )

        return jsonify({
            "ok": True,
            "article_id": article_id,
            "document_id": document_id,
            "filename": file.filename,
            "n_chunks": n_chunks,
            "full_text_retrieval_status": "retrieved",
            "full_text_available": True,
        }), 201

    except (ValueError, OSError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        try:
            delete_document(document_id)
        except Exception:
            pass

        return jsonify({
            "ok": False,
            "error": (
                "No se pudo indexar y asociar "
                f"el texto completo: {exc}"
            ),
        }), 500


@app.route("/api/systematic-review/human-decision", methods=["POST"])
def systematic_review_human_decision():
    from workers.plugins.human_screening import handle as human_screening_handle

    data = request.get_json(silent=True) or {}

    review_id = data.get("review_id")
    article_id = data.get("article_id")
    pmid = data.get("pmid")
    reviewer_id = (data.get("reviewer_id") or "").strip()
    stage = (data.get("stage") or "title_abstract").strip().lower()
    decision = (data.get("decision") or "").strip().lower()
    exclusion_reason = data.get("exclusion_reason")
    exclusion_reason_code = data.get("exclusion_reason_code")
    notes = data.get("notes")

    if not review_id:
        return jsonify({"ok": False, "error": "review_id es obligatorio"}), 400

    if not article_id and not pmid:
        return jsonify({
            "ok": False,
            "error": "article_id o pmid es obligatorio"
        }), 400

    if not reviewer_id:
        return jsonify({
            "ok": False,
            "error": "reviewer_id es obligatorio"
        }), 400

    if not _review_in_current_project(review_id):
        return jsonify({
            "ok": False,
            "error": "Revisión no encontrada en el proyecto activo"
        }), 404

    # Normalizar siempre el artículo a su ID interno.
    # El frontend/API puede enviar PMID, pero el resto del flujo
    # trabaja de forma segura con article_id.
    if not article_id and pmid:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM review_articles
                WHERE review_id = %s
                  AND pmid = %s
                LIMIT 1
                """,
                (review_id, str(pmid)),
            )
            row = cur.fetchone()

        if not row:
            return jsonify({
                "ok": False,
                "error": "No se encontró el PMID en esta revisión"
            }), 404

        article_id = row[0]

    if article_id and not _article_in_current_project(
        article_id,
        review_id,
    ):
        return jsonify({
            "ok": False,
            "error": "Artículo no encontrado en el proyecto activo"
        }), 404

    if reviewer_id == "adjudicator":
        return jsonify({
            "ok": False,
            "error": "El adjudicador solo puede resolver conflictos"
        }), 400

    if stage not in {"title_abstract", "full_text"}:
        return jsonify({
            "ok": False,
            "error": "stage debe ser title_abstract o full_text"
        }), 400

    if decision not in {"include", "exclude", "uncertain"}:
        return jsonify({
            "ok": False,
            "error": "decision debe ser include, exclude o uncertain"
        }), 400

    if stage == "full_text":
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT full_text_retrieval_status
                FROM review_articles
                WHERE id = %s
                  AND review_id = %s
                """,
                (article_id, review_id),
            )

            row = cur.fetchone()

        if not row:
            return jsonify({
                "ok": False,
                "error": "Artículo no encontrado"
            }), 404

        if row[0] != "retrieved":
            return jsonify({
                "ok": False,
                "error":
                    "El texto completo debe estar recuperado "
                    "antes de realizar el cribado"
            }), 409

    if decision == "exclude" and not (
        exclusion_reason or exclusion_reason_code
    ):
        return jsonify({
            "ok": False,
            "error":
                "El motivo o código de exclusión es obligatorio"
        }), 400

    try:
        result = human_screening_handle(
            f"human-ui-{article_id or pmid}-{stage}-{reviewer_id}",
            {
                "project_id": current_project_id(),
                "review_id": review_id,
                "article_id": article_id,
                "pmid": pmid,
                "reviewer_id": reviewer_id,
                "stage": stage,
                "decision": decision,
                "exclusion_reason": exclusion_reason,
                "exclusion_reason_code": exclusion_reason_code,
                "notes": notes,
            },
        )

        return jsonify({"ok": True, "result": result})

    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/systematic-review/resolve-conflict", methods=["POST"])
def systematic_review_resolve_conflict():
    from workers.plugins.resolve_screening_conflict import (
        handle as resolve_conflict_handle,
    )

    data = request.get_json(silent=True) or {}

    review_id = data.get("review_id")
    article_id = data.get("article_id")
    stage = (data.get("stage") or "").strip().lower()
    resolution = (data.get("resolution") or "").strip().lower()
    resolved_by = (data.get("resolved_by") or "").strip()
    resolution_notes = data.get("resolution_notes")
    exclusion_reason = data.get("exclusion_reason")
    exclusion_reason_code = data.get("exclusion_reason_code")

    if not review_id:
        return jsonify({"ok": False, "error": "review_id es obligatorio"}), 400

    if not article_id:
        return jsonify({"ok": False, "error": "article_id es obligatorio"}), 400

    if stage not in {"title_abstract", "full_text"}:
        return jsonify({
            "ok": False,
            "error": "stage debe ser title_abstract o full_text"
        }), 400

    if resolution not in {"include", "exclude", "uncertain"}:
        return jsonify({
            "ok": False,
            "error":
                "resolution debe ser include, exclude o uncertain"
        }), 400

    if not resolved_by:
        return jsonify({
            "ok": False,
            "error": "resolved_by es obligatorio"
        }), 400

    if not _article_in_current_project(article_id, review_id):
        return jsonify({
            "ok": False,
            "error": "Artículo no encontrado en el proyecto activo"
        }), 404

    if resolution == "exclude" and not (
        exclusion_reason or exclusion_reason_code
    ):
        return jsonify({
            "ok": False,
            "error":
                "El motivo o código de exclusión es obligatorio"
        }), 400

    try:
        result = resolve_conflict_handle(
            f"resolve-ui-{article_id}-{stage}",
            {
                "project_id": current_project_id(),
                "review_id": review_id,
                "article_id": article_id,
                "stage": stage,
                "resolution": resolution,
                "resolved_by": resolved_by,
                "resolution_notes": resolution_notes,
                "exclusion_reason": exclusion_reason,
                "exclusion_reason_code": exclusion_reason_code,
            },
        )

        return jsonify({"ok": True, "result": result})

    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

@app.route("/api/systematic-review/human-data-extraction", methods=["POST"])
def systematic_review_human_data_extraction():
    from workers.plugins.human_data_extraction import (
        handle as human_data_extraction_handle,
    )

    data = request.get_json(silent=True) or {}

    extraction_id = data.get("extraction_id")
    validation_status = data.get("validation_status")
    reviewer_id = data.get("reviewer_id")
    reviewer_notes = data.get("reviewer_notes")

    if not extraction_id:
        return jsonify({
            "ok": False,
            "error": "extraction_id es obligatorio",
        }), 400

    if validation_status not in {
        "accepted",
        "edited",
        "rejected",
    }:
        return jsonify({
            "ok": False,
            "error": (
                "validation_status debe ser "
                "accepted, edited o rejected"
            ),
        }), 400

    if not reviewer_id:
        return jsonify({
            "ok": False,
            "error": "reviewer_id es obligatorio",
        }), 400

    if not _extraction_in_current_project(extraction_id):
        return jsonify({
            "ok": False,
            "error": "Extracción no encontrada en el proyecto activo",
        }), 404

    payload = {
        "project_id": current_project_id(),
        "extraction_id": extraction_id,
        "validation_status": validation_status,
        "reviewer_id": reviewer_id,
        "reviewer_notes": reviewer_notes,
    }

    if "human_value" in data:
        payload["human_value"] = data.get("human_value")

    try:
        result = human_data_extraction_handle(
            f"human-extraction-ui-{extraction_id}",
            payload,
        )

        return jsonify({
            "ok": True,
            "result": result,
        })

    except ValueError as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 400

    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 500
@app.route("/settings")
def settings_page():
    services = load_services()
    env_example_path = BASE_DIR / ".env.example"
    env_vars = []
    if env_example_path.exists():
        for line in env_example_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, default = line.partition("=")
                env_vars.append({"key": key, "default": default})
    yaml_content = CONFIG_PATH.read_text() if CONFIG_PATH.exists() else ""
    return render_template("settings.html", page="settings", services=services, env_vars=env_vars, yaml_content=yaml_content)


@app.route("/api/settings/services-yaml", methods=["POST"])
def settings_save_yaml():
    """
    Guarda config/services.yaml editado desde la interfaz. Valida que sea
    YAML válido antes de escribir, para no dejar el fichero roto y tumbar
    el panel en el siguiente arranque.
    """
    payload = request.get_json(force=True) or {}
    content = payload.get("content", "")
    try:
        parsed = yaml.safe_load(content)
        if not isinstance(parsed, dict) or "services" not in parsed:
            return jsonify({"error": "el YAML es válido pero no tiene la forma esperada (falta la clave 'services')"}), 400
    except yaml.YAMLError as e:
        return jsonify({"error": f"YAML inválido: {e}"}), 400
    CONFIG_PATH.write_text(content)
    return jsonify({"saved": True})


# --- Backup / Restore ---

def _db_table_counts():
    tables = [
        "tasks",
        "audit_log",
        "rag_chunks",
        "documents",
        "collections",
        "n8n_integrations",
        "systematic_reviews",
        "review_articles",
        "review_audit_log",
        "review_search_strategies",
        "review_searches",
        "review_screening_decisions",
        "review_screening_conflicts",
        "review_extraction_fields",
        "review_extractions",
    ]
    counts = {}
    with get_conn() as conn, conn.cursor() as cur:
        for t in tables:
            try:
                cur.execute(f"SELECT count(*) FROM {t}")
                counts[t] = cur.fetchone()[0]
            except Exception:
                conn.rollback()
                counts[t] = None
    return counts


@app.route("/api/settings/backup/export")
def backup_export():
    try:
        zip_path = export_backup(CONFIG_PATH, _db_table_counts())
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
    return send_file(zip_path, as_attachment=True, download_name=zip_path.name)


@app.route("/api/settings/backup/import", methods=["POST"])
def backup_import():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "no se ha recibido ningún fichero"}), 400
    restore_yaml = request.form.get("restore_yaml") == "true"
    try:
        result = import_backup(file, restore_yaml, CONFIG_PATH)
    except (ValueError, RuntimeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result)


@app.route("/api/status")
def api_status():
    services = load_services()
    return jsonify({
        "services": [status_for(s) for s in services],
        "metrics": system_metrics(),
        "queues": queue_depths(),
        "docker_available": docker_available(),
        "llm_gateway": llm_gateway_metrics(),
    })


# --- Arranque/parada NATIVOS (como antes, pero ahora con log a fichero) ---

def _log_file(service_id):
    return open(LOGS_DIR / f"{service_id}.log", "a")


@app.route("/api/start/<service_id>", methods=["POST"])
def start_service(service_id):
    svc = get_service(service_id)
    if not svc:
        return jsonify({"error": "unknown service"}), 404
    logf = _log_file(service_id)
    proc = subprocess.Popen(svc["start_command"], shell=True, cwd=BASE_DIR, stdout=logf, stderr=subprocess.STDOUT)
    _started_pids[service_id] = proc.pid
    return jsonify({"started": service_id, "pid": proc.pid})


@app.route("/api/stop/<service_id>", methods=["POST"])
def stop_service(service_id):
    svc = get_service(service_id)
    if not svc:
        return jsonify({"error": "unknown service"}), 404
    subprocess.run(svc["stop_command"], shell=True, cwd=BASE_DIR)
    return jsonify({"stopped": service_id})


@app.route("/api/service/<service_id>/metrics")
def service_metrics(service_id):
    """
    CPU/RAM/uptime del proceso concreto, si el panel lo arrancó él mismo
    (y por tanto conoce su PID). Si no, o si ya no existe, lo dice.
    """
    pid = _started_pids.get(service_id)
    if not pid:
        return jsonify({"available": False, "reason": "este panel no arrancó este proceso (o se reinició el panel desde entonces)"})
    try:
        p = psutil.Process(pid)
        with p.oneshot():
            return jsonify({
                "available": True,
                "pid": pid,
                "cpu_percent": p.cpu_percent(interval=0.2),
                "ram_mb": round(p.memory_info().rss / (1024 * 1024), 1),
                "uptime_seconds": round(time.time() - p.create_time()),
                "status": p.status(),
            })
    except psutil.NoSuchProcess:
        return jsonify({"available": False, "reason": "el proceso ya no existe"})


@app.route("/api/tasks-summary")
def tasks_summary():
    project_id = current_project_id()
    counts = task_counts_by_status(project_id=project_id)
    return jsonify({
        "running": counts.get("running", 0),
        "pending": counts.get("pending", 0),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
    })


@app.route("/api/tasks")
def tasks_proxy():
    """Devuelve únicamente las tareas del proyecto activo."""
    status = request.args.get("status")

    try:
        limit = int(request.args.get("limit", 20))
    except (TypeError, ValueError):
        return jsonify({
            "error": "limit debe ser un número entero",
        }), 400

    limit = max(1, min(limit, 500))
    project_id = current_project_id()

    return jsonify(
        list_tasks(
            status=status,
            limit=limit,
            project_id=project_id,
        )
    )


@app.route("/api/start-all", methods=["POST"])
def start_all():
    for s in load_services():
        logf = _log_file(s["id"])
        subprocess.Popen(s["start_command"], shell=True, cwd=BASE_DIR, stdout=logf, stderr=subprocess.STDOUT)
    return jsonify({"started": "all"})


@app.route("/api/stop-all", methods=["POST"])
def stop_all():
    for s in reversed(load_services()):
        subprocess.run(s["stop_command"], shell=True, cwd=BASE_DIR)
    return jsonify({"stopped": "all"})


# --- Control de Docker por servicio ---

def _run_docker_compose(*args, timeout=30):
    if not docker_available():
        return {"ok": False, "error": "Docker no está instalado o no está en el PATH de este proceso."}
    try:
        result = subprocess.run(
            ["docker", "compose", *args],
            cwd=BASE_DIR, capture_output=True, text=True, timeout=timeout,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"docker compose no respondió en {timeout}s"}
    except FileNotFoundError:
        return {"ok": False, "error": "Comando 'docker' no encontrado en este sistema."}


@app.route("/api/docker/<service_id>/<action>", methods=["POST"])
def docker_control(service_id, action):
    if action not in ("start", "stop", "restart"):
        return jsonify({"error": f"acción desconocida '{action}', usa start/stop/restart"}), 400

    svc = get_service(service_id)
    if not svc:
        return jsonify({"error": "servicio desconocido"}), 404

    docker_service = svc.get("docker_service")
    if not docker_service:
        return jsonify({"error": f"'{svc['name']}' no tiene equivalente en docker-compose.yml (se gestiona de forma nativa)"}), 400

    action_map = {"start": ["up", "-d", docker_service], "stop": ["stop", docker_service], "restart": ["restart", docker_service]}
    result = _run_docker_compose(*action_map[action])
    status_code = 200 if result.get("ok") else 502
    return jsonify(result), status_code


# --- Logs en vivo (SSE) ---

@app.route("/logs/<service_id>/stream")
def log_stream(service_id):
    svc = get_service(service_id)
    if not svc:
        return jsonify({"error": "servicio desconocido"}), 404

    log_path = LOGS_DIR / f"{service_id}.log"
    docker_service = svc.get("docker_service")
    use_docker = request.args.get("source") == "docker" or (not log_path.exists() and docker_service)

    def native_source():
        # Si el fichero no existe todavía, espera a que aparezca (el
        # servicio puede arrancarse justo después de abrir el stream).
        for _ in range(30):
            if log_path.exists():
                break
            time.sleep(1)
        else:
            yield "event: error\ndata: sin logs todavía para este servicio\n\n"
            return

        with open(log_path, "r") as f:
            f.seek(0, os.SEEK_END)  # solo líneas nuevas a partir de ahora
            while True:
                line = f.readline()
                if line:
                    yield f"data: {json.dumps(line.rstrip())}\n\n"
                else:
                    time.sleep(0.5)

    def docker_source():
        if not docker_service:
            yield "event: error\ndata: este servicio no tiene equivalente en Docker\n\n"
            return
        if not docker_available():
            yield "event: error\ndata: Docker no está disponible en este sistema\n\n"
            return
        proc = subprocess.Popen(
            ["docker", "compose", "logs", "-f", "--tail", "50", docker_service],
            cwd=BASE_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            for line in proc.stdout:
                yield f"data: {json.dumps(line.rstrip())}\n\n"
        finally:
            proc.terminate()

    generator = docker_source() if use_docker else native_source()
    return Response(stream_with_context(generator), mimetype="text/event-stream")


def find_free_port(start_port=8765, end_port=8795):
    import socket

    for port in range(start_port, end_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue

    raise RuntimeError(
        f"No hay puertos libres entre {start_port} y {end_port}"
    )


if __name__ == "__main__":
    ensure_default_collection()

    preferred_port = int(os.environ.get("LOCAL_AI_DASHBOARD_PORT", "8765"))

    # El dashboard usa un puerto estable porque services.yaml y el proxy
    # dependen de este puerto concreto.
    if port_is_open("127.0.0.1", preferred_port):
        raise RuntimeError(
            f"El puerto del dashboard {preferred_port} ya está ocupado. "
            "Detén el proceso anterior antes de iniciar el stack."
        )

    dashboard_port = preferred_port
    DASHBOARD_RUNTIME_PORT = dashboard_port

    print("")
    print("=" * 60)
    print(f"Local AI Studio: http://127.0.0.1:{dashboard_port}")
    if dashboard_port != preferred_port:
        print(
            f"Puerto {preferred_port} ocupado; "
            f"se ha seleccionado automáticamente {dashboard_port}."
        )
    else:
        print(f"Puerto {dashboard_port} disponible.")
    print("=" * 60)
    print("")

    app.run(
        host="127.0.0.1",
        port=dashboard_port,
        debug=False,
    )
