"""
llm_gateway.py

Único punto de acceso a los LLM del stack. Dos cosas, no una:

  1. Controla CUÁNTAS peticiones concurrentes llegan a cada backend (un
     semáforo por proveedor), para no saturarlo.
  2. Hace de selector de modelo/proveedor: cada tipo de tarea
     (`task_type`) tiene asignado un proveedor + modelo en MODEL_ROUTES,
     configurable por .env. Puedes tener Ollama para lo local y un
     endpoint compatible con OpenAI (LM Studio, vLLM, OpenAI real...)
     para lo que necesite otra cosa, y el resto del stack no tiene que
     saber cuál es cuál — solo manda `task_type`.

Puerto: 8091
Arrancar: python3 llm_gateway/llm_gateway.py
"""

import os
import threading

import requests
from flask import Flask, request, jsonify

# --- Proveedores disponibles ---
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OPENAI_COMPAT_URL = os.environ.get("OPENAI_COMPAT_URL", "")  # ej. http://127.0.0.1:1234 (LM Studio, vLLM...) o https://api.openai.com
OPENAI_COMPAT_API_KEY = os.environ.get("OPENAI_COMPAT_API_KEY", "")

MAX_CONCURRENT = int(os.environ.get("LLM_MAX_CONCURRENT", "2"))

# task_type -> {provider, model}. Cada proyecto ajusta esto a lo que
# tenga disponible de verdad. "default" cubre lo que no encaje en nada
# más específico.
MODEL_ROUTES = {
    "default":      {"provider": "ollama", "model": os.environ.get("LLM_MODEL_DEFAULT", "llama3.1")},
    "rapido":       {"provider": "ollama", "model": os.environ.get("LLM_MODEL_FAST", "llama3.1:8b")},
    "razonamiento": {"provider": os.environ.get("LLM_PROVIDER_REASONING", "ollama"),
                      "model": os.environ.get("LLM_MODEL_REASONING", "llama3.1:70b")},
}

app = Flask(__name__)
_semaphore = threading.Semaphore(MAX_CONCURRENT)
_stats_lock = threading.Lock()
_stats = {"in_flight": 0, "total_requests": 0, "total_rejected_timeout": 0, "by_model": {}, "by_provider": {}}


def _call_ollama(model: str, prompt: str, timeout: float) -> str:
    resp = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


def _call_openai_compatible(model: str, prompt: str, timeout: float) -> str:
    if not OPENAI_COMPAT_URL:
        raise RuntimeError("OPENAI_COMPAT_URL no configurado — pon la URL del servidor compatible con OpenAI en .env")
    headers = {"Content-Type": "application/json"}
    if OPENAI_COMPAT_API_KEY:
        headers["Authorization"] = f"Bearer {OPENAI_COMPAT_API_KEY}"
    resp = requests.post(
        f"{OPENAI_COMPAT_URL}/v1/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": prompt}]},
        headers=headers, timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


PROVIDER_ADAPTERS = {
    "ollama": _call_ollama,
    "openai_compatible": _call_openai_compatible,
}


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/ready")
def ready():
    """Comprueba que el proveedor por defecto (Ollama) responde de verdad."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        ok = r.status_code == 200
    except requests.RequestException:
        ok = False
    return jsonify({"ready": ok}), (200 if ok else 503)


@app.route("/providers")
def providers():
    return jsonify({
        "available": list(PROVIDER_ADAPTERS),
        "routes": MODEL_ROUTES,
        "openai_compatible_configured": bool(OPENAI_COMPAT_URL),
    })


@app.route("/models")
def models():
    return jsonify(MODEL_ROUTES)


@app.route("/metrics")
def metrics():
    with _stats_lock:
        return jsonify({
            **_stats,
            "max_concurrent": MAX_CONCURRENT,
            "slots_free": MAX_CONCURRENT - _stats["in_flight"],
        })


@app.route("/generate", methods=["POST"])
def generate():
    payload = request.get_json(force=True) or {}
    prompt = payload.get("prompt", "")
    task_type = payload.get("task_type", "default")

    route = MODEL_ROUTES.get(task_type, MODEL_ROUTES["default"])
    provider = payload.get("provider") or route["provider"]
    model = payload.get("model") or route["model"]

    adapter = PROVIDER_ADAPTERS.get(provider)
    if not adapter:
        return jsonify({"error": f"proveedor desconocido '{provider}'", "disponibles": list(PROVIDER_ADAPTERS)}), 400

    acquired = _semaphore.acquire(timeout=30)
    if not acquired:
        with _stats_lock:
            _stats["total_rejected_timeout"] += 1
        return jsonify({"error": "LLM saturado, reintenta más tarde"}), 503

    with _stats_lock:
        _stats["in_flight"] += 1
        _stats["total_requests"] += 1
        _stats["by_model"][model] = _stats["by_model"].get(model, 0) + 1
        _stats["by_provider"][provider] = _stats["by_provider"].get(provider, 0) + 1
    try:
        text = adapter(model, prompt, 120)
        return jsonify({"response": text, "_model_used": model, "_provider_used": provider, "_task_type": task_type})
    except requests.RequestException as e:
        return jsonify({"error": f"fallo llamando al proveedor '{provider}': {e}"}), 502
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        with _stats_lock:
            _stats["in_flight"] -= 1
        _semaphore.release()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8091)
