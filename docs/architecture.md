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

## Tercera ronda: panel con control de Docker + logs en vivo + selector de proveedor de LLM

De la tabla "interfaz gráfica completa" (dashboard interactivo, plugins,
constructor visual de pipelines...), esta ronda cubre las 3 partes que
son extensión directa de lo que ya había — el resto (constructor visual
de pipelines, sistema de plugins, RAG con Qdrant/pgvector reales,
integraciones de n8n activables) queda deliberadamente fuera: son diseños
nuevos, no mejoras incrementales, y no tiene sentido construirlos a medias
sin decidir antes cómo deben funcionar.

### Control de Docker desde el panel

Cada servicio de `services.yaml` tiene ahora un campo `docker_service`
que lo enlaza con su nombre en `docker-compose.yml` (o `null` si no tiene
equivalente en Docker — Ollama, ChromaDB y Nginx se gestionan solo de
forma nativa, ver comentarios en `docker-compose.yml`).

El panel añade, por servicio con `docker_service`, tres botones que
llaman a `docker compose up -d / stop / restart <servicio>` vía
`POST /api/docker/<id>/<start|stop|restart>`. Si Docker no está instalado
o el servicio no tiene equivalente, el panel lo dice con un mensaje claro
en vez de fallar en silencio.

**Importante:** esto asume que el propio panel corre de forma NATIVA en
la máquina que tiene Docker (como en todos los ejemplos de esta plantilla
hasta ahora) — puede llamar a `docker compose` como cualquier comando del
host. Si metieras el panel dentro de un contenedor, necesitarías montar
el socket de Docker y añadir el cliente `docker` a esa imagen; no se ha
hecho a propósito, para no meter docker-in-docker si no hace falta.

Probado en real (sin Docker instalado en el entorno de desarrollo, que es
justo el caso límite más importante de cubrir bien): pedir una acción
Docker sobre un servicio devuelve `"Docker no está instalado..."` en vez
de un error genérico o un fallo silencioso; pedirla sobre un servicio sin
`docker_service` (como `llm`) devuelve `"no tiene equivalente en
docker-compose.yml"`.

### Logs en vivo (Server-Sent Events)

Los procesos nativos que arranca el panel (`/api/start/<id>`) ahora
redirigen su salida a `logs/<id>.log`. El endpoint
`GET /logs/<id>/stream` sirve ese fichero como SSE: solo líneas nuevas a
partir del momento en que se abre el stream (no vuelca el histórico
entero cada vez).

Para servicios en Docker, el mismo endpoint puede usar
`docker compose logs -f --tail 50 <servicio>` (con `?source=docker`, o
automáticamente si no hay fichero de log nativo y el servicio sí tiene
`docker_service`).

Probado en real: se abrió el stream, se escribieron dos líneas nuevas en
el fichero de log mientras el stream estaba activo, y ambas llegaron
correctamente por SSE en tiempo real (sin recargar nada).

### Selector de modelo/proveedor en el LLM Gateway

`MODEL_ROUTES` ya no mapea `task_type` a un simple nombre de modelo —
mapea a `{provider, model}`. Hay dos adaptadores de proveedor:

- `ollama` — el que ya había.
- `openai_compatible` — cualquier servidor que hable el protocolo de
  OpenAI (`/v1/chat/completions`): LM Studio, vLLM, text-generation-webui,
  o la propia API de OpenAI si configuras `OPENAI_COMPAT_URL` y la key.

`POST /generate` acepta `task_type` (usa la ruta configurada) o
`provider`/`model` explícitos para forzar uno concreto en una llamada
puntual. `GET /providers` lista los proveedores disponibles y las rutas
configuradas.

Probado en real con un Ollama simulado y un servidor OpenAI-compatible
simulado a la vez: `task_type: "default"` fue a Ollama, `task_type:
"razonamiento"` fue al servidor OpenAI-compatible, un override manual de
`provider`/`model` en la misma llamada funcionó, y pedir un proveedor
inexistente dio un 400 con la lista de proveedores válidos.

## Cuarta ronda: métricas del gateway en el panel, pgvector real, plugins, n8n activable, evaluación

