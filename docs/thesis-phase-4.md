# Thesis — Fase 4: solapamiento interno

Se añadió `thesis_check_overlap` como aviso determinista contra los fragmentos RAG
del mismo proyecto. No elimina documentos ni bloquea automáticamente una versión.

- Tabla `thesis_overlap_checks` con puntuación máxima y coincidencias trazables.
- Worker `thesis_check_overlap` reutilizable desde RQ.
- API `POST/GET /api/projects/<project_id>/thesis/versions/<version_id>/overlap`.
- Acción equivalente en el Dashboard Thesis.

La comprobación compara texto de la versión con fragmentos propios y conserva
`fragment_id`, `doc_id`, cita y `source_locator`. El plagio externo y Copyleaks
quedan fuera de esta fase.
