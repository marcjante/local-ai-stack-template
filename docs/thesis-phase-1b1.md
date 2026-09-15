# Thesis — Fase 1B1

Esta fase añade ingestión y extracción multiarchivo reutilizando el almacén
documental y RAG existentes.

## Persistencia

La migración `b1b18d204a61` desciende de `f1a7c93d820b` y crea:

- `thesis_file_ingestions`: relación única por `project_id + doc_id`, estado,
  rol declarado, trabajo RQ, parser, errores y si la identidad binaria está
  verificada (`sha256_verified`) o procede de un documento histórico
  (`legacy_unverified`).
- `thesis_fragments`: referencias a `rag_chunks`/`rag_chunks_pgvector`, hash
  del fragmento, tipo, rol, offsets y localizador JSON. No duplica el texto del
  chunk; el detalle lo recupera del vector store existente.

`documents` reutiliza `filename` y `content_type`; añade únicamente
`content_hash`, `storage_key`, `source_role` y `extraction_status`. El hash es
nullable para documentos históricos. La unicidad garantizada es
`project_id + content_hash`.

## Almacenamiento y deduplicación

Los originales nuevos se guardan en `data/documents/` (ya excluido de Git) con
una clave relativa basada en un hash del proyecto y el SHA-256 del contenido.
El nombre físico no contiene el nombre enviado por el usuario. La escritura
usa archivo temporal, `fsync` y `os.replace`. El nombre original saneado queda
en `documents.filename`.

La subida calcula el hash leyendo bloques de 64 KiB, valida tamaño de 50 MiB,
extensión, MIME y firma básica. Una segunda subida del mismo contenido dentro
del proyecto reutiliza documento, chunks, embeddings e ingestión. Otro proyecto
recibe su propia fila y su propia clave de almacenamiento.

Los documentos históricos se incorporan exclusivamente con:

```http
POST /api/projects/<project_id>/thesis/files/link
```

```json
{"doc_id":"documento-existente","source_role":"scientific_evidence"}
```

Se comprueba proyecto, autorización y existencia. No se infiere un hash y se
reutilizan los chunks existentes; la operación es idempotente.

## Extracción y trazabilidad

- PDF: bloques por página y sección explícita, con `page_number` y offsets.
- DOCX: párrafo o fila de tabla, con índice y encabezado; no se inventan páginas.
- XLSX: fila y hoja, con rango y columnas de celdas.
- CSV: columnas, fila de datos y líneas del archivo.

El flujo usa `rag.file_parsers`, `rag.chunking`, `rag.embeddings` y
`rag.vector_store`. Los workers autodetectables son `thesis_ingest` y
`thesis_extract`; no clasifican ni generan texto.

## API

- `POST /api/projects/<id>/thesis/files` — multipart `files[]` y
  `declared_role`; devuelve `batch_id`, aceptados, reutilizados y rechazados.
- `GET /api/projects/<id>/thesis/files` — listado aislado por proyecto.
- `GET /api/projects/<id>/thesis/files/<file_id>` — detalle, estado, error,
  fragmentos y procedencia.
- `POST /api/projects/<id>/thesis/files/link` — vinculación histórica.

La subida exige rol `editor`; lectura exige `viewer`. Los errores se devuelven
como JSON. Un documento referenciado por Thesis no se puede eliminar. La
sustitución de texto completo de una revisión conserva ese documento y sus
chunks cuando existe una referencia Thesis, y registra `shared_document_retained`
en la auditoría de revisión.

## Verificación

La suite completa pasa con **137 tests**. Los tests específicos de esta fase
cubren los cuatro formatos, lote parcial, tamaño y firmas inválidas,
path traversal, SHA-256 y persistencia, deduplicación, aislamiento, vínculo
legacy, reintento, atomicidad de escritura, referencias cruzadas, upgrade y
downgrade. La advertencia restante procede de LibreSSL del entorno Python.

No se modificó `.env` ni se añadieron dependencias.

## Fase 1B2a

La clasificación inicial se implementa con `thesis_classify` y la versión
`heuristic-1`. Registra en cada fragmento `source_role`, `content_type`,
confianza, explicación, estado y versión del clasificador. Un rol declarado
por el usuario conserva confianza 1.0; un documento con rol `unknown` solo se
promueve cuando la mayoría de sus fragmentos presenta una señal consistente.
La clasificación es repetible e idempotente y no propone capítulos.

Se puede reejecutar mediante `POST /api/projects/<id>/thesis/files/<file_id>/classify`.

## Límite para Fase 1B2b

Quedan fuera la clasificación automática del rol y del fragmento, propuestas de
capítulos, confianza, revisión humana de destinos, OCR y cualquier generación o
verificación de texto.