### Métricas del LLM Gateway en el panel (🟡9)

El dashboard ahora pinta en vivo lo que `/metrics` del gateway ya
exponía: peticiones en curso/totales/rechazadas y desglose por modelo
usado. Probado en real: tras una llamada de prueba al gateway, el panel
mostró exactamente esa llamada reflejada en `by_model`.

### pgvector real, con un bug real encontrado y corregido (🟠5)

Se activó la extensión `vector` en Postgres y se implementó el backend
completo en `rag/vector_store.py` (antes era un stub con
`NotImplementedError`). Durante las pruebas apareció un problema real:
el índice `ivfflat`, si se crea ANTES de insertar ningún dato (como pasa
al inicializar el esquema en una base vacía), queda mal calibrado y las
búsquedas devuelven **cero resultados, sin ningún error** — un fallo
silencioso especialmente peligroso porque no hay forma de notar que algo
va mal salvo probándolo con datos reales, que es justo lo que se hizo
aquí. Solución: se cambió a índice **HNSW**, que no necesita
"entrenarse" con datos previos. Verificado con los mismos documentos de
prueba de siempre, dando resultados idénticos al backend por defecto.

Activar este backend: `RAG_BACKEND=pgvector` en `.env` (requiere
`CREATE EXTENSION vector;` en la base, ver `db/schema.sql`).

Qdrant se queda sin implementar (sigue siendo un stub) — a diferencia de
pgvector, exige levantar un servicio nuevo, y no tiene sentido añadir esa
pieza operativa hasta que el volumen de un proyecto concreto lo justifique.

### Sistema de plugins para workers

Este es el cambio más grande de la ronda. `fetch`, `process` y `notify`
ya no son ficheros sueltos importados a mano en `backend/main.py` — son
plugins en `workers/plugins/`, descubiertos automáticamente por
`workers/plugin_loader.py`. Cualquier fichero ahí con:

```python
QUEUE_NAME = "mi_cola"
def handle(task_id: str, payload: dict) -> dict:
    ...
```

aparece solo en `/enqueue/mi_cola`, sin tocar `backend/main.py` ni
`config/services.yaml`. Se arranca con `rq worker mi_cola`.

**Probado de la forma más convincente posible**: se creó un plugin de
prueba (`echo.py`) sin tocar ningún otro fichero, se reinició el backend,
y ya estaba disponible; se encoló una tarea, un worker genérico la
procesó, y se pudo consultar el resultado — todo antes de borrar el
plugin de prueba.

### n8n con integraciones activables, no fijas por código

Nueva tabla `n8n_integrations` (flow_name, enabled). `n8n_client.py`
comprueba el estado antes de llamar a cualquier flujo — si no existe
todavía, se autorregistra como activado (para no romper nada por
defecto). Endpoints: `GET /integrations` (público), `POST
/integrations/<flow>/enable` y `/disable` (rol admin).

Probado en real: se desactivó `resultado-tarea`, se lanzó una tarea de
`process`, y **n8n no recibió ninguna llamada HTTP** (quedó auditado como
`omitido_desactivado`, no como fallo). Se reactivó, se lanzó otra tarea,
y esta vez n8n sí recibió el resultado completo.

### Framework de evaluación/benchmarks, genérico

`common/evaluation.py` no sabe nada de ningún dominio: compara la salida
de cualquier función contra comprobaciones simples (`expect_contains`,
`expect_field`, `expect_min_score`) declaradas en JSON.
`scripts/run_evaluation.py` lo ejecuta desde terminal contra dos tipos de
objetivo: `--target rag` (el pipeline de RAG real) o `--target
plugin:<nombre>` (el `handle()` real de cualquier worker, con lectura/
escritura real en Postgres).

Probado en real dos veces: contra el RAG (3/3 casos, incluida una cita
verificada contra el fragmento exacto del documento) y contra el plugin
`notify` (1/1). Ejemplo incluido en `evaluation/cases_rag_example.json`.

### Lo que sigue sin construir

