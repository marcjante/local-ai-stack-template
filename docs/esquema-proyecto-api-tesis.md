# Esquema del proyecto — API Thesis para Local AI Studio

Documento maestro de implementación del dominio **Thesis** dentro de `local-ai-stack-template`.
La API recibe archivos heterogéneos, extrae su contenido, lo clasifica por fragmentos, propone el
apartado de tesis correspondiente y genera borradores trazables. No crea una aplicación separada ni
duplica el almacén documental/RAG existente.

## 1. Objetivo y límites

La API debe permitir:

1. Crear y configurar una tesis dentro de un `project_id`.
2. Subir varios archivos en una sola operación.
3. Leer PDF, DOCX, XLSX, CSV, TXT/Markdown, BibTeX y RIS.
4. Distinguir datos propios, bibliografía científica, documentación administrativa, borradores y normas de redacción.
5. Dividir cada archivo en unidades con procedencia: página, sección, hoja, tabla, fila o rango.
6. Proponer uno o varios destinos dentro de la tesis, con puntuación de confianza.
7. Exigir confirmación humana antes de incorporar el contenido.
8. Generar borradores utilizando únicamente datos y fuentes aprobados.
9. Verificar las afirmaciones bibliográficas y conservar su cita exacta.
10. Exportar versiones revisadas a DOCX y LaTeX; Overleaf será una integración posterior.

La API no debe:

- inventar datos, resultados, tamaños muestrales, referencias, DOI o PMID;
- convertir evidencia bibliográfica en resultados propios;
- modificar cifras durante la redacción;
- inferir causalidad cuando el diseño solo permite asociación;
- mezclar información entre proyectos;
- insertar automáticamente contenido de baja confianza;
- considerar una sección validada como equivalente a una versión final de la tesis.

## 2. Estructura doctoral que gestionará la API

La imagen aportada describe un artículo científico. Para la tesis se adapta al siguiente árbol configurable:

| Orden | Capítulo o bloque | Contenido esperado |
|---:|---|---|
| 1 | Portada | título, doctorando/a, dirección, programa, universidad y fecha |
| 2 | Resúmenes | resumen, resum y abstract estructurados |
| 3 | Palabras clave | términos normalizados y descriptores DeCS/MeSH cuando proceda |
| 4 | Índices | contenido, tablas, figuras y abreviaturas |
| 5 | Introducción y justificación | problema, alcance, pertinencia y pregunta de investigación |
| 6 | Marco teórico y antecedentes | conceptos, estado del conocimiento y lagunas |
| 7 | Hipótesis y objetivos | hipótesis, objetivo general y objetivos específicos |
| 8 | Metodología | diseño, ámbito, población, muestra, variables, instrumentos, procedimiento, análisis y ética |
| 9 | Resultados | hallazgos propios organizados por objetivo, sin interpretación |
| 10 | Discusión | interpretación y comparación de resultados propios con la literatura |
| 11 | Limitaciones | sesgos, incertidumbre, validez y restricciones |
| 12 | Implicaciones | práctica clínica, investigación, docencia o gestión |
| 13 | Conclusiones | respuesta concisa a objetivos e hipótesis |
| 14 | Bibliografía | referencias verificadas en el estilo configurado |
| 15 | Agradecimientos | contribuciones no incluidas en autoría |
| 16 | Anexos | CEIC, consentimientos, instrumentos, tablas extensas y documentación complementaria |

El árbol se almacena en base de datos y puede adaptarse a la normativa de cada universidad. Los capítulos
pueden editarse en paralelo; el bloqueo se aplica a la **aprobación/exportación**, no a la escritura.

## 3. Clasificación documental

### 3.1 Roles de fuente

Cada documento recibe un `source_role` independiente de su formato:

| `source_role` | Ejemplos | Uso permitido |
|---|---|---|
| `own_data` | XLSX/CSV con datos del estudio | resultados, tablas y figuras |
| `own_results` | salidas estadísticas, tablas consolidadas | resultados y base de la discusión |
| `study_protocol` | protocolo, proyecto CEIC | objetivos, metodología, ética y anexos |
| `scientific_evidence` | artículos y guías | introducción, marco teórico y discusión |
| `administrative` | dictamen CEIC, consentimiento | metodología ética o anexos |
| `draft` | capítulos previos y notas redactadas | destino sugerido, siempre con revisión |
| `writing_guideline` | normativa universitaria o guía de estilo | reglas de estructura y formato; no se cita como evidencia salvo fuente verificable |
| `bibliography` | BibTeX/RIS | catálogo bibliográfico |

### 3.2 Unidad de clasificación

