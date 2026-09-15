# Thesis — Fase 1A

Implementación en el backend Flask (`backend/main.py`). Reutiliza JWT y
`require_project_role`: un miembro `viewer` puede consultar; `editor` y `admin`
pueden crear y actualizar. El administrador global conserva su acceso existente.
Todas las peticiones requieren `Authorization: Bearer <token>`.

## Migración

`f1a7c93d820b` depende de `ee1060d265ac` y crea únicamente `thesis_profiles`
y `thesis_chapters`. Usa identificadores TEXT, fechas TIMESTAMPTZ, claves
foráneas con CASCADE y una restricción única de perfil por proyecto.
La clave `(project_id, parent_id)` impide enlazar un capítulo de otro proyecto.
`approved_version_id` queda nullable y sin FK hasta implementar las versiones;
ningún endpoint de esta fase permite asignarlo.

La preparación de tests sigue CI: migrar una base **exclusiva de pruebas** hasta
`head` antes de ejecutar pytest. Nunca utilizar la base personal para estos tests,
que crean y eliminan datos. La prueba de downgrade utiliza un esquema privado
dentro de una transacción que se revierte, sin degradar el esquema compartido.

## Contrato

### POST `/api/projects/<project_id>/thesis`

Entrada: objeto JSON, que puede ser `{}`. Campos permitidos:
`title`, `author`, `supervisors`, `university`, `program`, `language`,
`citation_style`, `template`. Todos son texto; se admite `null` salvo en
`title` y `language`. `supervisors` es texto libre. Por defecto, `title` es
vacío e `language` es `es`. El idioma no puede estar vacío. Se rechazan campos
desconocidos, incluido `project_id`: el proyecto procede exclusivamente de la URL.

```json
{"title": "Mi tesis", "language": "es", "university": "Universidad"}
```

Respuesta inicial: `201`, `{"created": true, "profile": {...}}`.
Repetición: `200`, `{"created": false, "profile": {...}}` con el perfil
existente. La repetición no sobrescribe el perfil ni los títulos, ni duplica
capítulos, incluso con peticiones concurrentes. Para modificar el perfil se usa PUT.
El perfil y los 16 capítulos iniciales se guardan en una sola transacción.

### GET `/api/projects/<project_id>/thesis/structure`

Respuesta `200` con `project_id`, `profile` y `chapters`. Los capítulos forman
una lista plana con `parent_id`, ordenada jerárquicamente por `order_index`,
con desempate estable por código e identificador. Cada capítulo incluye
`id`, `project_id`, `parent_id`, `code`, `title`, `chapter_type`, `order_index`,
`status`, `approved_version_id`, `created_at` y `updated_at`.

Los 16 bloques del diseño se crean con orden 1–16 y estado `empty`.
Los tipos estables son `cover`, `abstracts`, `keywords`, `indexes`,
`introduction`, `background`, `objectives`, `methods`, `results`, `discussion`,
`limitations`, `implications`, `conclusions`, `references`, `acknowledgements`,
`appendices`.

El servicio `update_chapter_title(project_id, chapter_id, title)` permite
modificar el título conservando el tipo semántico. No hay bloqueo secuencial.
Esta fase incluye soporte SQL para subapartados, pero no añade endpoints de
edición del árbol ni de creación de subapartados.

### PUT `/api/projects/<project_id>/thesis/profile`

Actualización parcial con los mismos campos de POST. Los omitidos se conservan;
`null` borra un campo opcional. `{}` no modifica el perfil.

```json
{"language": "ca", "citation_style": "vancouver", "template": "doctoral"}
```

Respuesta `200`: `{"profile": {...}}`. Las fechas se serializan mediante
`jsonify`, con el formato HTTP de fecha predeterminado de Flask.

### Errores

Todos devuelven `{"error": "..."}`: `400` para JSON o perfil inválido;
`401` para autenticación ausente/inválida; `403` para permisos insuficientes;
`404` para proyecto o tesis inexistentes; `409` para conflictos de integridad;
`500` para errores de PostgreSQL, sin exponer detalles de conexión en la respuesta.
La autorización precede a la consulta: un usuario sin pertenencia recibe `403`
aunque el proyecto no exista; un administrador global recibe `404`.

## Siguiente fase propuesta: 1B

1. Inspeccionar los parsers y la deduplicación existentes por formato.
2. Añadir ingestiones, fragmentos y propuestas, referenciando `documents` y
   `rag_chunks`, con pertenencia al mismo proyecto reforzada por restricciones SQL.
3. Implementar subida múltiple y trabajos asíncronos reutilizando Redis/RQ.
4. Conservar página/sección y hoja/rango, hash y versión del parser.
5. Clasificar mediante el LLM Gateway y exigir confirmación humana del destino.
6. Probar aislamiento, reintentos idempotentes, duplicados, localizadores,
   fallos de extracción y aprobación/corrección de propuestas.

Sin generación de texto ni exportación en esa fase.