- **Constructor visual de pipelines** — mantenida la recomendación de
  usar n8n de verdad para eso, en vez de reconstruirlo.
- Nada más queda pendiente de la tabla original de esta fase —las 6
  filas trabajables ya están cubiertas entre esta ronda y la anterior.

## Quinta ronda: interfaz "Local AI Studio" — Dashboard interactivo + Playground

Cambio de enfoque respecto a las rondas anteriores: en vez de más
backend, esta ronda le pone cara a lo que ya funcionaba. El **repositorio**
sigue llamándose `local-ai-stack-template` (sigue siendo la plantilla
técnica reutilizable); el título dentro de la interfaz pasa a ser
**"Local AI Studio"** — es solo el nombre que ve quien usa el panel, no
un cambio del repo en sí.

### Dashboard: de tarjetas estáticas a interactivas

- Cada servicio es ahora una tarjeta desplegable. Al abrirla, pide sus
  métricas reales de proceso (CPU, RAM, uptime) vía `psutil.Process(pid)`
  — pero solo si el propio panel arrancó ese proceso (guarda el PID en
  memoria al hacerlo). Si no, lo dice claramente en vez de inventar un
  dato.
- El contador **"Failed"** es clicable: abre la lista de tareas con ese
  estado, con el error exacto de cada una. Nuevos endpoints en el backend:
  `GET /tasks` (filtro por estado) y `GET /tasks/counts`. El panel lee
  Postgres directamente para esto (como ya hacía con Redis para las
  colas), sin pasar por la autenticación del backend — es tráfico
  interno del propio panel, no una API pública.

Probado con un fallo real (no simulado con datos falsos): encolé una
tarea con un payload que rompe a propósito
(`sources: "un string en vez de una lista"`), el contador de Failed subió
a 1, y al hacer clic apareció el error exacto
(`'str' object has no attribute 'get'`) en pantalla.

### Playground: probar cualquier proyecto sin escribir una interfaz nueva

Página nueva que llama de verdad al LLM Gateway: selector de
proveedor/modelo (poblado desde `GET /providers`), system prompt, prompt,
temperature, contexto, botón RUN. El Gateway se amplió para aceptar y
reenviar estos parámetros a Ollama (`options: {temperature, num_ctx}`) y
a proveedores OpenAI-compatible.

Probado de extremo a extremo con Playwright real (no solo con curl):
cargó los proveedores y modelos del gateway, se rellenó un prompt y un
system prompt, se pulsó RUN, y la respuesta llegó con tiempo transcurrido,
nº de tokens y tokens/segundo reales (calculados a partir de lo que
devuelve Ollama).

### Lo que queda para la siguiente tanda

Del boceto de "Local AI Studio": **Models**, **Knowledge** (con test de
retrieval visual sobre el RAG ya probado), **Tasks** (vista completa, no
solo el resumen del dashboard), **Plugins** (usando el autodiscovery ya
existente), **Integrations** (la tabla `n8n_integrations` ya tiene
backend, falta la pantalla), **Logs** (vista unificada, ya existe por
servicio), **Evaluation** (ya existe por terminal, falta la pantalla) y
**Settings**. Aparecen en la barra lateral marcadas como "Próximamente"
en vez de ocultarlas o fingir que ya existen.

## Sexta ronda: las 7 secciones restantes de "Local AI Studio"

Completa el boceto de interfaz: todas las secciones de la barra lateral
ya funcionan (salvo Models, que sigue sin backend real detrás porque no
hay más "modelo" que gestionar que lo que ya expone el LLM Gateway).

- **Knowledge** — indexar texto y probar retrieval visualmente contra el
  RAG real. Probado: indexé un documento desde el formulario, lo
  encontré con una búsqueda, con su cita exacta y su score.
- **Plugins** — lista automática vía `workers/plugin_loader.discover_plugins()`,
  con un indicador de si hay un worker de verdad escuchando esa cola
  ahora mismo (consultando `Worker.all()` de RQ). Probado: los 3 plugins
  reales aparecen solos.
- **Integrations** — pantalla sobre la tabla `n8n_integrations` ya
  existente. Probado: desactivar un flujo cambia el botón a "Activar" al
  momento.