No se clasifica únicamente el archivo completo. Se crean fragmentos con:

- texto extraído;
- `doc_id` y `project_id`;
- página y encabezado de sección para PDF/DOCX;
- hoja, tabla y rango para XLSX/CSV;
- `char_start` y `char_end` cuando existan;
- tipo de contenido detectado;
- capítulo y sección propuestos;
- confianza de clasificación;
- explicación breve;
- estado de revisión humana.

Un mismo archivo puede alimentar varios apartados. Los fragmentos no se copian a otro almacén: se
referencian desde las tablas Thesis hacia `documents` y `rag_chunks`.

### 3.3 Umbrales iniciales

| Confianza | Comportamiento |
|---:|---|
| `>= 0.85` | preselecciona el destino, pendiente de confirmación |
| `0.60–0.84` | muestra hasta tres destinos posibles |
| `< 0.60` | queda en bandeja `sin_clasificar` |

Ningún umbral autoriza la incorporación definitiva sin acción humana.

## 4. Flujo funcional

```text
Subida múltiple
  → validación de formato, tamaño, duplicado y project_id
  → alta/reutilización en documents
  → extracción según formato
  → chunking e indexación RAG una sola vez
  → clasificación del documento y de sus fragmentos
  → bandeja de revisión
  → confirmación/corrección humana
  → asignación a capítulos/secciones
  → generación de borrador
  → comprobación de cifras, afirmaciones y citas
  → revisión/aprobación
  → exportación DOCX/LaTeX
```

Estados del archivo:

```text
uploaded → extracting → indexed → classifying → review_required → approved
                                                     └──────────→ rejected
```

Estados de una sección:

```text
empty → materials_ready → draft → under_review → approved → exported
```

## 5. Modelo de datos

### 5.1 Tablas existentes que se reutilizan

| Tabla | Uso |
|---|---|
| `projects` | aislamiento del proyecto de tesis |
| `documents` | registro único del archivo original |
| `rag_chunks` / `rag_chunks_pgvector` | contenido indexado y procedencia |
| `collections` | agrupaciones documentales |
| `review_articles` | artículos de la revisión sistemática |
| `review_conflicts` / `data_extraction` | estado y datos de la revisión |
| `audit_log` | base para la auditoría general |

Se conserva la relación formal existente:

```text
review_articles.full_text_document_id → documents.doc_id ON DELETE SET NULL
```

### 5.2 Extensión de `documents`

Añadir solo si no existen:

- `source_role`
- `mime_type`
- `original_filename`
- `content_hash`
- `extraction_status`
- `mendeley_id`
- `citation_key`
- `doi`
- `pmid`
- `authors`
- `publication_year`
- `publication_type`

`content_hash` permite evitar duplicados dentro del proyecto. Un mismo documento puede estar relacionado
con la revisión sistemática y con Thesis sin volver a extraerse ni generar nuevos embeddings.

### 5.3 Tablas nuevas

#### `thesis_profiles`

- `id`, `project_id`
- título provisional
- autor/a, dirección, universidad y programa
- idioma principal
- estilo bibliográfico
- plantilla/normativa activa
- fechas de creación y actualización

#### `thesis_chapters`

- `id`, `project_id`, `parent_id`
- `code`, `title`, `chapter_type`, `order_index`
- `status`
- `approved_version_id`
- fechas de creación y actualización

Permite capítulos y subapartados. `chapter_type` usa valores semánticos como `methods`, `results` o
`discussion`, aunque el título visible sea configurable.

#### `thesis_file_ingestions`

- `id`, `project_id`, `doc_id`, `job_id`
- estado de extracción y clasificación
- parser y versión utilizados
- errores y advertencias
- fechas de inicio y finalización

#### `thesis_fragments`

- `id`, `project_id`, `doc_id`, `rag_chunk_id`
- tipo de contenido
- texto normalizado
- localizador de origen en JSON
- rol de fuente
- hash del fragmento

#### `thesis_placement_suggestions`

- `id`, `fragment_id`, `chapter_id`
- confianza, explicación y modelo
- versión del prompt
- estado: `pending`, `approved`, `corrected`, `rejected`
- destino corregido por el usuario
- revisor y fecha de decisión

#### `thesis_section_sources`

- `chapter_id`, `fragment_id`
- finalidad: `data`, `evidence`, `method`, `context`, `appendix`, `style_rule`
- aprobado por y fecha

Esta es la unión trazable entre el material original y el apartado de tesis.

#### `thesis_section_versions`

- `id`, `chapter_id`, `version_number`
- contenido en Markdown estructurado
- estado: `draft`, `under_review`, `approved`
- instrucciones utilizadas
- modelo/proveedor
- creado por y fechas

