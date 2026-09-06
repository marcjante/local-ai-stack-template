# local-ai-stack-template

Plantilla reutilizable para proyectos de IA local con trabajo pesado
repartido entre workers especializados: cola con reintentos (Redis + RQ),
estado trazable en Postgres, control de concurrencia hacia el LLM,
autenticación básica y un panel de control con salud real (no solo
"el puerto está abierto").

No contiene lógica ni datos de ningún proyecto concreto — solo la
infraestructura. Pensada para clonarla como punto de partida.

## Estructura

```
local-ai-stack-template/
├── config/
│   ├── services.yaml        # inventario de servicios: nombre, puerto, comandos
│   └── nginx.conf           # reverse proxy de ejemplo
├── backend/
│   └── main.py              # API: auth, encolado por tipo de tarea, /health /ready /metrics, SSE
├── workers/
│   ├── queue_conn.py        # conexión y colas de RQ compartidas (fetch/process/notify)
│   ├── fetch_jobs.py        # worker especializado: traer datos externos
│   ├── process_jobs.py      # worker especializado: trabajo pesado, llama a llm_gateway
│   └── notify_jobs.py       # worker especializado: avisos al terminar
├── llm_gateway/
│   └── llm_gateway.py       # único punto de acceso a Ollama, limita concurrencia
├── rag/
│   ├── embeddings.py        # texto → vector
│   ├── retrieval.py         # vector/consulta → documentos candidatos
│   ├── rerank.py            # documentos candidatos → los N más relevantes
│   └── citations.py         # documentos finales → formato de cita
├── db/
│   ├── schema.sql           # tabla tasks: pending/running/completed/failed
│   └── db.py                # helpers de conexión y estado
├── common/
│   └── logging_setup.py     # logging con task_id, compartido por backend y workers
├── dashboard/
│   ├── dashboard_service.py # panel (Flask): salud HTTP real, CPU/RAM, profundidad de colas
│   └── templates/index.html
├── scripts/
│   ├── start_stack.sh
│   └── stop_stack.sh
├── docs/
│   └── architecture.md      # diagrama y explicación de cómo se conecta todo
├── docker-compose.yml       # Redis + Postgres + backend + workers + dashboard
├── Dockerfile
├── .env.example
└── requirements.txt
```

## Uso rápido (sin Docker)

```bash
pip install -r requirements.txt
cp .env.example .env    # y pon una API_KEY real

redis-server --port 6379 &
# Postgres: crea la base indicada en .env (createdb stack_template)

python3 backend/main.py &
python3 llm_gateway/llm_gateway.py &     # si tu proyecto usa LLM
rq worker fetch --url redis://127.0.0.1:6379/0 &
rq worker process --url redis://127.0.0.1:6379/0 &
rq worker notify --url redis://127.0.0.1:6379/0 &
python3 dashboard/dashboard_service.py   # http://localhost:8090
```

## Uso rápido (con Docker)

```bash
cp .env.example .env
docker compose up -d
```

## Probar el flujo completo

```bash
# Autenticación JWT (además de la API key existente)
TOKEN=$(curl -s -X POST http://127.0.0.1:8080/auth/token \
  -H "X-API-Key: $API_KEY" -d '{"subject":"marc","role":"escritor"}' | jq -r .token)

# Indexar un documento real en el RAG
curl -X POST http://127.0.0.1:8080/rag/index \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"doc_id":"doc1","text":"...","doc_version":"v1"}'

# Buscar en el RAG
curl "http://127.0.0.1:8080/rag/search?q=..." -H "Authorization: Bearer $TOKEN"

# Lanzar una tarea de 'process': el circuito adaptativo decide de dónde
# saca las fuentes (doc_id, sources directas, o índice global), si hace
# falta verificar, y cita afirmación por afirmación
curl -X POST http://127.0.0.1:8080/enqueue/process \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"prompt": "...", "doc_id": "doc1", "task_type": "rapido"}'
# → {"task_id": "...", "queue": "process", "status": "pending"}

curl http://127.0.0.1:8080/tasks/<task_id> -H "X-API-Key: $API_KEY"
# → verdict: "veraz" / "revisar" / "sin_verificar", con citas exactas por afirmación

curl http://127.0.0.1:8080/tasks/<task_id>/audit -H "X-API-Key: $API_KEY"
# → traza completa: qué modelo respondió, qué chunks se usaron, qué se decidió saltar y por qué
```

n8n en las dos direcciones:
- El worker `process` avisa a un flujo de n8n al terminar (`common/n8n_client.py`).
- n8n puede disparar una tarea llamando a `POST /webhooks/n8n/<queue>`
  con la cabecera `X-N8N-Secret`.
- Cada flujo se puede activar/desactivar sin tocar código: `GET
  /integrations`, `POST /integrations/<flow>/enable|disable` (rol admin).

## Workers como plugins

`fetch`, `process` y `notify` viven en `workers/plugins/` y se descubren
solos. Añadir un worker nuevo es crear un fichero ahí con `QUEUE_NAME` y
una función `handle(task_id, payload)` — el backend lo detecta al
arrancar, sin tocar `backend/main.py` ni `config/services.yaml`.

## Evaluación

```bash
python3 scripts/run_evaluation.py --cases evaluation/cases_rag_example.json --target rag
python3 scripts/run_evaluation.py --cases mis_casos.json --target plugin:process
```

Framework genérico (`common/evaluation.py`): compara la salida real de
cualquier función contra comprobaciones declaradas en JSON
(`expect_contains`, `expect_field`, `expect_min_score`).

Ver `docs/architecture.md` para el diagrama completo, por qué está
separado así, y cómo adaptar la plantilla a un proyecto real.

## Panel de control: Docker, logs en vivo y proveedores de LLM

- El panel (`http://localhost:8090`) puede arrancar/parar/reiniciar cada
  servicio vía `docker compose` (si tiene `docker_service` en
  `services.yaml` y Docker está instalado), además del modo nativo.
- Cada servicio tiene un botón "Ver logs en vivo" (Server-Sent Events,
  sin recargar la página).
- El LLM Gateway soporta varios proveedores (`ollama`,
  `openai_compatible`) — `GET /providers` los lista, y cada `task_type`
  en `.env` decide cuál usar por defecto.

## Qué NO incluye (a propósito)

- Lógica de negocio real: `workers/*_jobs.py` tienen placeholders donde
  va el trabajo de cada proyecto.
- RAG funcional: `rag/*.py` están separados por responsabilidad pero
  lanzan `NotImplementedError` — cada proyecto conecta su propia base
  vectorial y modelo de embeddings.
- HTTPS/TLS y JWT: hay una API key simple como base; para producción
  real, añade TLS delante (Nginx/Caddy) y valora JWT si necesitas
  usuarios distintos con permisos distintos.
