"""
model_manager.py

Gestión de modelos de Ollama desde el panel: ver qué hay instalado (de
verdad, consultando Ollama, no una lista inventada), instalar/borrar, y
un benchmark real con los tiempos que Ollama ya devuelve en cada
respuesta — no hace falta instrumentación aparte.
"""

import os
import shutil
import subprocess
import time

import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

# Catálogo curado de modelos "recomendados" — Ollama no tiene una API
# pública de catálogo consultable sin acceso a internet real, así que
# esto es una lista mantenida a mano. Se filtra contra lo ya instalado.
CURATED_AVAILABLE = [
    {"name": "gemma3:4b", "approx_size": "~3.3 GB"},
    {"name": "mistral:7b", "approx_size": "~4.1 GB"},
    {"name": "qwen2.5:7b", "approx_size": "~4.4 GB"},
    {"name": "llama3.1:8b", "approx_size": "~4.7 GB"},
    {"name": "phi3:mini", "approx_size": "~2.2 GB"},
]


def _format_size(n_bytes) -> str:
    if not n_bytes:
        return "—"
    gb = n_bytes / (1024 ** 3)
    return f"{gb:.1f} GB"


def list_installed():
    """Modelos instalados de verdad, consultando Ollama."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        r.raise_for_status()
        models = r.json().get("models", [])
        return [
            {"name": m["name"], "size": _format_size(m.get("size")), "modified_at": m.get("modified_at")}
            for m in models
        ], None
    except requests.RequestException as e:
        return [], str(e)


def list_available(installed_names: set):
    return [m for m in CURATED_AVAILABLE if m["name"] not in installed_names]


def install_model(model_name: str) -> dict:
    """
    Lanza la descarga en segundo plano — puede tardar minutos, no tiene
    sentido bloquear la petición HTTP. La interfaz vuelve a consultar
    list_installed() para ver cuándo termina.
    """
    if shutil.which("ollama"):
        subprocess.Popen(["ollama", "pull", model_name])
        return {"started": True, "model": model_name, "via": "cli"}
    # Sin el binario 'ollama' en el PATH (ej. Ollama corriendo en Docker
    # o en otra máquina): usar la API HTTP directamente.
    try:
        requests.post(f"{OLLAMA_URL}/api/pull", json={"name": model_name}, timeout=3)
        return {"started": True, "model": model_name, "via": "api"}
    except requests.RequestException as e:
        return {"started": False, "error": str(e)}


def delete_model(model_name: str) -> dict:
    try:
        r = requests.delete(f"{OLLAMA_URL}/api/delete", json={"name": model_name}, timeout=10)
        if r.status_code == 200:
            return {"deleted": model_name}
        return {"error": f"Ollama devolvió {r.status_code}: {r.text[:200]}"}
    except requests.RequestException as e:
        return {"error": str(e)}


def benchmark_model(model_name: str, prompt: str = "Explica brevemente qué es la fotosíntesis.") -> dict:
    """
    Un único prompt de prueba, usando los tiempos que Ollama ya
    devuelve en la respuesta (no hay que cronometrar nosotros, y por
    tanto no se mide de más el tiempo de red hacia el gateway):
      - TTFT aproximado: load_duration + prompt_eval_duration
      - velocidad de generación: eval_count / eval_duration
    RAM: se consulta /api/ps (modelos cargados ahora mismo en memoria);
    si el modelo no aparece ahí (por ejemplo, si esta llamada lo acaba
    de cargar y /api/ps tarda un ciclo en reflejarlo), se indica como
    no disponible en vez de inventar un número.
    """
    t0 = time.time()
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model_name, "prompt": prompt, "stream": False},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        return {"error": str(e)}

    wall_clock = time.time() - t0
    load_ns = data.get("load_duration", 0) or 0
    prompt_eval_ns = data.get("prompt_eval_duration", 0) or 0
    eval_ns = data.get("eval_duration", 0) or 0
    eval_count = data.get("eval_count", 0) or 0

    ttft = round((load_ns + prompt_eval_ns) / 1e9, 2)
    tokens_per_sec = round(eval_count / (eval_ns / 1e9), 1) if eval_ns else None

    ram = "—"
    try:
        ps = requests.get(f"{OLLAMA_URL}/api/ps", timeout=3).json()
        for m in ps.get("models", []):
            if m.get("name") == model_name and m.get("size_vram"):
                ram = _format_size(m["size_vram"])
                break
    except requests.RequestException:
        pass

    return {
        "model": model_name,
        "ttft_seconds": ttft,
        "tokens_per_second": tokens_per_sec,
        "eval_count": eval_count,
        "ram": ram,
        "wall_clock_seconds": round(wall_clock, 2),
        "response_preview": (data.get("response", "") or "")[:200],
    }