#### `thesis_claims`

- `id`, `section_version_id`
- texto de la afirmación
- tipo: `own_result`, `literature`, `interpretation`, `limitation`, `recommendation`
- estado de verificación

#### `thesis_claim_sources`

- `claim_id`, `fragment_id`, `document_id`
- cita literal de apoyo
- página/sección/offsets
- DOI/PMID cuando corresponda
- resultado de verificación y puntuación

#### `thesis_numeric_facts`

- `id`, `fragment_id`
- variable, grupo, estadístico, valor, unidad
- tamaño muestral, intervalo de confianza y p-valor cuando existan
- localizador de celda/tabla

Sirve para comprobar que el texto generado conserva exactamente las cifras originales.

#### `thesis_tasks`

- `id`, `project_id`, `description`, `due_at`, `completed`

## 6. Reglas de colocación

| Contenido detectado | Destino principal | Restricción |
|---|---|---|
| pregunta/problema de investigación | introducción/justificación | requiere confirmación |
| objetivos e hipótesis | hipótesis y objetivos | no reformular el sentido sin revisión |
| diseño, muestra, variables, instrumentos | metodología | separar planificado de realizado |
| dictamen CEIC/consentimiento | metodología ética/anexos | no exponer datos personales |
| cifras y tablas del estudio | resultados | sin citas bibliográficas ni interpretación |
| interpretación de hallazgos propios | discusión | enlazar con el resultado propio |
| comparación con artículos | discusión | exige fuente verificada |
| descripción del conocimiento previo | introducción/marco teórico | exige fuente verificable |
| sesgos y restricciones | limitaciones | diferenciar observados de potenciales |
| respuestas a objetivos | conclusiones | no introducir resultados nuevos |
| instrumento completo | anexos | citar su origen/licencia cuando proceda |
| guía de estructura aportada | normas de redacción | no incorporar como resultado o bibliografía sin procedencia |

## 7. Contrato de subida y clasificación

### 7.1 Subida múltiple

```http
POST /api/projects/{project_id}/thesis/files
Content-Type: multipart/form-data
```

Campos:

- `files[]`: uno o varios archivos;
- `declared_role` opcional;
- `collection_id` opcional;
- `language` opcional;
- `reprocess=false` por defecto.

Respuesta asíncrona:

```json
{
  "batch_id": "uuid",
  "accepted": [
    {"file_id": "uuid", "filename": "resultados_sus.xlsx", "status": "queued"}
  ],
  "rejected": []
}
```

### 7.2 Resultado de clasificación

```json
{
  "file_id": "uuid",
  "source_role": "own_results",
  "fragments": [
    {
      "fragment_id": "uuid",
      "source_locator": {"sheet": "SUS", "range": "A1:F35"},
      "content_type": "numeric_results",
      "suggestions": [
        {
          "chapter_code": "results.usability",
          "confidence": 0.96,
          "reason": "Contiene puntuaciones y estadísticos descriptivos del estudio"
        }
      ],
      "review_status": "pending"
    }
  ]
}
```

## 8. Endpoints

### Configuración y estructura

| Método | Ruta | Función |
|---|---|---|
| POST | `/api/projects/{id}/thesis` | crea el perfil y el árbol doctoral |
| GET | `/api/projects/{id}/thesis/structure` | devuelve capítulos, apartados y estados |
| PUT | `/api/projects/{id}/thesis/profile` | modifica universidad, idioma, estilo y plantilla |

### Archivos y clasificación

| Método | Ruta | Función |
|---|---|---|
| POST | `/api/projects/{id}/thesis/files` | subida múltiple y encolado |
| GET | `/api/projects/{id}/thesis/files` | bandeja y filtros por estado/rol |
| GET | `/api/projects/{id}/thesis/files/{file_id}` | extracción, fragmentos y procedencia |
| POST | `/api/projects/{id}/thesis/files/{file_id}/reclassify` | repite clasificación sin duplicar embeddings |
| GET | `/api/projects/{id}/thesis/placements` | propuestas pendientes |
| PUT | `/api/projects/{id}/thesis/placements/{suggestion_id}` | confirma, corrige o rechaza destino |
| POST | `/api/projects/{id}/thesis/placements/bulk-review` | revisión múltiple explícita |

### Redacción, verificación y aprobación

