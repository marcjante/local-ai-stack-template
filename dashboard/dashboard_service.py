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
import time
from pathlib import Path

import psutil
import requests
import yaml
from flask import Flask, jsonify, render_template, request, Response, stream_with_context

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "services.yaml"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

app = Flask(__name__, template_folder="templates")


def load_services():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("services", [])


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

    if endpoint and port:
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


def system_metrics():
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "ram_percent": psutil.virtual_memory().percent,
    }


def docker_available() -> bool:
    return shutil.which("docker") is not None


@app.route("/")
def index():
    services = load_services()
    statuses = [status_for(s) for s in services]
    return render_template(
        "index.html", services=statuses, metrics=system_metrics(),
        queues=queue_depths(), docker_ok=docker_available(),
    )


@app.route("/api/status")
def api_status():
    services = load_services()
    return jsonify({
        "services": [status_for(s) for s in services],
        "metrics": system_metrics(),
        "queues": queue_depths(),
        "docker_available": docker_available(),
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
    subprocess.Popen(svc["start_command"], shell=True, cwd=BASE_DIR, stdout=logf, stderr=subprocess.STDOUT)
    return jsonify({"started": service_id})


@app.route("/api/stop/<service_id>", methods=["POST"])
def stop_service(service_id):
    svc = get_service(service_id)
    if not svc:
        return jsonify({"error": "unknown service"}), 404
    subprocess.run(svc["stop_command"], shell=True, cwd=BASE_DIR)
    return jsonify({"stopped": service_id})


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8090, debug=False)
