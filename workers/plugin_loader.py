"""
plugin_loader.py

Descubre workers automáticamente: cualquier fichero .py dentro de
workers/plugins/ que defina QUEUE_NAME y una función handle(task_id, payload)
se registra como un worker.

IMPORTANTE:
- Un plugin descubierto técnicamente NO implica que esté autorizado como Tool.
- La autorización de Tools se controla por separado en config/tools.yaml.
- Dos plugins no pueden declarar el mismo QUEUE_NAME.
"""

import importlib
import pkgutil

import workers.plugins as plugins_pkg


DEFAULT_QUEUE_TIMEOUT = 120


def discover_plugins() -> dict:
    """
    Descubre los plugins disponibles.

    Devuelve:

        {
            queue_name: {
                "handle": function,
                "timeout": int,
                "module_name": str,
            }
        }

    Falla explícitamente si dos módulos declaran el mismo QUEUE_NAME.
    Esto evita que una copia, backup o versión antigua sustituya
    silenciosamente al plugin esperado.
    """

    registry = {}

    for _, module_name, _ in pkgutil.iter_modules(plugins_pkg.__path__):
        module = importlib.import_module(
            f"workers.plugins.{module_name}"
        )

        queue_name = getattr(module, "QUEUE_NAME", None)
        handle = getattr(module, "handle", None)

        if not queue_name or not callable(handle):
            continue

        if queue_name in registry:
            previous_module = registry[queue_name]["module_name"]

            raise RuntimeError(
                "QUEUE_NAME duplicado detectado: "
                f"'{queue_name}' está definido en "
                f"'workers.plugins.{previous_module}' y "
                f"'workers.plugins.{module_name}'. "
                "Cada cola debe tener una única implementación."
            )

        timeout = getattr(
            module,
            "QUEUE_TIMEOUT",
            DEFAULT_QUEUE_TIMEOUT,
        )

        registry[queue_name] = {
            "handle": handle,
            "timeout": timeout,
            "module_name": module_name,
        }

    return registry