| Método | Ruta | Función |
|---|---|---|
| GET | `/api/projects/{id}/thesis/chapters/{chapter_id}` | sección, fuentes y versiones |
| POST | `/api/projects/{id}/thesis/chapters/{chapter_id}/generate` | genera borrador con fuentes aprobadas |
| PUT | `/api/projects/{id}/thesis/versions/{version_id}` | guarda edición humana |
| POST | `/api/projects/{id}/thesis/versions/{version_id}/verify` | verifica cifras, afirmaciones y citas |
| POST | `/api/projects/{id}/thesis/versions/{version_id}/approve` | aprueba si supera reglas configuradas |
| POST | `/api/projects/{id}/thesis/versions/{version_id}/suggest-citations` | propone citas sin guardar |

### Exportación

| Método | Ruta | Función |
|---|---|---|
| GET | `/api/projects/{id}/thesis/export/docx` | exporta versión revisada a DOCX |
| GET | `/api/projects/{id}/thesis/export/latex` | genera ZIP LaTeX + `.bib` |
| POST | `/api/projects/{id}/thesis/export/overleaf` | encola sincronización cuando esté configurada |

Todos los endpoints deben validar pertenencia al `project_id` y permisos mediante la autenticación existente.

## 9. Workers/plugins

| Cola/plugin | Disparador | Responsabilidad |
|---|---|---|
| `thesis_ingest` | subida | valida, deduplica y registra documentos |
| `thesis_extract` | tras ingestión | extrae texto, tablas y localizadores según formato |
| `thesis_classify` | tras indexación | clasifica rol, tipo y destinos por fragmento |
| `thesis_generate` | a demanda | redacta desde materiales aprobados |
| `thesis_verify` | tras generación/a demanda | comprueba cifras, afirmaciones y citas |
| `thesis_export` | a demanda/aprobación | genera DOCX o paquete LaTeX |
| `thesis_check_overlap` | antes de aprobar | alerta de similitud textual con fuentes |
| `mendeley_sync` | posterior, a demanda/periódico | sincroniza referencias y claves de cita |

Los plugins deben ser auto-descubribles y utilizar el LLM Gateway existente mediante `task_type`; no
deben llamar directamente a proveedores desde cada worker.

## 10. Generación por tipo de sección

### Resultados

- Usa exclusivamente fuentes `own_data` y `own_results` aprobadas.
- Conserva valores, denominadores, unidades, IC y p-valores.
- Separa resultados descriptivos, comparativos y modelos.
- No añade bibliografía ni interpreta mecanismos.
- Ejecuta verificación determinista de cifras tras generar.

### Introducción y marco teórico

- Usa evidencia científica aprobada.
- Cada afirmación verificable debe enlazarse con uno o más fragmentos recuperados.
- Marca `needs_evidence` si no existe respaldo suficiente.

### Metodología

- Prioriza protocolo, CRD, CEIC y documentación propia.
- Señala discrepancias entre protocolo y ejecución real; no decide cuál es correcta.
- No completa datos ausentes por plausibilidad.

### Discusión

- Parte de resultados propios aprobados.
- Separa: hallazgo propio, comparación bibliográfica, interpretación y limitación.
- No atribuye causalidad si el diseño no la permite.
- Las comparaciones requieren cita verificable.

### Conclusiones

- Responde a objetivos e hipótesis usando resultados aprobados.
- No introduce cifras, hallazgos o recomendaciones nuevos.

## 11. Verificación y control de calidad

Una versión no puede aprobarse si presenta errores críticos:

- cifra del texto distinta de la fuente;
- afirmación bibliográfica sin fragmento de apoyo;
- referencia sin identidad verificable cuando se exige DOI/PMID;
- resultados externos presentados como propios;
- contenido procedente de otro `project_id`;
- sección de resultados con interpretación causal;
- datos personales o sensibles no autorizados.

Salida de ejemplo:

```json
{
  "status": "needs_revision",
  "checks": {
    "numeric_consistency": "passed",
    "citation_support": "failed",
    "project_isolation": "passed"
  },
  "issues": [
    {
      "claim": "La intervención mejora la cicatrización",
      "reason": "La fuente recuperada muestra asociación, no causalidad",
      "suggested_action": "Reformular o aportar evidencia causal"
    }
  ]
}
```

## 12. Interfaz en Local AI Studio

Nueva entrada **Thesis** con cinco vistas:

1. **Estructura:** árbol de capítulos y estado.
2. **Archivos:** subida múltiple, progreso y errores.
3. **Clasificar:** fragmento, origen, destinos propuestos y botones confirmar/corregir/rechazar.
4. **Redactar:** editor, materiales aprobados, citas y versiones.
5. **Calidad y exportación:** verificaciones, advertencias, DOCX/LaTeX/Overleaf.

