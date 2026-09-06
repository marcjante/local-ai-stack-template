"""
agent_worker.py

Worker de agente genérico. Varias instancias de este mismo fichero (agent-1,
agent-2, agent-3...) pueden correr a la vez, cada una escuchando la misma
cola de Redis y procesando tareas en paralelo, sin pisarse entre ellas
(BLPOP saca una tarea de la cola de forma atómica: cada tarea la coge un
único agente).

Este fichero es intencionadamente genérico: la función `process_task()` es
donde va la lógica real de cada proyecto. Todo lo demás (cola, salud,
resultados) es reutilizable tal cual.

Uso:
    python agents/agent_worker.py --id agent-1 --port 9101
"""

import argparse
import json
import threading
import time

import redis
from flask import Flask, jsonify

QUEUE_KEY = "tasks:pending"
RESULTS_KEY_PREFIX = "tasks:result:"

app = Flask(__name__)
STATE = {"agent_id": None, "status": "idle", "last_task": None, "processed": 0}


def get_redis_client():
    return redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)


def process_task(task: dict) -> dict:
    """
    Lógica de ejemplo: sustituye esto por el trabajo real del agente
    (llamar al LLM, consultar la base vectorial, transformar datos, etc.)
    """
    time.sleep(task.get("duration", 1))
    return {
        "task_id": task["id"],
        "handled_by": STATE["agent_id"],
        "result": f"Tarea '{task.get('payload', '')}' procesada por {STATE['agent_id']}",
    }


def worker_loop(agent_id: str):
    STATE["agent_id"] = agent_id
    r = get_redis_client()
    print(f"[{agent_id}] esperando tareas en la cola '{QUEUE_KEY}'...")
    while True:
        STATE["status"] = "idle"
        item = r.blpop(QUEUE_KEY, timeout=5)
        if item is None:
            continue
        _, raw_task = item
        task = json.loads(raw_task)
        STATE["status"] = "working"
        STATE["last_task"] = task.get("id")
        result = process_task(task)
        r.set(f"{RESULTS_KEY_PREFIX}{task['id']}", json.dumps(result))
        STATE["processed"] += 1
        print(f"[{agent_id}] tarea {task['id']} completada.")


@app.route("/health")
def health():
    return jsonify(STATE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True, help="Identificador del agente (agent-1, agent-2...)")
    parser.add_argument("--port", type=int, required=True, help="Puerto donde expone /health")
    args = parser.parse_args()

    t = threading.Thread(target=worker_loop, args=(args.id,), daemon=True)
    t.start()

    app.run(host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
