"""
process_jobs.py

Worker especializado en PROCESAR — pero ya no es un único paso, es un
circuito de subagentes encadenados, cada uno con su propia responsabilidad
y su propio veredicto guardado en audit_log:

    1. gather_sources()       — reúne las fuentes que respaldarán la respuesta
    2. generate_answer()      — pide al LLM (vía llm_gateway, nunca directo)
    3. cross_check_sources()  — ¿cuántas fuentes independientes lo confirman?
    4. detect_hallucination() — ¿la respuesta se apoya en las fuentes o parece inventada?
    5. notify via n8n         — dispara un flujo de n8n con el resultado final
                                 (que puede, a su vez, seguir procesando fuera de Python)

Arrancar: rq worker process --url redis://127.0.0.1:6379/0
"""

import sys
import os
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.db import set_status, log_audit  # noqa: E402
from common.logging_setup import get_logger  # noqa: E402
from common.verification import cross_check_sources, detect_hallucination  # noqa: E402
from common.n8n_client import trigger_n8n_flow  # noqa: E402

LLM_GATEWAY_URL = os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1:8091")
log = get_logger(__name__)


def gather_sources(task_id: str, payload: dict) -> list:
    """
    Subagente 0: reúne las fuentes sobre las que se apoyará la respuesta.
    Sustituye esto por la llamada real a rag/retrieval.py (ChromaDB, etc.).
    Aquí, de plantilla, acepta las fuentes directamente en el payload si
    vienen dadas, para poder probar el circuito sin una base vectorial real.
    """
    sources = payload.get("sources", [])
    log_audit(task_id, step="gather", subagent="gather_sources",
              verdict="ok", details={"n_sources": len(sources)})
    return sources


def generate_answer(task_id: str, prompt: str) -> str:
    """Subagente: pide la respuesta al LLM, siempre a través del gateway."""
    resp = requests.post(f"{LLM_GATEWAY_URL}/generate", json={"prompt": prompt}, timeout=90)
    resp.raise_for_status()
    answer = resp.json().get("response", "")
    log_audit(task_id, step="generate", subagent="generate_answer",
              verdict="ok", details={"prompt_len": len(prompt), "answer_len": len(answer)})
    return answer


def process_task(task_id: str, payload: dict) -> dict:
    log.info("empezando circuito de verificación", extra={"task_id": task_id})
    set_status(task_id, "running", increment_attempts=True)
    try:
        sources = gather_sources(task_id, payload)
        prompt = payload.get("prompt", "")
        answer = generate_answer(task_id, prompt)

        cross_check = cross_check_sources(task_id, claim=answer, sources=sources)
        hallucination = detect_hallucination(task_id, answer=answer, sources=sources)

        # Veredicto final del circuito: combina ambas comprobaciones.
        is_trustworthy = (
            cross_check["verdict"] in ("corroborado", "una_sola_fuente")
            and hallucination["verdict"] != "posible_alucinacion"
        )
        final_verdict = "veraz" if is_trustworthy else "revisar"

        log_audit(task_id, step="final_verdict", subagent="process_task",
                  verdict=final_verdict,
                  details={"cross_check": cross_check, "hallucination": hallucination})

        result = {
            "answer": answer,
            "verdict": final_verdict,
            "cross_check": cross_check,
            "hallucination_check": hallucination,
        }
        set_status(task_id, "completed", result=result)
        log.info(f"completada, veredicto={final_verdict}", extra={"task_id": task_id})

        # Aviso a n8n con el resultado final, para que el flujo decida qué
        # hacer con él (guardarlo, mandarlo a alguien, escalarlo si el
        # veredicto es 'revisar', etc.) — no es Python quien decide eso.
        n8n_result = trigger_n8n_flow("resultado-tarea", {
            "task_id": task_id, "queue": "process", **result,
        }, task_id=task_id)
        log_audit(task_id, step="n8n_notify", subagent="n8n_client",
                  verdict="ok" if n8n_result.get("ok") else "fallo_notificacion",
                  details=n8n_result)

        return result
    except Exception as e:
        set_status(task_id, "failed", error=str(e))
        log.error(f"fallida: {e}", extra={"task_id": task_id})
        log_audit(task_id, step="final_verdict", subagent="process_task",
                  verdict="error", details={"error": str(e)})
        raise
