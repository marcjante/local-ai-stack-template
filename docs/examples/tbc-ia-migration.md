# Migrar TBC-IA a Local AI Studio

Basado en la arquitectura real de tu TBC-IA
(https://marcjante.github.io/TBC-IA/), no en aproximaciones.

## Puertos — no hay conflicto real

Tu TBC-IA corre con `uvicorn` en el puerto **8000**. Local AI Studio
usa 8080 (backend), 8090 (panel) y 8091 (LLM Gateway). No chocan —
puedes tener los dos arrancados a la vez.

## Diferencias reales de arquitectura (para saber qué esperar)

| | Tu TBC-IA | Local AI Studio (por defecto) |
|---|---|---|
| Embeddings | `bge-m3` real, vía Ollama, con prefijo `"Tuberculosis: "` en cada consulta | `hashing_trick_256` (sin modelo real) |
| Vector store | ChromaDB persistente | Postgres JSON (o pgvector si lo activas) |
| Chunking | 2000 caracteres / 300 de solapamiento | Por palabras — ver más abajo |
| Filtro de relevancia | Doble umbral (permisivo/estricto según si la pregunta trae palabra clave de TB) | Umbral único |
| Reranking | Ninguno | Sí (`rag/rerank.py`) — esto es una mejora real sobre tu sistema actual |
| top_k | 8 (elegido deliberadamente para evitar alucinaciones) | Configurable por proyecto — se puso también en 8, misma razón |
| Guardrails | Prompt + detección de frases delatoras ("sin embargo, puedo ofrecerte...") que descarta la respuesta completa | Circuito de verificación con veredicto (veraz/revisar/sin_verificar) y cita por afirmación |
| Multilenguaje / triaje de urgencias | Sí (4 idiomas, reglas JS deterministas, nunca llega al LLM) | No implementado — ver más abajo |

**Bug real encontrado y corregido al preparar esto**: `chunk_size` y
`chunk_overlap` se guardaban en la configuración del proyecto (visibles
en el Project Dashboard) pero nunca se usaban de verdad al indexar —
siempre se aplicaba un valor fijo, sin importar lo que configuraras.
Corregido: ahora el troceado respeta de verdad lo que pongas en cada
proyecto.

## 1. Crear el proyecto

```bash
cd local-ai-stack-template
python3 scripts/setup_tbc_ia_project.py --model llama3.1:8b
```

Deja el proyecto "TBC-IA" con:
- `top_k=8` — igual que tu sistema real, y por el mismo motivo (más
  fragmentos aumenta cobertura pero también el riesgo de alucinación).
- `chunk_size=330` / `overlap=50` en palabras — el equivalente
  aproximado a tus 2000/300 caracteres reales (nuestro chunking es por
  palabras, no por caracteres; no es una conversión exacta).
- `temperature=0.2` — bajo, coherente con respuestas clínicas.

## 2. Subir tu base de conocimiento real

```bash
python3 scripts/setup_tbc_ia_project.py --knowledge-dir ~/Desktop/"TBC IA"/documents
```

Tus documentos están organizados en `documents/01_WHO/`,
`documents/02_CDC/`, `documents/03_ECDC/` — el script recorre
subcarpetas, así que los coge todos de una vez. Usan PyMuPDF para
extraer texto de los PDF; nuestro extractor usa `pypdf` — en la
mayoría de PDFs de texto normal el resultado es equivalente, pero si
alguno tiene tablas complejas o está escaneado, puede salir peor aquí.
No lo he podido comparar contra tus PDFs reales.

## 3. Comparar de verdad, con tus datos reales de evaluación

Ya tienes exactamente lo que hace falta para esto — no hay que
inventar nada:

- `FAQ_pacientes_tuberculosis.md` (200 preguntas clínicas)
- `Banco_360_respuestas.md` (360 preguntas coloquiales)
- Cobertura ya medida en tu sistema actual: **~61%** (clasificación
  automática de "tiene respuesta" vs "sin cobertura" — no verificación
  clínica de que la respuesta sea correcta, tal como tú mismo lo
  documentas).

Pasos:
1. Convierte una muestra de esas preguntas (o todas, si quieres el
   número comparable) al formato de `evaluation/cases_rag_example.json`
   — cada caso con `expect_contains` apuntando a un fragmento que
   debería aparecer si la respuesta tiene cobertura real.
2. Ejecuta ese fichero contra Local AI Studio: panel → Evaluation →
   target `rag`.
3. Compara el `pass_rate` resultante contra tu ~61% real.

Dado que Local AI Studio usa embeddings mucho más simples
(`hashing_trick_256` vs `bge-m3`) y no tiene el filtro de doble umbral
ni el prefijo `"Tuberculosis: "` en las consultas, **es razonable
esperar una cobertura peor** en esta comparación inicial — eso no
significa que la plantilla esté mal, significa que le falta conectar
un embedding real para ser justa la comparación (ver más abajo).

## Lo que NO está en Local AI Studio todavía, y que tu TBC-IA sí tiene

Para que la decisión de migrar sea informada, esto es lo que perderías
si migraras hoy mismo sin más desarrollo:

- **Embeddings reales** (bge-m3) — usa un backend de prueba en su
  lugar. Cambiar esto es desarrollo real (sustituir `rag/embeddings.py`
  para llamar a Ollama con `bge-m3`), no una opción de configuración.
- **Filtro de doble umbral** por palabra clave de dominio — no existe,
  hay un único umbral de relevancia.
- **Guardrail de "frases delatoras"** que descarta la respuesta
  completa — el circuito de verificación de Local AI Studio hace algo
  distinto (veredicto + cita), no exactamente lo mismo.
- **Chat de pacientes multilenguaje con triaje de urgencias
  determinista** — no existe ningún equivalente. Esto sería un
  desarrollo nuevo bastante grande (plugin propio con reglas JS o
  Python + páginas de chat dedicadas), no algo que salga de
  configurar el multi-proyecto.
- **Reranking** — aquí Local AI Studio sí tiene algo que tu sistema
  actual no tiene (`rag/rerank.py`). Es una mejora real, no al revés.

## Resumen honesto

Migrar TBC-IA de un día para otro perdería capacidades reales que hoy
funcionan (embeddings de dominio, triaje de urgencias, multilenguaje).
Lo que sí ganarías: multi-proyecto real (poder tener TBC-IA junto a
otros proyectos sin mezclarlos), permisos, backup/restore, Model
Manager, y migraciones versionadas — infraestructura, no la lógica
clínica específica que ya tienes afinada.

La decisión razonable, con los datos que hay: usar esto como plantilla
para un proyecto **nuevo** que todavía no tenga la inversión ya hecha
en TBC-IA, o como banco de pruebas para decidir si merece la pena
portar piezas concretas (por ejemplo, el reranking que aquí sí existe)
de vuelta a tu sistema actual, en vez de al revés.
