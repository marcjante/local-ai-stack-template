"""Generation and claim verification orchestration for Thesis Phase 3B."""

import os
import uuid
import requests
from psycopg2.extras import RealDictCursor

from common.thesis_service import ThesisNotFound, _profile, _require_project
from common.thesis_versions import create_version, create_claim, add_claim_source
from common.verification import split_into_claims, verify_claim
from db.db import get_conn

GATEWAY_URL = os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1:8091")


def _sources(cur, project_id, chapter_id):
    cur.execute("SELECT s.fragment_id, f.doc_id, f.rag_chunk_id, f.pgvector_chunk_id, f.source_locator FROM thesis_section_sources s JOIN thesis_fragments f ON f.project_id=s.project_id AND f.id=s.fragment_id WHERE s.project_id=%s AND s.chapter_id=%s", (project_id, chapter_id))
    sources = []
    for row in cur.fetchall():
        chunk_id, table = row["rag_chunk_id"] or row["pgvector_chunk_id"], "rag_chunks" if row["rag_chunk_id"] else "rag_chunks_pgvector"
        cur.execute(f"SELECT text, chunk_id FROM {table} WHERE chunk_id=%s AND doc_id=%s", (chunk_id, row["doc_id"]))
        chunk = cur.fetchone()
        if chunk:
            sources.append({**dict(row), "text": chunk["text"], "chunk_id": chunk["chunk_id"]})
    return sources


def generate_chapter(project_id, chapter_id, instructions=""):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        _require_project(cur, project_id); _profile(cur, project_id)
        cur.execute("SELECT title, chapter_type FROM thesis_chapters WHERE project_id=%s AND id=%s", (project_id, chapter_id))
        chapter = cur.fetchone()
        if not chapter: raise ThesisNotFound("capítulo no encontrado")
        sources = _sources(cur, project_id, chapter_id)
    if not sources:
        raise ValueError("el capítulo no tiene fuentes aprobadas")
    evidence = "\n\n".join(f"[fragmento {s['fragment_id']}]\n{s['text']}" for s in sources)
    prompt = f"Redacta un borrador académico en Markdown para el capítulo '{chapter['title']}'.\n{instructions}\nUsa únicamente esta evidencia y no inventes datos:\n{evidence}"
    response = requests.post(f"{GATEWAY_URL}/generate", json={"prompt": prompt, "task_type": "razonamiento", "skill_task": "thesis_generate"}, timeout=180)
    response.raise_for_status(); data = response.json(); content = data.get("response") or data.get("generated_text") or ""
    if not content: raise ValueError("el gateway no devolvió contenido")
    version = create_version(project_id, chapter_id, {"content_markdown": content, "instructions": instructions, "model": data.get("_model_used"), "provider": data.get("_provider_used")}, "thesis_generate")
    for claim in split_into_claims(content):
        create_claim(project_id, version["id"], {"claim_text": claim, "claim_type": "interpretation"})
    return version


def verify_version(project_id, version_id):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        _require_project(cur, project_id)
        cur.execute("SELECT * FROM thesis_claims WHERE project_id=%s AND section_version_id=%s", (project_id, version_id)); claims = cur.fetchall()
        cur.execute("SELECT s.fragment_id, f.doc_id, f.rag_chunk_id, f.pgvector_chunk_id FROM thesis_section_sources s JOIN thesis_fragments f ON f.project_id=s.project_id AND f.id=s.fragment_id JOIN thesis_section_versions v ON v.project_id=s.project_id AND v.chapter_id=s.chapter_id WHERE v.project_id=%s AND v.id=%s", (project_id, version_id))
        refs = cur.fetchall(); candidates = []
        for ref in refs:
            cid, table = ref["rag_chunk_id"] or ref["pgvector_chunk_id"], "rag_chunks" if ref["rag_chunk_id"] else "rag_chunks_pgvector"
            cur.execute(f"SELECT text, chunk_id FROM {table} WHERE chunk_id=%s AND doc_id=%s", (cid, ref["doc_id"]))
            chunk = cur.fetchone()
            if chunk: candidates.append({"text": chunk["text"], "chunk_id": chunk["chunk_id"], "doc_id": ref["doc_id"], "fragment_id": ref["fragment_id"]})
    results = []
    for claim in claims:
        result = verify_claim(claim["claim_text"], candidates)
        status = {"citado": "verified", "parcial": "partial"}.get(result["verdict"], "unsupported")
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE thesis_claims SET verification_status=%s, updated_at=now() WHERE project_id=%s AND id=%s", (status, project_id, claim["id"]))
        if result.get("citation"):
            match = next((c for c in candidates if c["chunk_id"] == result["citation"]["chunk_id"]), None)
            if match:
                add_claim_source(project_id, claim["id"], {"fragment_id": match["fragment_id"], "source_quote": result["citation"]["quote"], "verification_result": result["verdict"], "verification_score": result["overlap"]})
        results.append({"claim_id": claim["id"], **result, "verification_status": status})
    return {"version_id": version_id, "claims": results}
