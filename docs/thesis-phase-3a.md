# Thesis — Fase 3A: versiones y fuentes

Esta fase añade persistencia project-scoped para preparar generación y verificación
sin ejecutarlas todavía.

## Tablas

- `thesis_section_sources`: fragmentos aprobados como fuentes de un capítulo.
- `thesis_section_versions`: versiones Markdown numeradas por capítulo.
- `thesis_claims`: afirmaciones asociadas a una versión.
- `thesis_claim_sources`: trazabilidad de cada afirmación a fragmentos y documentos,
  incluyendo cita, localizador y resultado futuro de verificación.

## API

- `POST/GET /api/projects/<project_id>/thesis/chapters/<chapter_id>/sources`
- `POST/GET /api/projects/<project_id>/thesis/chapters/<chapter_id>/versions`
- `POST/GET /api/projects/<project_id>/thesis/versions/<version_id>/claims`
- `POST /api/projects/<project_id>/thesis/claims/<claim_id>/sources`

Las lecturas requieren rol `viewer` y las escrituras `editor`. Todas las relaciones
validan el proyecto antes de insertar o devolver datos.

La generación mediante el gateway y la verificación mediante `common.verification`
quedan para la Fase 3B.
