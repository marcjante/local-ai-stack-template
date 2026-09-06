# Arquitectura del stack

Esta plantilla asume un patrón habitual en proyectos de IA local con varios
servicios corriendo en paralelo en la misma máquina, cada uno en su puerto,
más un panel de control que los supervisa a todos.

## Servicios tipo

| Servicio              | Puerto | Rol                                                        |
|-----------------------|--------|-------------------------------------------------------------|
| LLM local (Ollama)    | 11434  | Sirve los modelos de lenguaje                               |
| Base vectorial        | 8000   | Embeddings / búsqueda semántica (RAG)                       |
| Cola de tareas (Redis)| 6379   | Reparte tareas entre agentes, sin que se pisen entre sí     |
| Base de datos (Postgres)| 5432 | Persiste estado y resultados                                |
| Backend API           | 8080   | Orquesta LLM + base vectorial y encola tareas para agentes  |
| Automatización (n8n)  | 5678   | Backups, tareas programadas, integraciones                  |
| Agente 1 / 2 / 3      | 9101-9103 | Workers idénticos que procesan tareas de la cola en paralelo |
| Panel de control      | 8090   | Ve el estado de todo y permite arrancar/parar               |
| Reverse proxy (Nginx) | 80     | Punto de entrada único hacia dashboard + backend            |

## Cómo se conectan

```
                    Internet / navegador
                            │
                     ┌──────▼──────┐
                     │    Nginx     │  :80
                     │ (reverse     │
                     │   proxy)     │
                     └──────┬──────┘
                ┌───────────┴────────────┐
                │                        │
        ┌───────▼────────┐      ┌────────▼────────┐
        │ Panel de control│      │   Backend API    │  :8080
        │    :8090        │◄─────┤ (orquesta todo)  │
        └───────┬─────────┘      └───┬────┬────┬────┘
                │ supervisa           │    │    │
                │ (health-check)      │    │    │
   ┌────────────┼──────────┬──────────┘    │    └───────────┐
   │            │          │               │                │
┌──▼───┐  ┌─────▼────┐ ┌───▼────┐   ┌──────▼──────┐  ┌──────▼──────┐
│ LLM  │  │  Base    │ │Automat.│   │ Cola (Redis) │  │  Postgres    │
│:11434│  │ vectorial│ │ (n8n)  │   │    :6379     │  │    :5432     │
└──────┘  │  :8000   │ │ :5678  │   └──────┬───────┘  └──────▲──────┘
          └──────────┘ └────────┘          │                 │
                          reparte tareas ───┼─────────────────┘
                          (BLPOP, atómico)  │  agentes guardan resultados
                    ┌─────────────┬─────────┴───┬──────────────┐
              ┌─────▼────┐  ┌─────▼────┐  ┌──────▼───┐
              │ Agente 1 │  │ Agente 2 │  │ Agente 3 │  :9101-9103
              │(worker)  │  │(worker)  │  │(worker)  │
              └──────────┘  └──────────┘  └──────────┘
```

- El **backend** es el único punto que habla con el LLM y con la base
  vectorial directamente, y también el que encola tareas en Redis.
- Los **agentes** (agent-1/2/3) son procesos idénticos: cada uno hace
  `BLPOP` sobre la misma cola. Redis garantiza que cada tarea la coge un
  único agente, así que 3 agentes procesan 3 tareas en paralelo sin
  configuración extra ni reparto manual. Para tener más agentes, duplica
  el bloque `agent_N` en `services.yaml` y arráncalo con otro `--id`/`--port`.
- El **panel de control** solo hace *health-checks* (comprobar si el puerto
  responde) y lanza los `start_command` / `stop_command` definidos en
  `config/services.yaml` — no conoce la lógica interna de cada servicio.
- **Nginx** es opcional en desarrollo (puedes seguir usando los puertos
  sueltos), pero es el que usarías si despliegas esto en un servidor real:
  un único puerto público (80/443) hacia fuera.
- La **automatización** (n8n u otro orquestador) vive aparte y se engancha
  al backend o a los datos según las tareas programadas del proyecto.

## Probar que los agentes trabajan en paralelo

Con Redis y los 3 agentes arrancados:

```bash
python agents/enqueue_demo_tasks.py
```

Esto mete 6 tareas de 2 segundos cada una. Con 3 agentes libres deberían
tardar ~4 segundos en total (2 tandas), no 12 — eso confirma que se están
repartiendo el trabajo en vez de procesarlo uno a uno.

## Cómo adaptar esto a un proyecto nuevo

1. Edita `config/services.yaml`: cambia nombres, puertos y comandos reales.
2. Pon el código real de cada servicio donde corresponda (`backend/`,
   `dashboard/`, etc. — crea las carpetas que falten).
3. No toques `dashboard_service.py` ni los scripts de `scripts/` salvo que
   cambie la lógica de arranque/parada en sí — leen todo de `services.yaml`.
4. Añade un `.env` (a partir de `.env.example`) con las variables propias
   del proyecto (rutas de datos, claves de API externas, etc.).
