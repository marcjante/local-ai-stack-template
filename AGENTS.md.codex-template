# AGENTS.md — Local AI Studio

## Objetivo
Mantener, depurar y evolucionar este repositorio sin degradar funcionalidades existentes.

## Forma de trabajo obligatoria
1. Antes de editar, inspecciona el área afectada y sus tests.
2. Comprueba `git status` antes de cambios.
3. Haz cambios pequeños, localizados y reversibles.
4. Ejecuta primero los tests más cercanos al cambio.
5. Si pasan, ejecuta las comprobaciones globales disponibles.
6. Revisa `git diff` antes de dar la tarea por terminada.
7. Resume exactamente qué archivos cambiaste, qué pruebas ejecutaste y qué queda pendiente.

## Prohibiciones
- No hacer `git push` automáticamente.
- No hacer commits directamente sobre `main`.
- No usar `git reset --hard`, `git clean -fd`, `rm -rf` u operaciones destructivas salvo petición explícita.
- No borrar ni modificar `.env`, secretos, tokens, claves o credenciales.
- No borrar bases de datos ni datos persistentes.
- No reescribir migraciones ya aplicadas.
- No introducir dependencias nuevas si puede resolverse con las existentes.
- No desactivar tests para hacerlos pasar.
- No ocultar errores con `try/except` genéricos sin tratamiento.
- No cambiar API pública ni comportamiento existente sin justificarlo.

## Git
Si la rama actual es `main`, no hagas cambios hasta crear o usar una rama de trabajo.
Nombre recomendado: `codex-work`.

## Python
Cuando existan en el proyecto, usa:
- pytest
- ruff
- mypy
- bandit
- pip-audit

No presupongas que todos están instalados. Detecta primero qué herramientas existen.

## Base de datos
- PostgreSQL/Alembic: inspecciona `alembic current` y el historial antes de crear migraciones.
- Nunca alteres una migración aplicada.
- Toda migración nueva debe tener `upgrade()` y `downgrade()` coherentes.

## Arquitectura del proyecto
Respeta el carácter genérico y multiproyecto de Local AI Studio.
Evita introducir lógica específica de TBC, heridas u otro proyecto concreto en la infraestructura base.
Mantén aislamiento entre proyectos, RAG, workers, dashboard y revisión sistemática.

## Revisión sistemática
Los cambios deben preservar:
- trazabilidad de decisiones;
- deduplicación;
- fases de screening;
- conflictos entre revisores;
- reproducibilidad de búsquedas;
- auditoría de cambios.

## Límites por tarea
Salvo que el usuario lo pida:
- una tarea funcional cada vez;
- evita refactorizaciones masivas;
- no cambies más archivos de los necesarios;
- si detectas otro problema, añádelo a `.codex/TASKS.md`.

## Criterio de finalización
Una tarea NO está terminada hasta que:
- el código compila/importa;
- pasan los tests relacionados;
- no hay errores evidentes de lint en los archivos modificados;
- se ha revisado el diff;
- se informa de cualquier test que no pudo ejecutarse.
