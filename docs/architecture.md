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

## El circuito de información veraz (dentro de `process`)

El worker `process` ya no es un único paso: es una cadena de subagentes,
cada uno con su propia responsabilidad y su veredicto guardado en
`audit_log` (tabla nueva en Postgres):

```
payload (prompt + fuentes)
        │
        ▼
┌───────────────────┐
│ gather_sources     │  reúne las fuentes que respaldarán la respuesta
└─────────┬──────────┘
          ▼
┌───────────────────┐
│ generate_answer    │  pide la respuesta al LLM (vía llm_gateway)
└─────────┬──────────┘
          ▼
┌───────────────────┐     ┌───────────────────────────┐
│ cross_check_sources │───►│ ¿cuántas fuentes           │
│ (common/verification)    │  independientes lo dicen?  │
└─────────┬──────────┘    └───────────────────────────┘
          ▼
┌───────────────────┐     ┌───────────────────────────┐
│ detect_hallucination│──►│ ¿la respuesta se apoya      │
│ (common/verification)   │  en las fuentes reales?     │
└─────────┬──────────┘    └───────────────────────────┘
          ▼
   veredicto final: 'veraz' o 'revisar'
          │
          ▼
┌───────────────────┐
│ trigger_n8n_flow   │  avisa a n8n con el resultado (saliente)
│ (common/n8n_client)│
└────────────────────┘
```

Cada paso queda en `audit_log` con `task_id`, `step`, `subagent`,
`verdict` y `confidence` — se puede reconstruir exactamente qué pasó con
cualquier tarea llamando a `GET /tasks/<id>/audit`.

**Importante:** `cross_check_sources` y `detect_hallucination` son
heurísticas simples (coincidencia de texto / solapamiento de palabras) a
propósito, porque esto es una plantilla. Para un proyecto real, sustitúyelas
por comparación semántica de verdad o un segundo LLM actuando de juez.

Probado en real durante el desarrollo: se montó un Ollama y un n8n de
mentira (mocks) para verificar el circuito completo de punta a punta —
los 6 pasos quedaron en `audit_log` y el mock de n8n recibió el resultado
final con su veredicto.

## n8n en las dos direcciones

- **Worker → n8n (saliente):** `common/n8n_client.trigger_n8n_flow()`
  llama a `{N8N_BASE_URL}/webhook/<flow>`. Úsalo para todo lo que no sea
  puramente Python: mandar un email, escribir en una hoja de cálculo,
  avisar por Slack... Un fallo aquí no tumba la tarea, solo queda
  registrado en `audit_log` como `fallo_notificacion`.

- **n8n → backend (entrante):** un flujo de n8n puede hacer un HTTP
  Request a `POST /webhooks/n8n/<queue>` (con la cabecera
  `X-N8N-Secret`, ver `.env`) para encolar una tarea, igual que haría el
  propio backend. Probado: sin el secreto da 401, con él encola
  correctamente.

## Segunda ronda de mejoras (RAG real, verificación por afirmaciones, pipeline adaptativo, JWT)

### RAG como núcleo real (🔴1)

`rag/` ya no son placeholders — es un pipeline que FUNCIONA de punta a
punta sin depender de un modelo pesado:

- `chunking.py` — trocea documentos en chunks con solapamiento.
- `embeddings.py` — embedding por defecto vía *hashing trick* (determinista,
  sin dependencias, dimensión 256). Suficiente para que todo el pipeline
  se pruebe de verdad; sustitúyelo por un modelo real cuando el proyecto
  lo necesite — el resto no cambia.
- `vector_store.py` — guarda y busca chunks en una tabla Postgres
  (`rag_chunks`), calculando similitud coseno en Python. Documentado cómo
  migrar a **pgvector** (misma Postgres, con extensión + índice ANN) o
  **Qdrant** (servicio dedicado) si el volumen lo justifica (🟠5) — son
  stubs con `NotImplementedError` a propósito, para no arrastrar
  dependencias que la mayoría de proyectos no usarán.
- `retrieval.py` — `index_document()` y `retrieve()`.
- `rerank.py` — combina similitud vectorial + solapamiento léxico.
- `citations.py` — cita el fragmento EXACTO, no un resumen.

Probado en real: se indexaron 2 documentos (uno de hockey, uno de fútbol)
y una consulta sobre hockey recuperó el documento correcto muy por encima
del irrelevante.

Endpoints nuevos en el backend: `POST /rag/index` (indexar) y
`GET /rag/search?q=...` (buscar), ambos protegidos con JWT por rol.

