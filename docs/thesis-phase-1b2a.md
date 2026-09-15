# Thesis — Fase 1B2a

Esta fase añade el worker autodetectable `thesis_classify` y la migración
`c2d9e11a04f6`, descendiente de `b1b18d204a61`.

Cada `thesis_fragment` conserva ahora `content_type`, `classification_status`,
`classification_confidence`, `classification_reason`, `classifier_version` y
`classified_at`. La versión actual (`heuristic-1`) es determinista y no llama
a un proveedor externo: usa señales explícitas del texto y del nombre del
archivo. Un `source_role` declarado por el usuario prevalece con confianza 1.0;
los documentos `unknown` solo se promueven cuando la mayoría de fragmentos
coincide en una señal fuerte.

La extracción encadena el trabajo de clasificación en Redis/RQ. También puede
reintentarse con:

```http
POST /api/projects/<project_id>/thesis/files/<file_id>/classify
```

La operación es idempotente, mantiene el `project_id`, no crea chunks nuevos y
no propone capítulos por sí misma.

### Fase 1B2b

`thesis_placement_suggestions` conserva propuestas deterministas de destino con
confianza, razón, estado (`pending`, `approved`, `corrected`, `rejected`) y
revisor. Se generan después de clasificar y se pueden consultar o revisar con:

```http
GET /api/projects/<project_id>/thesis/placements?status=pending
PUT /api/projects/<project_id>/thesis/placements/<suggestion_id>
```

La corrección recibe `{"status":"corrected","corrected_chapter_id":"..."}`.
La revisión comprueba que el capítulo corregido pertenece al mismo proyecto.
No hay generación de texto ni verificación de afirmaciones en esta fase.
