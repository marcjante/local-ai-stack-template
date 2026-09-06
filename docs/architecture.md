# Arquitectura del stack

Esta plantilla asume un patrón habitual en proyectos de IA local con varios
servicios corriendo en paralelo en la misma máquina, cada uno en su puerto,
más un panel de control que los supervisa a todos.

## Servicios tipo

| Servicio            | Puerto | Rol                                              |
|---------------------|--------|---------------------------------------------------|
| LLM local (Ollama)  | 11434  | Sirve los modelos de lenguaje                     |
| Base vectorial       | 8000   | Embeddings / búsqueda semántica (RAG)             |
| Backend API          | 8080   | Lógica de negocio, conecta LLM + base vectorial   |
| Automatización (n8n) | 5678   | Backups, tareas programadas, integraciones        |
| Panel de control     | 8090   | Ve el estado de todo y permite arrancar/parar     |

## Cómo se conectan

```
                     ┌─────────────────────┐
                     │   Panel de control   │  :8090
                     │ (dashboard_service)  │
                     └──────────┬───────────┘
                                │ supervisa (health-check por puerto)
        ┌───────────────┬──────┴───────┬────────────────┐
        │               │              │                │
  ┌─────▼─────┐   ┌─────▼─────┐  ┌─────▼──────┐   ┌──────▼──────┐
  │ LLM local │   │  Backend  │  │ Automatiz. │   │ Base vectorial│
  │  :11434   │◄──┤   API     │  │   (n8n)    │   │    :8000      │
  └───────────┘   │  :8080    │  │   :5678    │   └──────▲────────┘
                   └─────┬─────┘  └────────────┘          │
                         └───────────────────────────────┘
                          el backend consulta la base vectorial
                          y el LLM para responder
```

- El **backend** es el único punto que habla con el LLM y con la base
  vectorial; nada más debería llamarlos directamente.
- El **panel de control** solo hace *health-checks* (comprobar si el puerto
  responde) y lanza los `start_command` / `stop_command` definidos en
  `config/services.yaml` — no conoce la lógica interna de cada servicio.
- La **automatización** (n8n u otro orquestador) vive aparte y se engancha
  al backend o a los datos según las tareas programadas del proyecto.

## Cómo adaptar esto a un proyecto nuevo

1. Edita `config/services.yaml`: cambia nombres, puertos y comandos reales.
2. Pon el código real de cada servicio donde corresponda (`backend/`,
   `dashboard/`, etc. — crea las carpetas que falten).
3. No toques `dashboard_service.py` ni los scripts de `scripts/` salvo que
   cambie la lógica de arranque/parada en sí — leen todo de `services.yaml`.
4. Añade un `.env` (a partir de `.env.example`) con las variables propias
   del proyecto (rutas de datos, claves de API externas, etc.).
