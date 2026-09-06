-- schema.sql
-- Esquema mínimo para dar trazabilidad real a las tareas: estado explícito
-- (pending/running/completed/failed), resultado, error y nº de intentos.

-- Projects/Workspaces: la capa que hace que esto sea una plataforma
-- reutilizable, no "el panel de un proyecto concreto". Todo lo demás
-- cuelga de un project_id — colecciones y tareas directamente, documentos
-- y chunks indirectamente (vía collection_id -> project_id).
CREATE TABLE IF NOT EXISTS projects (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT,
    project_type TEXT NOT NULL DEFAULT 'blank',  -- plantilla usada al crearlo (solo informativo)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Configuración propia por proyecto: modelo principal/fallback, modelo
-- de embeddings, system prompt, temperature, chunking/retrieval. Una
-- fila por proyecto (PK = project_id).
CREATE TABLE IF NOT EXISTS project_settings (
    project_id       TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    default_model    TEXT NOT NULL DEFAULT 'default',
    fallback_model   TEXT,
    embedding_model  TEXT NOT NULL DEFAULT 'hashing_trick_256',
    system_prompt    TEXT,
    temperature      REAL NOT NULL DEFAULT 0.4,
    top_k            INTEGER NOT NULL DEFAULT 5,
    chunk_size       INTEGER NOT NULL DEFAULT 120,
    chunk_overlap    INTEGER NOT NULL DEFAULT 20,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- El proyecto 'default' siempre existe: cualquier instalación que ya
-- tuviera datos de antes de esta ronda (colecciones, tareas...) se
-- entiende que pertenecen a él — no se pierde ni se mezcla nada al
-- actualizar una instalación existente.
INSERT INTO projects (id, name, description, project_type)
VALUES ('default', 'Default', 'Proyecto por defecto (datos previos a multi-proyecto)', 'blank')
ON CONFLICT (id) DO NOTHING;

INSERT INTO project_settings (project_id) VALUES ('default')
ON CONFLICT (project_id) DO NOTHING;

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

-- Migración: instalaciones ya existentes no tienen esta columna todavía.
-- ADD COLUMN IF NOT EXISTS es idempotente: no rompe nada si ya existe.
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT 'default' REFERENCES projects(id);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status);
CREATE INDEX IF NOT EXISTS idx_tasks_queue ON tasks (queue);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks (project_id);

-- Traza de cada paso del "circuito de información veraz": qué subagente
-- actuó, sobre qué tarea, qué decidió y por qué. Una tarea puede tener
-- varias filas aquí (una por subagente que participó). No lleva
-- project_id propio a propósito: se hereda de tasks.project_id vía
-- task_id — evita duplicar la columna en una tabla que solo tiene
-- sentido junto a su tarea.
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
-- Sin project_id propio: se hereda vía doc_id -> documents.collection_id
-- -> collections.project_id, para no duplicar la columna en la tabla
-- más grande (potencialmente miles de filas por documento).
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

-- Colecciones: agrupación lógica de documentos (ej. "Research", "Manuals"),
-- siempre dentro de un proyecto — dos proyectos pueden tener cada uno su
-- propia colección "default" sin chocar entre sí (el id de colección es
-- único POR PROYECTO, no global).
CREATE TABLE IF NOT EXISTS collections (
    id          TEXT NOT NULL,
    project_id  TEXT NOT NULL DEFAULT 'default' REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, id)
);

-- Migración desde instalaciones anteriores a multi-proyecto: la tabla ya
-- existía con PK solo en `id`. Se añade la columna si falta y se
-- recompone la PK a (project_id, id) — necesario para que dos proyectos
-- puedan tener cada uno una colección "default" sin chocar.
ALTER TABLE collections ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_collection_id_fkey;
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'collections'::regclass AND contype = 'p' AND array_length(conkey, 1) = 1
    ) THEN
        ALTER TABLE collections DROP CONSTRAINT collections_pkey;
        ALTER TABLE collections ADD PRIMARY KEY (project_id, id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_collections_project ON collections (project_id);

-- Metadatos por documento: a qué colección pertenece, de qué fichero
-- vino, con qué modelo de embeddings se indexó, y el TEXTO EXTRAÍDO
-- completo (para poder reindexar sin pedir el fichero otra vez si
-- cambia el chunk size o el modelo de embeddings). doc_id sigue siendo
-- único globalmente por simplicidad (un doc_id ya incluye normalmente
-- el nombre de fichero, con baja probabilidad real de choque entre
-- proyectos; si hiciera falta unicidad estricta por proyecto, el punto
-- de cambio es aquí y en rag_chunks.doc_id).
CREATE TABLE IF NOT EXISTS documents (
    doc_id          TEXT PRIMARY KEY,
    collection_id   TEXT,
    project_id      TEXT NOT NULL DEFAULT 'default' REFERENCES projects(id) ON DELETE CASCADE,
    filename        TEXT,
    content_type    TEXT,
    doc_version     TEXT NOT NULL DEFAULT 'v1',
    embedding_model TEXT NOT NULL DEFAULT 'hashing_trick_256',
    raw_text        TEXT,
    n_chunks        INTEGER NOT NULL DEFAULT 0,
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE documents ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT 'default' REFERENCES projects(id);

CREATE INDEX IF NOT EXISTS idx_documents_collection ON documents (collection_id);
CREATE INDEX IF NOT EXISTS idx_documents_project ON documents (project_id);

-- Integraciones de n8n activables desde el backend, en vez de fijas por
-- código. Si un flujo no está en esta tabla, n8n_client lo registra
-- automáticamente como activado la primera vez que se usa (para no
-- romper el comportamiento por defecto), y a partir de ahí se puede
-- desactivar sin tocar código. Por proyecto: el mismo nombre de flujo
-- puede estar activado en un proyecto y desactivado en otro.
CREATE TABLE IF NOT EXISTS n8n_integrations (
    flow_name   TEXT NOT NULL,
    project_id  TEXT NOT NULL DEFAULT 'default' REFERENCES projects(id) ON DELETE CASCADE,
    enabled     BOOLEAN NOT NULL DEFAULT true,
    description TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, flow_name)
);

ALTER TABLE n8n_integrations ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT 'default';
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'n8n_integrations'::regclass AND contype = 'p' AND array_length(conkey, 1) = 1
    ) THEN
        ALTER TABLE n8n_integrations DROP CONSTRAINT n8n_integrations_pkey;
        ALTER TABLE n8n_integrations ADD PRIMARY KEY (project_id, flow_name);
    END IF;
END $$;
