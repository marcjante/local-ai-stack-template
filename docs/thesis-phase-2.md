# Thesis — Fase 2: interfaz Dashboard

La vista `/thesis` añade una interfaz mínima dentro del dashboard existente. Usa el
proyecto activo de la sesión y consume directamente `thesis_profiles`,
`thesis_chapters`, `thesis_file_ingestions`, `thesis_fragments` y
`thesis_placement_suggestions`; no crea un almacén paralelo.

## Incluye

- Perfil y estructura ordenada de capítulos, conservando `chapter_type`.
- Archivos Thesis con formato, rol, estado, reutilización y número de fragmentos.
- Fragmentos con texto procedente de los chunks RAG y su `source_locator`.
- Propuestas de destino con confianza, motivo y estado.
- Acción por archivo para ejecutar la clasificación automática existente y generar
  propuestas de capítulos de forma idempotente.
- Filtros por texto, rol, estado de extracción y estado de propuesta.
- Revisión humana desde el dashboard: aprobar, rechazar o corregir el capítulo.
- Todas las operaciones quedan limitadas al `project_id` activo y reutilizan los
  servicios de Thesis y la sesión del dashboard.

La revisión detallada y los endpoints API protegidos por JWT siguen disponibles en
`/api/projects/<project_id>/thesis/placements`.
