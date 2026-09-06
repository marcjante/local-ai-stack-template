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
