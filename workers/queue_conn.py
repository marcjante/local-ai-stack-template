"""
queue_conn.py

Conexión de Redis compartida. Las colas ya NO están hardcodeadas aquí
(antes: QUEUE_FETCH, QUEUE_PROCESS, QUEUE_NOTIFY fijas) — se construyen
dinámicamente a partir de lo que workers/plugin_loader.py descubra en
workers/plugins/. Así, un plugin nuevo no necesita tocar este fichero.
"""

import os
from redis import Redis
from rq import Queue, Retry

REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
redis_conn = Redis.from_url(REDIS_URL)

# Reintentos con backoff: 3 intentos, esperando 10s / 30s / 60s entre cada uno.
DEFAULT_RETRY = Retry(max=3, interval=[10, 30, 60])


def build_queues(plugin_registry: dict) -> dict:
    """A partir de {queue_name: {...}} de plugin_loader, construye {queue_name: rq.Queue}."""
    return {
        name: Queue(name, connection=redis_conn, default_timeout=info["timeout"])
        for name, info in plugin_registry.items()
    }
