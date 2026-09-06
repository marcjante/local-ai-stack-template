"""
plugin_loader.py

Descubre workers automáticamente: cualquier fichero .py dentro de
workers/plugins/ que defina QUEUE_NAME y una función handle(task_id, payload)
se registra como un worker más, sin tocar backend/main.py ni
config/services.yaml.

Para añadir un worker nuevo: crea workers/plugins/mi_worker.py con:

    QUEUE_NAME = "mi_cola"
    QUEUE_TIMEOUT = 120  # opcional, por defecto 120

    def handle(task_id: str, payload: dict) -> dict:
        ...

Y arráncalo con: rq worker mi_cola --url redis://127.0.0.1:6379/0

El backend lo verá automáticamente en /enqueue/mi_cola la próxima vez
que arranque (la lista de plugins se descubre una vez al arrancar, no
en caliente — reiniciar el backend basta, no hace falta más).
"""

import importlib
import pkgutil

import workers.plugins as plugins_pkg


def discover_plugins() -> dict:
    """
    Devuelve {queue_name: {"handle": fn, "timeout": int, "module_name": str}}
    para cada plugin válido encontrado en workers/plugins/.
    """
    registry = {}
    for _, module_name, _ in pkgutil.iter_modules(plugins_pkg.__path__):
        module = importlib.import_module(f"workers.plugins.{module_name}")
        queue_name = getattr(module, "QUEUE_NAME", None)
        handle = getattr(module, "handle", None)
        if not queue_name or not handle:
            continue  # no es un plugin válido, se ignora sin fallar
        registry[queue_name] = {
            "handle": handle,
            "timeout": getattr(module, "QUEUE_TIMEOUT", 120),
            "module_name": module_name,
        }
    return registry
