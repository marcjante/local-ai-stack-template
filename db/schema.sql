-- schema.sql
-- Esquema mínimo para dar trazabilidad real a las tareas: estado explícito
-- (pending/running/completed/failed), resultado, error y nº de intentos.

CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    queue       TEXT NOT NULL,               -- qué worker especializado la procesa
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    payload     JSONB,
    result      JSONB,
    error       TEXT,
    attempts    INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status);
CREATE INDEX IF NOT EXISTS idx_tasks_queue ON tasks (queue);

-- Traza de cada paso del "circuito de información veraz": qué subagente
-- actuó, sobre qué tarea, qué decidió y por qué. Una tarea puede tener
-- varias filas aquí (una por subagente que participó).
CREATE TABLE IF NOT EXISTS audit_log (
    id          SERIAL PRIMARY KEY,
    task_id     TEXT NOT NULL,
    step        TEXT NOT NULL,           -- ej. 'cross_check', 'hallucination_check', 'n8n_notify'
    subagent    TEXT NOT NULL,           -- nombre del subagente que ejecutó el paso
    verdict     TEXT,                    -- ej. 'ok', 'baja_confianza', 'posible_alucinacion'
    confidence  REAL,                    -- 0.0–1.0 si el subagente produce un score
    details     JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_task_id ON audit_log (task_id);

-- Chunks indexados para RAG. embedding en JSONB (ver rag/vector_store.py
-- para por qué, y cómo migrar a pgvector si el volumen lo justifica).
CREATE TABLE IF NOT EXISTS rag_chunks (
    chunk_id    TEXT PRIMARY KEY,
    doc_id      TEXT NOT NULL,
    position    INTEGER NOT NULL,
    text        TEXT NOT NULL,
    embedding   JSONB NOT NULL,
    doc_version TEXT NOT NULL DEFAULT 'v1',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc_id ON rag_chunks (doc_id);

-- Colecciones: agrupación lógica de documentos (ej. "Research", "Manuals").
CREATE TABLE IF NOT EXISTS collections (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Metadatos por documento: a qué colección pertenece, de qué fichero
-- vino, con qué modelo de embeddings se indexó, y el TEXTO EXTRAÍDO
-- completo (para poder reindexar sin pedir el fichero otra vez si
-- cambia el chunk size o el modelo de embeddings).
CREATE TABLE IF NOT EXISTS documents (
    doc_id          TEXT PRIMARY KEY,
    collection_id   TEXT REFERENCES collections(id) ON DELETE SET NULL,
    filename        TEXT,
    content_type    TEXT,
    doc_version     TEXT NOT NULL DEFAULT 'v1',
    embedding_model TEXT NOT NULL DEFAULT 'hashing_trick_256',
    raw_text        TEXT,
    n_chunks        INTEGER NOT NULL DEFAULT 0,
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_collection ON documents (collection_id);

-- Integraciones de n8n activables desde el backend, en vez de fijas por
-- código. Si un flujo no está en esta tabla, n8n_client lo registra
-- automáticamente como activado la primera vez que se usa (para no
-- romper el comportamiento por defecto), y a partir de ahí se puede
-- desactivar sin tocar código.
CREATE TABLE IF NOT EXISTS n8n_integrations (
    flow_name   TEXT PRIMARY KEY,
    enabled     BOOLEAN NOT NULL DEFAULT true,
    description TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