- **Tasks** — vista completa con filtro por estado y traza de auditoría
  desplegable por tarea. Probado con una tarea y su paso de auditoría
  reales.
- **Logs** — todos los servicios en una sola pantalla, cada línea
  etiquetada con su servicio y coloreada. Probado con una línea real
  añadida a un fichero de log mientras la página estaba abierta.
- **Evaluation** — envoltorio visual sobre `scripts/run_evaluation.py`
  (lo ejecuta de verdad, no simula el resultado). Probado: 3/3 casos
  reales contra el RAG, desde el botón de la interfaz.
- **Settings** — editor de `config/services.yaml` con validación (YAML
  inválido, o válido pero sin la forma esperada, ambos rechazados con
  mensaje claro antes de escribir nada). Las variables de entorno se
  muestran solo desde `.env.example` — el panel **nunca** lee ni enseña
  el `.env` real, para no arriesgarse a mostrar un secreto en pantalla.

Con esto, las 8 secciones del boceto original de "Local AI Studio" están
todas construidas salvo "Models" (que no tiene más contenido real que
mostrar del que ya da `/providers` del Gateway, visible desde Playground).

## Séptima ronda: onboarding, diagnóstico y comparación A/B

### Asistente de primera puesta en marcha

`/` redirige a `/onboarding` hasta que se completa una vez (estado en
`data/setup_state.json`, ignorado por git — es local de cada máquina).
Comprueba Python, Docker, Postgres, Redis y Ollama de verdad
(`common/system_checks.py`), y solo bloquea el avance si falla algo
realmente imprescindible (Python, Postgres, Redis) — Docker y Ollama son
opcionales, porque el modo nativo no necesita Docker y un proyecto que
solo use APIs externas no necesita Ollama. Si Ollama está pero sin
modelos, ofrece un botón para lanzar `ollama pull` en segundo plano.

El segundo paso pregunta el modo de uso (local only / local + APIs
externas / desarrollo) y lo guarda — de momento es solo una preferencia
registrada, no cambia comportamiento del sistema todavía.

**Probado en real, incluido un bug de diseño que se corrigió sobre la
marcha**: la primera versión exigía que TODOS los checks pasaran para
continuar, lo que habría bloqueado a cualquiera sin Docker instalado
aunque estuviera en modo nativo (el caso más común). Se corrigió para
que solo lo imprescindible bloquee. Probado el flujo completo: redirect
a onboarding en la primera visita, checks reales, avance con Docker en
amarillo, completar el asistente, redirect a Dashboard, y que una
segunda visita a `/` ya no vuelve a pedir onboarding.

### Centro de diagnóstico

Ya no es "el puerto responde o no" — `common/diagnostics.py` cruza
señales para detectar problemas concretos. El caso estrella: una cola
con tareas esperando pero sin ningún worker escuchándola (comprobado vía
`Worker.all()` de RQ), algo invisible mirando servicios uno a uno porque
Redis, Postgres y el backend pueden estar perfectamente sanos mientras
nada se procesa. Cada problema trae un botón de acción cuando existe uno
razonable (`Start worker`), no solo el diagnóstico.

Probado en real: con backend y gateway arrancados pero sin ningún
worker, el estado general bajó a `degraded` con las 3 colas señaladas;
pulsar "Start worker" sobre `process` lo puso en `up` de verdad
(confirmado consultando `/api/diagnostics` otra vez).

### Playground: Compare (A/B)

Pestaña nueva junto a la de siempre: dos selectores de proveedor/modelo,
un prompt compartido, y "RUN BOTH" — lanza la misma petición contra
ambas combinaciones (secuencial a propósito, no en paralelo, para no
medir "cómo compiten entre sí" sino el rendimiento real de cada una) y
compara latencia, tokens y tokens/segundo lado a lado.

No incluye una columna de "calidad/evaluation" como en el boceto
original: eso necesita un caso con respuesta esperada de verdad, que es
justo lo que ya cubre la pantalla **Evaluation** con casos reales — un
número de "calidad" inventado sin referencia habría sido decorativo, no
información real.

