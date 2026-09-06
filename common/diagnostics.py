"""
diagnostics.py

Va un paso más allá de "el puerto responde": cruza varias señales para
detectar problemas concretos y accionables. El caso que más se repite en
la práctica — una cola con tareas esperando pero SIN ningún worker
escuchándola — no se ve mirando servicios uno a uno (Redis está bien,
Postgres está bien, el backend está bien... y aun así nada se procesa).
"""

import os

from common.system_checks import check_postgres, check_redis, check_docker


def _http_ok(url, timeout=1.5):
    import requests
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code < 400, r
    except requests.RequestException as e:
        return False, str(e)


def _active_worker_queues():
    try:
        from rq import Worker
        from redis import Redis
        r = Redis(host="127.0.0.1", port=6379, socket_connect_timeout=0.5)
        queues = set()
        for w in Worker.all(connection=r):
            queues.update(q.name for q in w.queues)
        return queues
    except Exception:
        return set()


def _queue_depths():
    try:
        from redis import Redis
        r = Redis(host="127.0.0.1", port=6379, socket_connect_timeout=0.5)
        return {name: r.llen(f"rq:queue:{name}") for name in _discovered_queue_names()}
    except Exception:
        return {}


def _discovered_queue_names():
    try:
        from workers.plugin_loader import discover_plugins
        return list(discover_plugins().keys())
    except Exception:
        return []


def run_diagnostics():
    services = {}

    pg = check_postgres()
    services["Postgres"] = "up" if pg["ok"] else "down"

    rd = check_redis()
    services["Redis"] = "up" if rd["ok"] else "down"

    backend_ok, _ = _http_ok("http://127.0.0.1:8080/health")
    services["Backend"] = "up" if backend_ok else "down"

    gw_ready_ok, gw_resp = _http_ok("http://127.0.0.1:8091/ready")
    if gw_ready_ok:
        services["LLM Gateway"] = "up"
    else:
        gw_health_ok, _ = _http_ok("http://127.0.0.1:8091/health")
        services["LLM Gateway"] = "slow" if gw_health_ok else "down"

    problems = []

    active_queues = _active_worker_queues()
    depths = _queue_depths()
    for queue_name in _discovered_queue_names():
        has_worker = queue_name in active_queues
        depth = depths.get(queue_name, 0)
        services[f"Worker: {queue_name}"] = "up" if has_worker else "down"
        if not has_worker:
            problems.append({
                "severity": "high" if depth > 0 else "medium",
                "message": f"Ningún worker está escuchando la cola \"{queue_name}\""
                           + (f" — {depth} tarea(s) esperando" if depth > 0 else ""),
                "action": "start_worker",
                "action_target": queue_name,
            })

    if not pg["ok"]:
        problems.append({"severity": "high", "message": "Postgres no responde", "action": None})
    if not rd["ok"]:
        problems.append({"severity": "high", "message": "Redis no responde", "action": None})
    if not backend_ok:
        problems.append({"severity": "high", "message": "El backend no responde en /health", "action": None})
    if services["LLM Gateway"] == "slow":
        problems.append({
            "severity": "medium",
            "message": "El LLM Gateway responde pero no confirma que el proveedor por defecto esté listo (/ready)",
            "action": None,
        })

    down_count = sum(1 for v in services.values() if v == "down")
    if down_count == 0 and not any(p["severity"] == "high" for p in problems):
        overall = "healthy"
    elif services.get("Backend") == "down" or services.get("Postgres") == "down" or services.get("Redis") == "down":
        overall = "critical"
    else:
        overall = "degraded" if problems else "healthy"

    return {"overall": overall, "services": services, "problems": problems}
