"""
process_jobs.py

Worker especializado en PROCESAR. El circuito ya no es una cadena fija de
pasos: es ADAPTATIVO — cada tarea decide qué subagentes necesita de
verdad, y todo queda auditado (qué se decidió, con qué modelo, con qué
chunks, contra qué versión de documento):

    1. gather_candidate_chunks()  — fuentes directas, doc_id concreto, o índice global (decisión auditada)
    2. generate_answer()          — LLM vía el gateway, con routing de modelo por task_type
    3. decide_need_verification() — ¿hace falta verificar? (no, si no hay fuentes o la respuesta es trivial)
    4. cross_check_sources()      — si hace falta: verificación por AFIRMACIÓN, con cita textual exacta
    5. veredicto final + aviso a n8n

Arrancar: rq worker process --url redis://127.0.0.1:6379/0
"""

import sys
import os
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from db.db import set_status, log_audit  # noqa: E402
from common.logging_setup import get_logger  # noqa: E402
from common.verification import cross_check_sources  # noqa: E402
from common.adaptive_pipeline import gather_candidate_chunks, decide_need_verification  # noqa: E402
from common.n8n_client import trigger_n8n_flow  # noqa: E402

LLM_GATEWAY_URL = os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1:8091")
log = get_logger(__name__)

QUEUE_NAME = "process"
QUEUE_TIMEOUT = 300


def generate_answer(task_id: str, prompt: str, task_type: str = "default") -> dict:
    """Subagente: pide la respuesta al LLM, siempre a través del gateway, con routing por task_type."""
    resp = requests.post(
        f"{LLM_GATEWAY_URL}/generate",
        json={"prompt": prompt, "task_type": task_type},
        timeout=90,
    )
    resp.raise_for_status()
    data = resp.json()
    answer = data.get("response", "")

    # Auditoría enriquecida: qué modelo respondió, con qué prompt y con
    # qué parámetros — no solo "generó algo".
    log_audit(task_id, step="generate", subagent="generate_answer", verdict="ok",
              details={
                  "model_used": data.get("_model_used"),
                  "provider_used": data.get("_provider_used"),
                  "task_type": data.get("_task_type", task_type),
                  "prompt": prompt,
                  "answer_len": len(answer),
              })
    return {"answer": answer, "model_used": data.get("_model_used")}


def handle(task_id: str, payload: dict) -> dict:
    log.info("empezando circuito adaptativo", extra={"task_id": task_id})
    set_status(task_id, "running", increment_attempts=True)
    try:
        prompt = payload.get("prompt", "")
        task_type = payload.get("task_type", "default")

        chunks, gather_path = gather_candidate_chunks(task_id, payload, query=prompt)
        gen = generate_answer(task_id, prompt, task_type=task_type)
        answer = gen["answer"]

        needs_verification = decide_need_verification(task_id, answer, chunks)

        if needs_verification:
            cross_check = cross_check_sources(task_id, answer=answer, candidate_chunks=chunks)
            final_verdict = "veraz" if cross_check["verdict"] in ("todo_citado", "mayoria_citada") else "revisar"
        else:
            cross_check = {"verdict": "omitido", "reason": "sin fuentes o respuesta trivial"}
            final_verdict = "sin_verificar"

        # Auditoría del contexto documental usado (doc_version, chunks) —
        # trazabilidad real de qué versión de qué documento respaldó esto.
        doc_versions = sorted({c.get("doc_version") for c in chunks if c.get("doc_version")})
        chunk_ids_used = [c.get("chunk_id") for c in chunks[:10]]
        log_audit(task_id, step="context_used", subagent="process_task", verdict="ok",
                  details={"gather_path": gather_path, "doc_versions": doc_versions, "chunk_ids": chunk_ids_used})

        log_audit(task_id, step="final_verdict", subagent="process_task", verdict=final_verdict,
                  details={"cross_check": cross_check})

        result = {
            "answer": answer,
            "model_used": gen["model_used"],
            "verdict": final_verdict,
            "cross_check": cross_check,
        }
        set_status(task_id, "completed", result=result)
        log.info(f"completada, veredicto={final_verdict}", extra={"task_id": task_id})

        n8n_result = trigger_n8n_flow("resultado-tarea", {
            "task_id": task_id, "queue": "process", **result,
        }, task_id=task_id, project_id=payload.get("project_id", "default"))
        if n8n_result.get("skipped"):
            n8n_verdict = "omitido_desactivado"
        elif n8n_result.get("ok"):
            n8n_verdict = "ok"
        else:
            n8n_verdict = "fallo_notificacion"
        log_audit(task_id, step="n8n_notify", subagent="n8n_client",
                  verdict=n8n_verdict, details=n8n_result)

        return result
    except Exception as e:
        set_status(task_id, "failed", error=str(e))
        log.error(f"fallida: {e}", extra={"task_id": task_id})
        log_audit(task_id, step="final_verdict", subagent="process_task",
                  verdict="error", details={"error": str(e)})
        raise