Probado en real: dos modelos distintos (`llama3.1` y `llama3.1:8b`)
contra el mismo prompt, con latencia/tokens/salida de cada uno
mostrados correctamente por separado.

### Pendiente de esta ronda

**Knowledge como gestor de colecciones** (subida de PDF/DOCX/CSV, vista
por documento con "ver chunks"/"reindexar"/"borrar") queda fuera a
propósito: implica añadir el concepto de "colección" al esquema (hoy el
RAG es plano, por `doc_id`) y nuevas dependencias de parseo de ficheros
— cambios de fondo, no una extensión directa de lo que ya había.

## Octava ronda: Knowledge como gestor de colecciones real

Cierra la carencia que quedaba marcada como "sin construir". Ya no es
pegar texto y probar retrieval — es un gestor real:

- **Colecciones**: tabla `collections`, creables desde la interfaz
  (`POST /api/knowledge/collections`). La colección `default` se crea
  siempre al arrancar el panel, para no bloquear a quien sube algo sin
  haber creado una colección antes.
- **Subida real de ficheros**: `POST /api/knowledge/upload` (multipart)
  acepta PDF, DOCX, TXT y MD. `rag/file_parsers.py` extrae el texto de
  cada formato (`pypdf` para PDF, `python-docx` para DOCX) — añadir un
  formato nuevo es añadir una función ahí, nada más.
- **Metadatos por documento**: tabla `documents` — colección, nombre de
  fichero, tipo, versión, modelo de embeddings usado, y el **texto
  extraído completo** guardado (no solo los chunks), para poder
  reindexar sin volver a pedir el fichero.
- **Reindexar**: `POST /api/knowledge/documents/<id>/reindex` — borra
  los chunks existentes y vuelve a trocear/calcular embeddings desde el
  texto ya guardado.
- **Borrar**: `DELETE /api/knowledge/documents/<id>` — quita chunks
  (de ambos backends, JSON y pgvector si existiera) y la metadata.
- **Ver chunks**: página de detalle por documento
  (`/knowledge/<doc_id>`) con los chunks reales y un test de retrieval
  acotado solo a ese documento (`?doc_id=` en `/api/knowledge/search`).

### Dos bugs reales encontrados subiendo ficheros de verdad

1. La colección `default` solo se creaba al visitar la página
   `/knowledge` — llamar directamente a la API de subida (como hace
   cualquier integración externa, no solo el navegador) fallaba con
   `ForeignKeyViolation` porque la colección no existía todavía.
   Corregido: se crea al arrancar el proceso del panel, no al visitar
   una página concreta.
2. El borrado de chunks en `rag_chunks_pgvector` asumía que esa tabla
   siempre existe — pero desde la ronda anterior pgvector es opcional,
   así que la tabla puede no estar. Corregido comprobando su existencia
   (`to_regclass`) antes de intentar borrar ahí.

**Probado end-to-end con ficheros reales, no de mentira**: generé un
PDF real (con `reportlab`), un DOCX real (con `python-docx`), un TXT y
un MD, subí los cuatro, y el retrieval global los recuperó a todos
correctamente ordenados por relevancia — incluida la extracción de
texto del PDF, que salió limpia. Probado también: página de detalle,
ver chunks, reindexar sin re-subir, borrar (confirmando que desaparece
de la búsqueda), y que dos colecciones distintas mantienen sus
documentos separados.

## Validación de instalación limpia (punto 2 del plan)

Prueba real, no simulada: se borró toda la base de datos, todo el
estado de Redis, el `.env`, y todos los ficheros de log, para simular
una máquina que nunca ha visto este proyecto. Se siguió el flujo exacto
que seguiría alguien nuevo:

**install → start → cargar documento → preguntar → obtener respuesta+cita**

Resultado: **funciona de punta a punta**. Cada paso, confirmado:

1. `pip install -r requirements.txt` — instala todo lo necesario.
2. `createdb` + `init_schema()` — crea las tablas núcleo sin pedir nada más.
3. Arrancar backend, gateway, un worker y el panel — todos responden sanos.
4. Onboarding — detecta correctamente Python/Postgres/Redis como
   imprescindibles y Docker/Ollama como opcionales; se completa sin fricción.
