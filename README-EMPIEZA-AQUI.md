# Codex bridge para Local AI Studio

Objetivo: dejar de copiar/pegar comandos entre ChatGPT y Terminal. Una vez instalado, abre el proyecto y ejecuta:

    ./ai

A partir de ahí habla con Codex en lenguaje normal. Codex puede leer/editar archivos y ejecutar tests dentro del repositorio.

## Instalación rápida

1. Descomprime esta carpeta.
2. Copia su contenido dentro de la raíz de `local-ai-stack-template`.
3. Desde la raíz del proyecto ejecuta UNA sola vez:

    bash setup-codex.sh

4. Si Codex no está instalado, el instalador te indicará cómo instalarlo.
5. Ejecuta:

    ./ai

La primera vez, si Codex lo solicita, inicia sesión con tu cuenta de ChatGPT.

## Qué instala

- `AGENTS.md`: reglas permanentes para Codex.
- `.codex/TASKS.md`: cola de trabajo.
- `.codex/SESSION_PROMPT.md`: instrucciones de cada sesión.
- `ai`: arranque normal.
- `ai-safe`: revisión/diagnóstico sin pedir cambios grandes.
- `ai-status`: estado rápido del repositorio.
- `.codex/logs/`: informes de sesión.

## Uso habitual

    cd ~/Desktop/local-ai-stack-template
    ./ai

Y luego puedes escribir cosas como:

    Revisa por qué falla la revisión sistemática. Corrígelo, ejecuta los tests
    relacionados y enséñame el diff final.

o:

    Continúa con la primera tarea pendiente de .codex/TASKS.md.

## Seguridad

El paquete está pensado para que Codex:
- trabaje dentro del repositorio;
- no haga push a `main`;
- no borre `.env`, bases de datos ni secretos;
- ejecute tests antes de considerar terminado un cambio;
- enseñe un resumen/diff al finalizar.

No convierte este chat de ChatGPT en acceso remoto a tu Mac. Lo que elimina es el ciclo
manual de “pásame sed/cat → cópialo → pega la salida”: al trabajar en Codex CLI, el propio
Codex lee y modifica directamente el proyecto.