El estado de los workers también aparece en Tasks; los documentos continúan visibles en Knowledge y las
verificaciones agregadas pueden exponerse en Evaluation.

## 13. Orden de implementación

### Fase 1 — MVP documental

- [ ] Migración de `thesis_profiles`, `thesis_chapters`, `thesis_file_ingestions`, `thesis_fragments` y `thesis_placement_suggestions`.
- [ ] Crear árbol doctoral inicial.
- [ ] Subida múltiple PDF/DOCX/XLSX/CSV.
- [ ] Deduplicación por `project_id + content_hash`.
- [ ] Extracción con localizadores de origen.
- [ ] Clasificación por fragmentos.
- [ ] Bandeja de confirmación/corrección.
- [ ] Tests de aislamiento, duplicados y asignación.

### Fase 2 — Redacción mínima

- [ ] `thesis_section_sources`, `thesis_section_versions` y editor.
- [ ] Generación de Metodología desde archivos propios aprobados.
- [ ] Generación de Resultados desde tablas aprobadas.
- [ ] Comprobación determinista de cifras.
- [ ] Historial de versiones y auditoría.

### Fase 3 — Evidencia y discusión

- [ ] `thesis_claims` y `thesis_claim_sources`.
- [ ] Introducción/marco teórico con citas exactas.
- [ ] Discusión que relacione hallazgos propios y bibliografía.
- [ ] Estado `needs_evidence` y revisión humana.

### Fase 4 — Exportación

- [ ] Exportación DOCX con estilos configurables.
- [ ] ZIP LaTeX con `.bib`.
- [ ] Integración Git con Overleaf si la cuenta lo permite.

### Fase 5 — Calidad avanzada

- [ ] Detección de solapamiento textual.
- [ ] Reglas específicas por diseño de estudio.
- [ ] Informe completo de trazabilidad y reproducibilidad.

### Fase 6 — Bibliografía externa

- [ ] Sincronización con Mendeley.
- [ ] Generación estable de `citation_key`.
- [ ] Deduplicación DOI/PMID/título.

No se implementan Mendeley, Overleaf ni similitud avanzada hasta validar el flujo completo:
**subir → extraer → clasificar → confirmar → redactar → verificar**.

## 14. Criterios de aceptación del primer MVP

El MVP se considera terminado cuando:

1. Se pueden subir simultáneamente al menos un PDF, un DOCX y un XLSX/CSV.
2. Cada archivo queda asociado al proyecto correcto y no se indexa dos veces.
3. Un documento mixto produce fragmentos destinados a secciones diferentes.
4. Un Excel conserva hoja, tabla/rango y valores numéricos.
5. El usuario puede confirmar, corregir o rechazar cada propuesta.
6. Solo los fragmentos aprobados pueden alimentar la generación.
7. El sistema no usa literatura como resultado propio.
8. Cada texto generado permite volver al archivo y localizador de origen.
9. Los tests impiden recuperar documentos de otro proyecto.
10. Los errores de extracción o clasificación son visibles y reintentables.

## 15. Dependencias y configuración

Dependencias orientativas, sujetas a las ya instaladas:

- PDF: `pypdf`/`pdfplumber` y OCR opcional posterior.
- DOCX: `python-docx`.
- XLSX/CSV: `openpyxl` y `pandas`.
- BibTeX/RIS: parser específico reutilizable por bibliografía.
- PostgreSQL + Alembic.
- Redis/RQ.
- RAG y LLM Gateway existentes.

Variables nuevas mínimas:

```dotenv
THESIS_MAX_FILE_MB=50
THESIS_CLASSIFY_HIGH_CONFIDENCE=0.85
THESIS_CLASSIFY_LOW_CONFIDENCE=0.60
THESIS_REQUIRE_HUMAN_APPROVAL=true
```

Las credenciales de proveedores siguen centralizadas en el LLM Gateway. Las de Mendeley y la integración
con Overleaf se añadirán únicamente en sus fases correspondientes.

## 16. Primer corte de código

El primer cambio sobre el repositorio debe limitarse a:

1. una migración Alembic con las cinco tablas del MVP;
2. un servicio `thesis_service` para estructura, archivos, fragmentos y propuestas;
3. tres workers: `thesis_ingest`, `thesis_extract` y `thesis_classify`;
4. endpoints de subida, consulta y revisión de propuestas;
5. una plantilla de bandeja de clasificación;
6. tests de aislamiento por proyecto, deduplicación y aprobación humana.

En este primer corte todavía no se genera texto de tesis. Primero se garantiza que los materiales se leen,
se clasifican y quedan correctamente vinculados. La redacción se añade en la fase siguiente sobre una base
documental ya validada.
