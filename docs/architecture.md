# Arquitectura del stack

Plantilla para proyectos de IA local con trabajo pesado repartido entre
varios workers especializados, con reintentos, trazabilidad de estado,
control de concurrencia hacia el LLM y autenticación básica.

## Servicios

| Servicio               | Puerto | Rol                                                                 |
|------------------------|--------|----------------------------------------------------------------------|
| LLM local (Ollama)     | 11434  | Sirve los modelos. Nadie debería llamarlo salvo `llm_gateway`.       |
| LLM Gateway            | 8091   | Único punto de acceso al LLM: limita llamadas concurrentes.          |
| Base vectorial         | 8000   | Embeddings / búsqueda semántica (RAG), ver `rag/`.                   |
| Cola (Redis + RQ)      | 6379   | Encola tareas, gestiona reintentos, backoff y jobs fallidos.         |
| Base de datos (Postgres)| 5432  | Estado de cada tarea: pending/running/completed/failed.              |
| Backend API            | 8080   | Autentica, encola en la cola especializada, expone estado (con SSE). |
| Worker: fetch          | —      | Trae datos externos (APIs, ficheros). Cola `fetch`.                  |
| Worker: process        | —      | Trabajo pesado, llama a `llm_gateway`. Cola `process`.               |
| Worker: notify         | —      | Avisa cuando algo termina (webhook/SSE). Cola `notify`.               |
| Automatización (n8n)   | 5678   | Backups, tareas programadas, integraciones.                          |
| Panel de control       | 8090   | Salud real (HTTP), CPU/RAM, profundidad de colas.                    |
| Reverse proxy (Nginx)  | 80     | Punto de entrada único hacia dashboard + backend.                    |

Los workers no tienen puerto HTTP propio (son procesos `rq worker`), así
que el panel no puede darles un "activo/parado" directo — se supervisan
indirectamente por la profundidad de sus colas (si crece sin parar, algo
va mal) y por los logs con `task_id` de `common/logging_setup.py`.

## Cómo se conectan

```
                    Internet / navegador
                            │
                     ┌──────▼──────┐
                     │    Nginx     │  :80
                     └──────┬──────┘
                ┌───────────┴────────────┐
                │                        │
        ┌───────▼────────┐      ┌────────▼─────────┐
        │ Panel de control│      │   Backend API     │  :8080
        │    :8090        │◄─────┤ (auth X-API-Key)  │
        └───────┬─────────┘      └─┬──────┬────┬─────┘
                │ health-check      │      │    │
                │ HTTP real         │      │    │ encola en la
   ┌────────────┼────────┐         │      │    │ cola correcta
   │            │        │         │      │    ▼
┌──▼───┐  ┌─────▼────┐ ┌─▼──────┐  │      │  ┌──────────────┐
│Automat│ │  Base    │ │Postgres│  │      │  │ Redis (RQ)   │
│(n8n)  │ │ vectorial│ │ :5432  │◄─┼──────┼──┤   :6379      │
│:5678  │ │  :8000   │ │        │  │      │  └──────┬───────┘
└───────┘ └──────────┘ └────────┘  │      │         │ BLPOP por cola
                                    │      │  ┌──────┼──────┬─────────┐
                              ┌─────▼──┐   │  │      │      │         │
                              │ LLM    │   │┌─▼───┐┌─▼────┐┌▼──────┐
                              │Gateway │◄──┼┤fetch││process││notify │
                              │ :8091  │   │└─────┘└──┬───┘└───────┘
                              └───┬────┘   │          │ llama al gateway,
                                  │        │          │ nunca a Ollama directo
                              ┌───▼────┐   │
                              │ Ollama │◄──┘
                              │ :11434 │
                              └────────┘
```

- El **backend** decide, por endpoint (`/enqueue/<cola>`), a qué worker
  especializado va cada tarea. Nunca llama al LLM directamente: si necesita
  generar algo, encola en `process`, que a su vez llama a `llm_gateway`.
- **Redis + RQ** reemplaza el `BLPOP` manual de la versión anterior:
  cada tarea tiene reintentos con backoff (3 intentos: 10s/30s/60s) y,
  si los agota, RQ la deja en su *failed job registry* — no desaparece.
- **Postgres** guarda el estado real de cada tarea (`db/schema.sql`),
  así que "¿qué pasó con la tarea X?" tiene siempre una respuesta,
  incluso después de reiniciar todo el stack.
- El **LLM Gateway** es la única puerta a Ollama: un semáforo limita
  cuántas peticiones concurrentes le llegan, así que aunque haya 10
  tareas de `process` a la vez, Ollama no se satura.
- El **backend** exige la cabecera `X-API-Key` en los endpoints que
  escriben (`/enqueue/...`) o leen estado (`/tasks/...`) — cámbialo por
  JWT si el proyecto lo necesita, el punto de enganche es
  `require_api_key()` en `backend/main.py`.
- El **panel de control** ya no se conforma con "el puerto está abierto":
  para servicios HTTP hace un GET real a su `health_endpoint` y solo
  cuenta como activo si responde. Además muestra CPU/RAM de la máquina
  y la profundidad de las 3 colas.

## Probarlo de extremo a extremo

Con Redis, Postgres, el backend y al menos un worker arrancados:

```bash
# 1. Salud real (no solo "el proceso vive")
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/ready      # comprueba Redis y Postgres de verdad

# 2. Sin API key falla (401)
curl -X POST http://127.0.0.1:8080/enqueue/fetch -d '{}'

# 3. Con API key, se encola y un worker la recoge
curl -X POST http://127.0.0.1:8080/enqueue/fetch \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"args": ["ejemplo.com"]}'

# 4. Consultar el resultado
curl http://127.0.0.1:8080/tasks/<task_id> -H "X-API-Key: $API_KEY"
```

Esto se ha probado en real durante el desarrollo de esta plantilla: la
tarea pasa por `pending → running → completed` en Postgres, y el log del
worker muestra el `task_id` en cada línea.

## Con Docker

```bash
cp .env.example .env    # y ajusta API_KEY, contraseñas, etc.
docker compose up -d redis postgres          # solo infraestructura
docker compose up -d                         # todo el stack de Python
```

Ollama, ChromaDB y Nginx se quedan fuera de `docker-compose.yml` a
propósito (ver comentarios en el propio fichero) — añádelos si tu
proyecto los necesita en contenedor.

## Cómo adaptar esto a un proyecto nuevo

1. Edita `config/services.yaml` con los servicios reales.
2. Sustituye la lógica de ejemplo en `workers/*_jobs.py` (ahora mismo
   `fetch_task` y `notify_task` son placeholders; `process_task` sí llama
   de verdad al `llm_gateway`).
3. Si el proyecto necesita RAG, implementa `rag/embeddings.py`,
   `retrieval.py`, `rerank.py` y `citations.py` — están separados a
   propósito para poder cambiar cada pieza sin tocar las demás.
4. Define el esquema real que necesites en `db/schema.sql` (la tabla
   `tasks` es genérica y reutilizable, añade las tuyas al lado).
5. No toques `dashboard_service.py` salvo que cambie la lógica de
   arranque/parada en sí — lee todo de `services.yaml`.
