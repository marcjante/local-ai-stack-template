"""
queue_conn.py

Conexión y colas compartidas de RQ (Redis Queue). Centralizado aquí para
que el backend (al encolar) y los workers (al arrancar) usen exactamente
la misma configuración.

Colas con nombre por función, en vez de una única cola genérica:
así cada worker especializado escucha solo lo suyo y el backend decide
a qué worker va cada tarea simplemente eligiendo la cola.
"""

import os
from redis import Redis
from rq import Queue, Retry

REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
redis_conn = Redis.from_url(REDIS_URL)

# Reintentos con backoff: 3 intentos, esperando 10s / 30s / 60s entre cada uno.
DEFAULT_RETRY = Retry(max=3, interval=[10, 30, 60])

QUEUE_FETCH = Queue("fetch", connection=redis_conn, default_timeout=120)
QUEUE_PROCESS = Queue("process", connection=redis_conn, default_timeout=300)
QUEUE_NOTIFY = Queue("notify", connection=redis_conn, default_timeout=60)

# Cola de "muertas": RQ mueve aquí automáticamente los jobs que agotan
# todos sus reintentos (Failed Job Registry por cola, expuesto por nombre
# para que el panel de control pueda inspeccionarlo).
QUEUES_BY_NAME = {
    "fetch": QUEUE_FETCH,
    "process": QUEUE_PROCESS,
    "notify": QUEUE_NOTIFY,
}
