"""
logging_setup.py

Logging centralizado y con contexto: todo lo que loguee cualquier
servicio (backend, workers) pasa por el mismo formato e incluye el
task_id cuando existe, para poder seguir una tarea completa en los
logs aunque la procesen varios servicios distintos.

Uso:
    from common.logging_setup import get_logger
    log = get_logger(__name__)
    log.info("procesando", extra={"task_id": task_id})
"""

import logging
import sys

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s task_id=%(task_id)s — %(message)s"


class _DefaultTaskIdFilter(logging.Filter):
    """Si no se pasa task_id explícito en `extra`, muestra '-' en vez de reventar."""
    def filter(self, record):
        if not hasattr(record, "task_id"):
            record.task_id = "-"
        return True


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler.addFilter(_DefaultTaskIdFilter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