### Verificación por afirmaciones, no por respuesta completa (🔴2)

`common/verification.py` parte la respuesta del LLM en afirmaciones
(frases) y verifica CADA UNA por separado contra los chunks del RAG,
exigiendo una cita textual real (solapamiento de palabras significativas
por encima de un umbral), no una coincidencia vaga de la respuesta entera.

Cada afirmación queda como `citado` / `parcial` / `sin_respaldo` /
`sin_fuentes`, con la cita exacta (doc_id, chunk_id, fragmento) cuando la
hay. El veredicto agregado (`todo_citado` / `mayoria_citada` /
`mayoria_sin_citar`) sale de combinar los veredictos de cada afirmación.

Probado en real: una respuesta de 2 afirmaciones sobre hockey patines,
contra un documento indexado de verdad, dio citas exactas correctas para
ambas.

### Pipeline adaptativo (🔴3)

`common/adaptive_pipeline.py` decide, para cada tarea, qué hace falta:

- **De dónde saca las fuentes** (`gather_candidate_chunks`): si el payload
  ya trae `sources`, las trocea al vuelo sin tocar el índice; si trae
  `doc_id`, busca solo ahí; si no trae nada, busca en todo lo indexado.
  Cada camino queda auditado (`gather_path`).
- **Si hace falta verificar** (`decide_need_verification`): si no hay
  ningún chunk candidato, o la respuesta es trivial (menos de 6 palabras),
  se salta el subagente de verificación entero — no tiene sentido partir
  en frases y comparar contra nada, o para un "sí"/"no".

Probado en real, los tres casos por separado: sin chunks → `False`;
respuesta trivial → `False`; caso normal → `True`.

### JWT con roles (🔴4, parcial — TLS no se puede simular en código)

`backend/auth.py` añade JWT junto a la API key existente:

- `POST /auth/token` (protegido con la API key maestra) emite un token
  con un `role` — es "quien tiene la key raíz emite credenciales más
  finas", no un login público.
- `@require_role("admin", "escritor")` protege endpoints por rol;
  `@require_role()` sin argumentos exige solo que el token sea válido.
- `/rag/index` requiere rol `admin` o `escritor`; `/rag/search` acepta
  cualquier rol autenticado.

Probado en real: sin token → 401; token de `lector` contra `/rag/index`
→ 403; token de `escritor` → 201 e indexa correctamente.

**TLS de verdad no se puede simular en código** — hace falta un dominio
real y un certificado (Let's Encrypt, Caddy, o el CA que use tu infra).
Lo dejé documentado y comentado en `config/nginx.conf`: un bloque
`server { listen 443 ssl; ... }` listo para activar en cuanto haya
certificados, más la redirección 80→443.

### Routing de modelo por tarea (🟠6)

`llm_gateway.py` tiene un `MODEL_ROUTES` (`default` / `rapido` /
`razonamiento` por defecto, configurable por `.env`). El worker `process`
manda `task_type` en la petición y el gateway elige el modelo — probado:
pedir `task_type: "rapido"` hizo que el gateway devolviera
`llama3.1:8b` como modelo usado.

### Auditoría enriquecida (🟠8)

Cada paso de `audit_log` ahora guarda más contexto real, no solo un
veredicto: el paso `generate` guarda `model_used`, `task_type` y el
`prompt` completo; el paso `context_used` guarda las `doc_version` y los
`chunk_id` de los chunks realmente usados. Con esto, `GET
/tasks/<id>/audit` reconstruye no solo QUÉ pasó, sino con qué modelo, qué
prompt y qué versión de qué documento.

### Lo que se queda igual a propósito (🟡10)

Redis + RQ se mantiene tal cual — no se ha metido Celery ni Kafka. Para
el volumen de una plantilla (y de la mayoría de proyectos que arrancan
desde aquí), RQ ya da reintentos, backoff y dead-letter sin la
complejidad operativa de un cluster de Kafka.

### Pendiente / fuera de esta ronda

- **🟠7 (framework de evaluación/benchmarks)**: no se ha tocado en esta
  ronda — es un módulo independiente (comparar outputs contra un set de
  referencia) que tiene sentido como pieza propia cuando un proyecto
  concreto defina qué significa "correcto" para su caso. Generalizado,
  sin nada específico de ningún dominio.
- **🟡9 (métricas RAG/LLM en el dashboard)**: el LLM Gateway ya expone
  `/metrics` (con desglose por modelo) — falta que el panel las muestre
  visualmente. Pendiente de la próxima ronda.
