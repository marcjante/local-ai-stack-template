# local-ai-stack-template

![Tests](https://github.com/marcjante/local-ai-stack-template/actions/workflows/tests.yml/badge.svg)

Plantilla reutilizable para proyectos de IA local, con multi-proyecto,
RAG real (con citas exactas), verificación de respuestas, y un panel
web completo ("Local AI Studio") para manejarlo todo sin tocar la
terminal.

No contiene lógica ni datos de ningún proyecto concreto — solo la
infraestructura. Pensada para clonarla como punto de partida y crear
tantos proyectos como haga falta dentro (RAG, tuberculosis, heridas,
soporte, lo que sea), cada uno aislado del resto.

## Arranque rápido

```bash
pip3 install -r requirements.txt
cp .env.example .env

# Redis y Postgres (nativos o vía Docker — ver docs/architecture.md
# y la guía de instalación para macOS/Linux/Windows)
python3 -c "from db.db import init_schema; init_schema()"

rq worker process --url redis://127.0.0.1:6379/0 &
python3 backend/main.py &
python3 dashboard/dashboard_service.py   # http://localhost:8090
```

La primera vez que abres el panel, un asistente de bienvenida comprueba
que todo lo necesario está bien antes de dejarte pasar — no hace falta
saber qué es Redis o RQ para arrancarlo.

## Qué hay dentro

**Infraestructura de tareas**: cola con reintentos y backoff (Redis +
RQ), estado trazable en Postgres, control de concurrencia hacia el LLM
(LLM Gateway, multi-proveedor: Ollama / OpenAI-compatible).

**RAG real, no un placeholder**: `rag/*.py` — chunking, embeddings,
vector store (backend JSON por defecto o pgvector real), reranking y
citas textuales exactas. Knowledge (el gestor documental del panel)
sube PDF, DOCX, TXT, MD, CSV, JSON y HTML, cada uno convertido a texto
con significado, no volcado crudo.

**Verificación de respuestas**: el worker `process` corre un circuito
de subagentes (recoger fuentes → generar respuesta → contrastar contra
las fuentes → detectar posible alucinación) y devuelve un veredicto
(`veraz` / `revisar` / `sin_verificar`) con cita exacta por afirmación,
más una auditoría completa de qué decidió cada paso.

**Multi-proyecto**: cada proyecto tiene sus propias colecciones,
documentos, tareas, integraciones de n8n y configuración (modelo,
system prompt, temperature, chunking) — aislado de verdad, probado
tanto a nivel de base de datos como a través de la interfaz real.
Incluye New Project Wizard (8 plantillas), Project Dashboard, y
export/import de un proyecto individual (`.ai-project.zip`).

**Permisos por proyecto**: tabla `project_members`
(admin/editor/viewer), aplicados en el backend vía
`require_project_role()`. El panel web sigue sin login — es una
herramienta de un solo usuario local; añadir login es la pieza que
falta si de verdad va a haber varios usuarios accediendo a la misma
instalación.

**Workers como plugins**: `fetch`, `process` y `notify` viven en
`workers/plugins/` y se descubren solos. Añadir un worker nuevo es
crear un fichero ahí con `QUEUE_NAME` y una función
`handle(task_id, payload)` — el backend lo detecta al arrancar, sin
tocar `backend/main.py` ni `config/services.yaml`. Esta es la vía
oficial para extender la plantilla (un plugin de PubMed, de búsqueda
web, de OCR, lo que necesite cada proyecto) sin tocar el núcleo.

**n8n en las dos direcciones**: el worker `process` avisa a un flujo al
terminar; n8n puede disparar una tarea llamando a
`POST /webhooks/n8n/<queue>`. Cada flujo se activa/desactiva por
proyecto sin tocar código.

**Evaluación**: framework genérico (`common/evaluation.py`) que compara
la salida real de cualquier función contra casos declarados en JSON.
Los resultados quedan guardados por proyecto, con histórico visible en
el Project Dashboard.

**Backup / Restore**: desde Settings, exporta toda la instalación
(config + base de datos completa) a un `.zip` vía `pg_dump`, o
restaura uno — probado de forma destructiva (borrar algo, restaurar,
confirmar que vuelve). El `.env` real nunca se incluye.

**Local AI Studio** (el panel, `http://localhost:8090`): Dashboard
interactivo, Diagnostics (detecta problemas concretos como una cola sin
worker, no solo semáforos), Playground (con comparación A/B de
modelos), Knowledge, Tasks, Plugins, Integrations, Logs, Evaluation,
Settings y Projects — 14 pantallas en total.

## Estructura

```
local-ai-stack-template/
├── config/
│   ├── services.yaml         # inventario de servicios: nombre, puerto, comandos
│   └── nginx.conf            # reverse proxy (TLS documentado, no activo)
├── backend/
│   ├── main.py                # API: auth, RAG, encolado, SSE, integrations, tasks, projects
│   └── auth.py                 # API key + JWT con roles, permisos por proyecto
├── workers/
│   ├── plugin_loader.py       # descubre workers/plugins/*.py automáticamente
│   ├── queue_conn.py          # Redis/RQ compartido
│   └── plugins/
│       ├── fetch.py, process.py, notify.py
├── llm_gateway/
│   └── llm_gateway.py         # proveedores (ollama/openai_compatible), routing, semáforo
├── rag/
│   ├── chunking.py, embeddings.py, vector_store.py
│   ├── retrieval.py, rerank.py, citations.py
│   └── file_parsers.py        # PDF/DOCX/TXT/MD/CSV/JSON/HTML → texto
├── common/
│   ├── logging_setup.py, verification.py, adaptive_pipeline.py
│   ├── n8n_client.py, evaluation.py, backup.py, project_export.py
│   ├── system_checks.py, diagnostics.py
├── db/
│   ├── schema.sql              # núcleo: tasks, audit_log, rag_chunks, documents,
│   │                            # collections, projects, project_settings,
│   │                            # project_members, evaluations, n8n_integrations
│   ├── schema_pgvector.sql     # opcional — solo si RAG_BACKEND=pgvector
│   └── db.py
├── dashboard/                   # "Local AI Studio": 14 páginas (ver docs/architecture.md)
├── evaluation/                  # casos de prueba en JSON
├── scripts/
│   ├── run_evaluation.py, start_stack.sh, stop_stack.sh
├── docker-compose.yml, Dockerfile
├── .env.example
├── requirements.txt
└── docs/
    └── architecture.md          # diario técnico completo, ronda a ronda
```

## No incluido, de forma deliberada

- Lógica clínica o de negocio específica de ningún proyecto.
- Modelos propietarios obligatorios — funciona con cualquier modelo de
  Ollama o compatible con la API de OpenAI.
- Datos de proyectos concretos.
- Exposición pública a Internet (TLS documentado en `nginx.conf`, no
  activo).
- Autenticación del panel web para despliegues multiusuario externos —
  los permisos por proyecto existen en el backend, no en el panel.
- Infraestructura cloud obligatoria — pensado para correr en local.
- Constructor visual de pipelines — para eso, usa n8n directamente.

## Migraciones (Alembic)

El esquema de base de datos se versiona con Alembic — historial real,
con rollback controlado (no `ALTER TABLE ... IF NOT EXISTS` acumulado
a mano).

```bash
alembic upgrade head       # instalación nueva, desde cero
alembic stamp head         # instalación ya existente: marca como al día
alembic downgrade -1       # deshacer la última migración
alembic revision -m "..."  # crear una migración nueva
```

`db/schema.sql` sigue siendo la referencia legible de lo que hay ahora
mismo — la migración baseline lo ejecuta tal cual para instalaciones
nuevas; cualquier cambio de esquema a partir de ahora es una migración
nueva, no una edición de ese fichero.

## Tests

30 tests reales contra Postgres/Redis de verdad (no mocks) — incluido
el que más importa: crear dos proyectos, un documento distinto en cada
uno, y confirmar que una búsqueda desde el proyecto A **jamás**
devuelve nada del B.

```bash
pip3 install -r requirements-dev.txt
pytest tests/ -v
```

Se ejecutan automáticamente en cada push/PR vía GitHub Actions
(`.github/workflows/tests.yml`), levantando Postgres y Redis reales.

## Documentación

- `docs/architecture.md` — diario técnico completo, ronda a ronda: qué
  se construyó, qué bugs aparecieron y cómo se corrigieron, qué está
  probado y cómo.
- Guía de instalación y uso con capturas reales del panel (pídela si no
  la tienes a mano).
