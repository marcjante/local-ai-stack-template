"""
dashboard_service.py

Panel de control genérico para el stack local. Para cada servicio de
config/services.yaml:
  - Si tiene health_endpoint, hace un GET real a http://host:port/health_endpoint
    y solo lo marca "activo" si responde 200 — puerto abierto ya NO es
    suficiente por sí solo.
  - Si no tiene health_endpoint (ej. Redis, Postgres), sigue comprobando
    solo el puerto, porque no hablan HTTP.

También muestra métricas básicas de la máquina (CPU/RAM) y, si Redis
está disponible, la profundidad de las colas — diagnóstico real en vez
de un simple sí/no.

No contiene lógica de ningún proyecto concreto: solo orquesta lo que hay
definido en services.yaml. Para reutilizar esta plantilla en un proyecto
nuevo, edita services.yaml y los scripts de scripts/, no este fichero.
"""

import socket
import subprocess
from pathlib import Path

import psutil
import requests
import yaml
from flask import Flask, jsonify, render_template

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "services.yaml"

app = Flask(__name__, template_folder="templates")


def load_services():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("services", [])


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
        # Sin puerto propio (ej. workers de RQ): no hay forma directa de
        # comprobar su salud desde aquí. Se ve indirectamente por si la
        # cola que consumen no deja de crecer (ver profundidad de colas).
        check_type = "n/a"
        status = "unknown"

    return {
        "id": service["id"],
        "name": service["name"],
        "description": service.get("description", ""),
        "port": port,
        "status": status,
        "check_type": check_type,
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


@app.route("/")
def index():
    services = load_services()
    statuses = [status_for(s) for s in services]
    return render_template("index.html", services=statuses, metrics=system_metrics(), queues=queue_depths())


@app.route("/api/status")
def api_status():
    services = load_services()
    return jsonify({
        "services": [status_for(s) for s in services],
        "metrics": system_metrics(),
        "queues": queue_depths(),
    })


@app.route("/api/start/<service_id>", methods=["POST"])
def start_service(service_id):
    services = {s["id"]: s for s in load_services()}
    svc = services.get(service_id)
    if not svc:
        return jsonify({"error": "unknown service"}), 404
    subprocess.Popen(svc["start_command"], shell=True, cwd=BASE_DIR)
    return jsonify({"started": service_id})


@app.route("/api/stop/<service_id>", methods=["POST"])
def stop_service(service_id):
    services = {s["id"]: s for s in load_services()}
    svc = services.get(service_id)
    if not svc:
        return jsonify({"error": "unknown service"}), 404
    subprocess.run(svc["stop_command"], shell=True, cwd=BASE_DIR)
    return jsonify({"stopped": service_id})


@app.route("/api/start-all", methods=["POST"])
def start_all():
    for s in load_services():
        subprocess.Popen(s["start_command"], shell=True, cwd=BASE_DIR)
    return jsonify({"started": "all"})


@app.route("/api/stop-all", methods=["POST"])
def stop_all():
    for s in reversed(load_services()):
        subprocess.run(s["stop_command"], shell=True, cwd=BASE_DIR)
    return jsonify({"stopped": "all"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8090, debug=False)
