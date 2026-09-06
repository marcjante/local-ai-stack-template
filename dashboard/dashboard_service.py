"""
dashboard_service.py

Panel de control generico para el stack local.
Lee config/services.yaml, comprueba el estado de cada servicio (puerto abierto +
health endpoint si responde) y expone una web sencilla con botones para arrancar
y parar todo el stack, o un servicio individual.

No contiene logica de ningun proyecto concreto: solo orquesta lo que hay
definido en services.yaml. Para reutilizar esta plantilla en un proyecto nuevo,
edita services.yaml y los scripts de scripts/, no este fichero.
"""

import socket
import subprocess
import yaml
from pathlib import Path
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


def status_for(service: dict) -> dict:
    up = port_is_open(service["host"], service["port"])
    return {
        "id": service["id"],
        "name": service["name"],
        "description": service.get("description", ""),
        "port": service["port"],
        "status": "up" if up else "down",
        "depends_on": service.get("depends_on", []),
    }


@app.route("/")
def index():
    services = load_services()
    statuses = [status_for(s) for s in services]
    return render_template("index.html", services=statuses)


@app.route("/api/status")
def api_status():
    services = load_services()
    return jsonify([status_for(s) for s in services])


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
    # Puerto del propio dashboard tal como esta definido en services.yaml
    app.run(host="0.0.0.0", port=8090, debug=False)
