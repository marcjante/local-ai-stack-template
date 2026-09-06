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
from rag.embeddings import cosine_similarity, DIMENSIONS

RAG_BACKEND = os.environ.get("RAG_BACKEND", "postgres_json")


def add_chunks(chunks: list, embeddings: list, doc_version: str = "v1"):
    if RAG_BACKEND == "pgvector":
        return _add_chunks_pgvector(chunks, embeddings, doc_version)
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
    if RAG_BACKEND == "pgvector":
        return _search_pgvector(query_embedding, top_k, doc_id)
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


# --- Backend pgvector (🟠5 del roadmap, implementado de verdad) ---
#
# Requiere: CREATE EXTENSION vector; y la tabla rag_chunks_pgvector (ver
# db/schema.sql) con una columna `embedding vector(256)` en vez de JSONB.
# La búsqueda usa el operador `<=>` (distancia coseno) de pgvector — se
# calcula dentro de Postgres, no trayendo todos los chunks a Python como
# hace el backend por defecto. A partir de decenas de miles de chunks,
# esto es sustancialmente más rápido, sobre todo con un índice ivfflat.

def _vector_literal(embedding: list) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


def _add_chunks_pgvector(chunks: list, embeddings: list, doc_version: str = "v1"):
    with get_conn() as conn, conn.cursor() as cur:
        for chunk, emb in zip(chunks, embeddings):
            cur.execute(
                """
                INSERT INTO rag_chunks_pgvector (chunk_id, doc_id, position, text, embedding, doc_version)
                VALUES (%s, %s, %s, %s, %s::vector, %s)
                ON CONFLICT (chunk_id) DO UPDATE
                SET text = EXCLUDED.text, embedding = EXCLUDED.embedding, doc_version = EXCLUDED.doc_version
                """,
                (chunk["chunk_id"], chunk["doc_id"], chunk["position"], chunk["text"],
                 _vector_literal(emb), doc_version),
            )


def _search_pgvector(query_embedding: list, top_k: int = 5, doc_id: str = None) -> list:
    query_lit = _vector_literal(query_embedding)
    with get_conn() as conn, conn.cursor() as cur:
        if doc_id:
            cur.execute(
                """
                SELECT chunk_id, doc_id, position, text, doc_version,
                       1 - (embedding <=> %s::vector) AS score
                FROM rag_chunks_pgvector
                WHERE doc_id = %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_lit, doc_id, query_lit, top_k),
            )
        else:
            cur.execute(
                """
                SELECT chunk_id, doc_id, position, text, doc_version,
                       1 - (embedding <=> %s::vector) AS score
                FROM rag_chunks_pgvector
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_lit, query_lit, top_k),
            )
        rows = cur.fetchall()

    return [
        {"chunk_id": r[0], "doc_id": r[1], "position": r[2], "text": r[3], "doc_version": r[4], "score": float(r[5])}
        for r in rows
    ]


def _search_qdrant(query_embedding, top_k=5, collection="chunks"):
    """
    Requiere el servicio Qdrant (añádelo a services.yaml/docker-compose.yml)
    y el cliente `qdrant-client`. Sustituye por completo esta tabla y este
    módulo si el volumen de chunks lo justifica. No implementado aquí
    porque, a diferencia de pgvector, exige levantar un servicio nuevo —
    cada proyecto decide si lo necesita de verdad antes de añadir esa
    pieza operativa.
    """
    raise NotImplementedError("Añade el servicio Qdrant y su cliente para usar este backend")
