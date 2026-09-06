"""
system_checks.py

Comprobaciones reales del entorno, usadas por el asistente de primera
puesta en marcha (onboarding) y por el centro de diagnóstico. Cada
función devuelve algo concreto (ok/fail + detalle), nunca solo un
booleano — para que la interfaz pueda explicar QUÉ falla y sugerir un
arreglo, no solo pintar un semáforo en rojo.
"""

import shutil
import socket
import subprocess

import requests


def check_python():
    return {"name": "Python", "ok": True, "detail": "corriendo (obviamente)", "required": True}


def check_docker():
    ok = shutil.which("docker") is not None
    return {"name": "Docker", "ok": ok, "detail": "instalado" if ok else "no encontrado (opcional si usas modo nativo)", "required": False}


def check_postgres(host="127.0.0.1", port=5432, timeout=1.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"name": "PostgreSQL", "ok": True, "detail": f"puerto {port} abierto", "required": True}
    except OSError as e:
        return {"name": "PostgreSQL", "ok": False, "detail": str(e), "required": True}


def check_redis(host="127.0.0.1", port=6379, timeout=1.0):
    try:
        from redis import Redis
        r = Redis(host=host, port=port, socket_connect_timeout=timeout)
        r.ping()
        return {"name": "Redis", "ok": True, "detail": "responde a PING", "required": True}
    except Exception as e:
        return {"name": "Redis", "ok": False, "detail": str(e), "required": True}


def check_ollama(url="http://127.0.0.1:11434", timeout=1.5):
    try:
        r = requests.get(f"{url}/api/tags", timeout=timeout)
        if r.status_code == 200:
            models = [m.get("name") for m in r.json().get("models", [])]
            return {"name": "Ollama", "ok": True, "detail": f"{len(models)} modelo(s)", "models": models, "required": False}
        return {"name": "Ollama", "ok": False, "detail": f"HTTP {r.status_code} (opcional si solo usarás APIs externas)", "models": [], "required": False}
    except requests.RequestException as e:
        return {"name": "Ollama", "ok": False, "detail": f"{e} (opcional si solo usarás APIs externas)", "models": [], "required": False}


def run_all_checks():
    ollama = check_ollama()
    all_checks = {
        "python": check_python(),
        "docker": check_docker(),
        "postgres": check_postgres(),
        "redis": check_redis(),
        "ollama": ollama,
    }
    # Docker y Ollama son opcionales para poder continuar: Docker no hace
    # falta en modo nativo, y Ollama no hace falta si el proyecto solo va
    # a usar un proveedor externo (modo "local + external APIs"). Python,
    # Postgres y Redis sí son imprescindibles siempre.
    required = ["python", "postgres", "redis"]
    checks = list(all_checks.values())
    has_model = bool(ollama.get("models"))
    return {
        "checks": checks,
        "all_ok": all(all_checks[k]["ok"] for k in required),
        "has_model": has_model,
    }


def pull_recommended_model(model="llama3.1", url="http://127.0.0.1:11434"):
    """
    Lanza `ollama pull` en segundo plano y devuelve inmediatamente — la
    descarga puede tardar minutos, no tiene sentido bloquear la petición
    HTTP esperándola. La interfaz consulta el progreso reconsultando
    check_ollama() (aparecerá en `models` en cuanto termine).
    """
    if not shutil.which("ollama"):
        return {"started": False, "error": "el comando 'ollama' no está instalado en este sistema"}
    subprocess.Popen(["ollama", "pull", model])
    return {"started": True, "model": model}
