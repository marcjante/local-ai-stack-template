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


def _call_ollama(model: str, prompt: str, timeout: float, system: str = None, options: dict = None) -> dict:
    body = {"model": model, "prompt": prompt, "stream": False}
    if system:
        body["system"] = system
    if options:
        body["options"] = options
    resp = requests.post(f"{OLLAMA_URL}/api/generate", json=body, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return {
        "text": data.get("response", ""),
        "eval_count": data.get("eval_count"),
        "eval_duration_ns": data.get("eval_duration"),
    }


def _call_openai_compatible(model: str, prompt: str, timeout: float, system: str = None, options: dict = None) -> dict:
    if not OPENAI_COMPAT_URL:
        raise RuntimeError("OPENAI_COMPAT_URL no configurado — pon la URL del servidor compatible con OpenAI en .env")
    headers = {"Content-Type": "application/json"}
    if OPENAI_COMPAT_API_KEY:
        headers["Authorization"] = f"Bearer {OPENAI_COMPAT_API_KEY}"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body = {"model": model, "messages": messages}
    if options and "temperature" in options:
        body["temperature"] = options["temperature"]
    resp = requests.post(f"{OPENAI_COMPAT_URL}/v1/chat/completions", json=body, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage", {})
    return {
        "text": data["choices"][0]["message"]["content"],
        "eval_count": usage.get("completion_tokens"),
        "eval_duration_ns": None,
    }


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
    import time as time_module
    payload = request.get_json(force=True) or {}
    prompt = payload.get("prompt", "")
    system = payload.get("system")
    task_type = payload.get("task_type", "default")

    route = MODEL_ROUTES.get(task_type, MODEL_ROUTES["default"])
    provider = payload.get("provider") or route["provider"]
    model = payload.get("model") or route["model"]

    options = {}
    if "temperature" in payload:
        options["temperature"] = payload["temperature"]
    if "num_ctx" in payload:
        options["num_ctx"] = payload["num_ctx"]

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
    t0 = time_module.time()
    try:
        result = adapter(model, prompt, 120, system=system, options=options or None)
        elapsed = round(time_module.time() - t0, 3)
        tokens = result.get("eval_count")
        tok_per_sec = round(tokens / elapsed, 1) if tokens and elapsed > 0 else None
        return jsonify({
            "response": result["text"],
            "_model_used": model, "_provider_used": provider, "_task_type": task_type,
            "_elapsed_seconds": elapsed, "_tokens": tokens, "_tokens_per_second": tok_per_sec,
        })
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
