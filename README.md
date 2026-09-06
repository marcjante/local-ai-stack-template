# local-ai-stack-template

Plantilla reutilizable para proyectos de IA local con varios servicios
corriendo a la vez (LLM local, base de datos vectorial, backend, automatización)
más un panel de control web que los supervisa.

No contiene lógica ni datos de ningún proyecto concreto — solo la
infraestructura (qué servicios hay, en qué puerto, cómo arrancarlos/pararlos
y cómo se conectan entre ellos). Pensada para clonarla como punto de partida
de un proyecto nuevo.

## Estructura

```
local-ai-stack-template/
├── config/
│   └── services.yaml        # inventario de servicios: nombre, puerto, comandos
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
