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
curl -X POST http://127.0.0.1:8080/enqueue/fetch \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"args": ["ejemplo.com"]}'
# → {"task_id": "...", "queue": "fetch", "status": "pending"}

curl http://127.0.0.1:8080/tasks/<task_id> -H "X-API-Key: $API_KEY"
# → status pasa de pending a running a completed
```

Ver `docs/architecture.md` para el diagrama completo, por qué está
separado así, y cómo adaptar la plantilla a un proyecto real.

## Qué NO incluye (a propósito)

- Lógica de negocio real: `workers/*_jobs.py` tienen placeholders donde
  va el trabajo de cada proyecto.
- RAG funcional: `rag/*.py` están separados por responsabilidad pero
  lanzan `NotImplementedError` — cada proyecto conecta su propia base
  vectorial y modelo de embeddings.
- HTTPS/TLS y JWT: hay una API key simple como base; para producción
  real, añade TLS delante (Nginx/Caddy) y valora JWT si necesitas
  usuarios distintos con permisos distintos.
