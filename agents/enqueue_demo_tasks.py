"""
enqueue_demo_tasks.py

Script de demostración: mete varias tareas en la cola para comprobar que
los 3 agentes las recogen y procesan en paralelo (mira los logs de cada
agente, o consulta /health en cada uno para ver qué está haciendo cada uno).

Uso:
    python agents/enqueue_demo_tasks.py
"""

import json
import time
import uuid

import redis

QUEUE_KEY = "tasks:pending"


def main():
    r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)
    tasks = [
        {"id": str(uuid.uuid4()), "payload": f"tarea de ejemplo {i}", "duration": 2}
        for i in range(6)
    ]
    for task in tasks:
        r.rpush(QUEUE_KEY, json.dumps(task))
        print(f"Encolada: {task['id']} — {task['payload']}")

    print("\n6 tareas encoladas. Con 3 agentes activos deberían repartirse")
    print("2 tareas por agente y tardar ~4s en total (2 tandas de 2s), no 12s.")


if __name__ == "__main__":
    main()
