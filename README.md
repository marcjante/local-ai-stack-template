# local-ai-stack-template

Plantilla reutilizable para proyectos de IA local con varios servicios
corriendo a la vez (LLM local, base de datos vectorial, backend, cola de
tareas, base de datos, 3 agentes trabajando en paralelo, automatización y
un reverse proxy) más un panel de control web que los supervisa a todos.

No contiene lógica ni datos de ningún proyecto concreto — solo la
infraestructura (qué servicios hay, en qué puerto, cómo arrancarlos/pararlos
y cómo se conectan entre ellos). Pensada para clonarla como punto de partida
de un proyecto nuevo.

## Estructura

```
local-ai-stack-template/
├── config/
│   ├── services.yaml        # inventario de servicios: nombre, puerto, comandos
│   └── nginx.conf           # reverse proxy de ejemplo (puerto 80)
├── agents/
│   ├── agent_worker.py      # worker genérico (usado por agent-1/2/3 en paralelo)
│   └── enqueue_demo_tasks.py# mete tareas de prueba en la cola Redis
├── dashboard/
│   ├── dashboard_service.py # panel de control (Flask), puerto 8090
│   └── templates/index.html
├── scripts/
│   ├── start_stack.sh
│   └── stop_stack.sh
├── docs/
│   └── architecture.md      # diagrama y explicación de cómo se conecta todo
├── .env.example
└── requirements.txt
```

## Agentes en paralelo

`agents/agent_worker.py` es un worker genérico. En `services.yaml` hay tres
instancias (`agent_1`, `agent_2`, `agent_3`) que corren el mismo código con
`--id` distinto, escuchando la misma cola Redis — cada tarea la procesa un
único agente, así que se reparten el trabajo automáticamente. Para probarlo:

```bash
python agents/enqueue_demo_tasks.py
```

Ver `docs/architecture.md` para el detalle de cómo se coordinan.

## Uso

1. Clona este repo como base de un proyecto nuevo.
2. Edita `config/services.yaml` con los servicios reales del proyecto
   (nombres, puertos, comandos de arranque/parada).
3. Instala dependencias del panel de control:
   ```
   pip install -r requirements.txt
   ```
4. Arranca el panel de control:
   ```
   python3 dashboard/dashboard_service.py
   ```
   y abre `http://localhost:8090` para ver el estado de todos los servicios
   y arrancarlos/pararlos desde ahí.

Ver `docs/architecture.md` para el detalle de cómo se conectan los servicios
entre sí y cómo adaptar la plantilla a un proyecto concreto.
