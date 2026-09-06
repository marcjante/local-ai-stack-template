"""
vector_store.py

Responsabilidad única: guardar chunks con su embedding, y buscar los más
parecidos a un embedding de consulta.

Backend por defecto: tabla `rag_chunks` en el MISMO Postgres que ya usa
el stack (columna embedding como JSONB; la similitud coseno se calcula en
Python). Es deliberadamente simple para que la plantilla funcione sin
instalar nada más — a la escala de una plantilla/demo, cientos o pocos
miles de chunks van bien así.

Para un proyecto con muchos más documentos, cambia RAG_BACKEND:
  - "pgvector": misma Postgres, pero con la extensión pgvector y un
    índice ANN (mucho más rápido en > ~100k chunks). Requiere
    `CREATE EXTENSION vector;` y cambiar la columna a tipo `vector`.
  - "qdrant": base vectorial dedicada, mejor si el volumen o el QPS de
    búsqueda crecen mucho. Añade el servicio a `services.yaml` y
    `docker-compose.yml` si lo activas.
Los stubs de ambos están abajo — quien los necesite, los implementa;
no se incluyen enteros para no arrastrar dependencias que la mayoría
de proyectos con esta plantilla no van a usar.
"""

import os
import json

from db.db import get_conn
from rag.embeddings import cosine_similarity

RAG_BACKEND = os.environ.get("RAG_BACKEND", "postgres_json")


def add_chunks(chunks: list, embeddings: list, doc_version: str = "v1"):
    if RAG_BACKEND != "postgres_json":
        raise NotImplementedError(f"Backend '{RAG_BACKEND}' no implementado en esta plantilla (ver docstring)")

    with get_conn() as conn, conn.cursor() as cur:
        for chunk, emb in zip(chunks, embeddings):
            cur.execute(
                """
                INSERT INTO rag_chunks (chunk_id, doc_id, position, text, embedding, doc_version)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (chunk_id) DO UPDATE
                SET text = EXCLUDED.text, embedding = EXCLUDED.embedding, doc_version = EXCLUDED.doc_version
                """,
                (chunk["chunk_id"], chunk["doc_id"], chunk["position"], chunk["text"],
                 json.dumps(emb), doc_version),
            )


def search(query_embedding: list, top_k: int = 5, doc_id: str = None) -> list:
    if RAG_BACKEND != "postgres_json":
        raise NotImplementedError(f"Backend '{RAG_BACKEND}' no implementado en esta plantilla (ver docstring)")

    with get_conn() as conn, conn.cursor() as cur:
        if doc_id:
            cur.execute("SELECT chunk_id, doc_id, position, text, embedding, doc_version FROM rag_chunks WHERE doc_id = %s", (doc_id,))
        else:
            cur.execute("SELECT chunk_id, doc_id, position, text, embedding, doc_version FROM rag_chunks")
        rows = cur.fetchall()

    scored = []
    for chunk_id, doc_id_, position, text, embedding, doc_version in rows:
        emb = json.loads(embedding) if isinstance(embedding, str) else embedding
        score = cosine_similarity(query_embedding, emb)
        scored.append({
            "chunk_id": chunk_id, "doc_id": doc_id_, "position": position,
            "text": text, "doc_version": doc_version, "score": score,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


# --- Stubs documentados para backends alternativos (🟠5 del roadmap) ---

def _add_chunks_pgvector(chunks, embeddings, doc_version="v1"):
    """
    Requiere: CREATE EXTENSION IF NOT EXISTS vector;
    y una columna `embedding vector(256)` en vez de JSONB.
    La búsqueda se hace con el operador `<=>` (distancia coseno) de
    pgvector, con un índice ivfflat/hnsw — mucho más rápido a gran escala.
    """
    raise NotImplementedError("Activa pgvector en Postgres e implementa esto para tu proyecto")


def _search_qdrant(query_embedding, top_k=5, collection="chunks"):
    """
    Requiere el servicio Qdrant (añádelo a services.yaml/docker-compose.yml)
    y el cliente `qdrant-client`. Sustituye por completo esta tabla y este
    módulo si el volumen de chunks lo justifica.
    """
    raise NotImplementedError("Añade el servicio Qdrant y su cliente para usar este backend")
