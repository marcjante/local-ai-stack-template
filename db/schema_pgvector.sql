-- Backend pgvector real (opcional, RAG_BACKEND=pgvector): misma info que
-- rag_chunks pero con la columna embedding como tipo `vector` en vez de
-- JSONB, para que Postgres calcule la distancia coseno nativamente y
-- pueda usar un índice ivfflat en vez de traer todo a Python.
-- Requiere: CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_chunks_pgvector (
    chunk_id    TEXT PRIMARY KEY,
    doc_id      TEXT NOT NULL,
    position    INTEGER NOT NULL,
    text        TEXT NOT NULL,
    embedding   vector(256) NOT NULL,
    doc_version TEXT NOT NULL DEFAULT 'v1',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_pgvector_doc_id ON rag_chunks_pgvector (doc_id);

-- Índice HNSW para búsqueda aproximada rápida. A diferencia de ivfflat,
-- HNSW no necesita "entrenarse" con datos representativos antes de
-- construirse — un ivfflat creado sobre la tabla vacía (como pasa aquí,
-- antes de indexar ningún documento) queda mal calibrado y puede devolver
-- CERO resultados en silencio, sin error. Esto se descubrió probando el
-- backend pgvector de verdad durante el desarrollo de esta plantilla.
CREATE INDEX IF NOT EXISTS idx_rag_pgvector_embedding
    ON rag_chunks_pgvector USING hnsw (embedding vector_cosine_ops);