5. Subir un documento real (`.md`) desde Knowledge — indexado correcto.
6. Preguntar sobre su contenido vía `/enqueue/process` — la respuesta
   viene con **cita textual exacta** del documento subido, con su
   `chunk_id` y el fragmento literal.

### Fricción real encontrada (no bloqueante, mejorable)

En sistemas con Python gestionado por el sistema operativo (Debian y
derivados, y probablemente relacionado con lo visto en macOS con
Homebrew), `pip install --upgrade` sobre paquetes que el propio sistema
ya trae instalados (como `PyJWT`) puede fallar con un error de
desinstalación. No bloquea nada — la versión ya instalada funciona
igual — pero es un punto de fricción real en la primera instalación que
vale la pena documentar: si `pip install -r requirements.txt` da un
error de "Cannot uninstall X", normalmente se puede ignorar y seguir
adelante, comprobando después que el módulo se importa
(`python3 -c "import jwt"`, etc.).

## Novena ronda: Backup / Restore desde Settings (punto 3 del plan)

Nueva sección en Settings, respaldada por `pg_dump`/`psql` directamente
— no un formato propio inventado. El `.env` real nunca se incluye
(puede tener secretos).

- **Export** (`GET /api/settings/backup/export`): genera un `.zip` con
  `manifest.json` (fecha + recuento de filas por tabla), `services.yaml`,
  y `db_dump.sql` (con `--clean --if-exists`, para que restaurarlo
  sobrescriba limpiamente en vez de duplicar filas).
- **Import/Restore** (`POST /api/settings/backup/import`): sube el
  `.zip`, valida que contenga `db_dump.sql`, y lo aplica con `psql`
  sobre la base de datos actual. Opcionalmente restaura también
  `services.yaml` (validado como YAML antes de escribir, igual que el
  editor de Settings). **Restaurar sobrescribe la base de datos
  actual — es lo que significa restaurar un backup**, y la interfaz
  pide confirmación explícita antes de hacerlo.

### Bug real encontrado en la propia prueba de la funcionalidad

Al probar qué pasaba si alguien sube un fichero que no es un `.zip` de
verdad, `zipfile.BadZipFile` no estaba capturado — daba un 500 genérico
en vez de un error entendible. Corregido: ahora da 400 con
`"el fichero subido no es un .zip válido"`.

**Probado de la forma más convincente para esta función en concreto —
una prueba destructiva real**: se creó una colección y un documento de
verdad, se exportó el backup, se **borró el documento** (confirmando
404), y se **restauró el backup** — el documento volvió, visible en su
página y de nuevo encontrable por búsqueda. Es exactamente el escenario
que motiva tener esto: algo se borra o se rompe, y hay vuelta atrás.
También probados los dos casos de error (fichero corrupto, zip válido
pero sin `db_dump.sql`) y que restaurar un backup sin pedir tocar
`services.yaml` lo deja intacto.

## Décima ronda: multi-proyecto — la capa que faltaba para ser una plataforma genérica

Antes de esta ronda, "Local AI Studio" era, en la práctica, el panel de
un único proyecto. Esta ronda añade `projects` como entidad de primer
nivel: cada proyecto tiene sus propias colecciones, documentos, tareas,
integraciones de n8n y configuración (modelo, system prompt,
temperature, top-k, chunking), sin mezclarse con los demás.

### Esquema

- `projects` (id, name, description, project_type) y `project_settings`
  (1 fila por proyecto: modelo principal/fallback, embeddings, system
  prompt, temperature, top_k, chunk_size/overlap).
- `collections` y `n8n_integrations` pasan a tener **clave primaria
  compuesta** `(project_id, id)` / `(project_id, flow_name)` — así dos
  proyectos pueden tener cada uno su colección "default" sin chocar.
- `tasks` y `documents` llevan `project_id` directo.
- `rag_chunks` y `audit_log` NO llevan `project_id` propio a propósito:
  lo heredan vía `doc_id -> documents.project_id` y `task_id ->
  tasks.project_id` respectivamente — evita duplicar la columna en las
  dos tablas que más crecen.
- El proyecto `default` se crea siempre, y toda instalación previa a
  esta ronda queda asignada a él automáticamente al migrar.

### Bugs de migración reales, encontrados migrando una base con datos de verdad

Se probó la migración contra una base con datos reales de rondas
anteriores (3 colecciones, 1 tarea), no contra una base vacía — y
aparecieron dos problemas que una base vacía nunca hubiera revelado:

1. Cambiar la PK de `collections` de `(id)` a `(project_id, id)` falló
   la primera vez: una restricción de clave foránea huérfana en
   `documents.collection_id` (de una ronda anterior) dependía del índice
   de la PK antigua. Solución: `DROP CONSTRAINT IF EXISTS` de esa FK
   antes de tocar la PK.
2. Tras eso, la migración sí completó — y se confirmó que las 3
   colecciones y la tarea existentes quedaron asignadas al proyecto
   `default` sin perder ni un dato.

### La prueba que de verdad importa: aislamiento real entre proyectos

Probado en dos capas:

- **A nivel de base de datos**: dos proyectos con documentos de
  contenido claramente distinto (baloncesto / ajedrez) — una búsqueda en
  el proyecto A nunca devuelve nada del proyecto B, y viceversa.
- **A través de la interfaz web real** (no solo funciones Python):
  se crearon dos proyectos desde el wizard, se subió un documento
  distinto a cada uno, y se confirmó que la pantalla Knowledge y el
  buscador de retrieval, tras cambiar de proyecto con el selector del
  sidebar, **solo** muestran/encuentran los documentos de ese proyecto.

### New Project Wizard

`/projects` — formulario con nombre, descripción y una de las 8
plantillas pedidas (Blank, RAG/Document Q&A, Research assistant,
Customer support, Clinical/health, Knowledge base, Document analysis,
Agent workflow). Cada plantilla solo predefine el `system_prompt` inicial
en `project_settings` — no fuerza nada, se puede cambiar después desde
el dashboard del proyecto.

### Project Dashboard

`/projects/<id>` — exactamente los 5 datos pedidos: documentos/chunks
indexados, tareas ejecutadas (con desglose completadas/fallidas), modelo
activo, calidad de evaluación (placeholder hasta que se ejecute una
evaluación real — no se inventa un número), y errores recientes con el
mensaje de error real de cada tarea fallida. Debajo, edición de
`project_settings` con guardado probado.

### Export / Import de proyecto individual

Distinto del backup global (que exporta TODA la instalación vía
`pg_dump`): `common/project_export.py` exporta un `.ai-project.zip` con
un `manifest.json` — proyecto, settings, colecciones, documentos
(incluido el texto extraído completo) e integraciones — de UN proyecto
concreto. Al importar, los documentos se re-indexan (chunking +
embeddings) en el destino, no se copian los chunks tal cual, para no
depender de qué backend de embeddings tenga configurado el otro lado.

**Probado de extremo a extremo**: se exportó el proyecto "Baloncesto",
se importó con un id distinto ("baloncesto-copia"), y el documento
apareció en Knowledge del proyecto nuevo, correctamente indexado y
buscable con un score de relevancia real.

### Lo que queda fuera de esta ronda, explícitamente

- **Permisos por proyecto** — el JWT con roles sigue siendo global, no
  por proyecto. Añadirlo es una pieza de diseño nueva (roles ×
  proyectos), no una extensión directa.
- **Métricas de evaluación por proyecto** — el Project Dashboard tiene
  el hueco para ello, pero no se ha conectado con un histórico real de
  ejecuciones de `Evaluation` todavía.
- **Playground y Evaluation aún no leen `project_settings`** — el
  modelo/temperature/system prompt de un proyecto se guardan y se ven
  en su dashboard, pero el Playground sigue usando sus propios campos
  sueltos en vez de precargar los valores del proyecto activo. Es el
  siguiente punto de conexión obvio, no construido todavía.
