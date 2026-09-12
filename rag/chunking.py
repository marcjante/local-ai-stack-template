"""
chunking.py

Responsabilidad única: partir un documento largo en trozos manejables
(chunks) para indexar y para poder citar con precisión.

Compatibilidad:
- texto plano sigue funcionando como antes;
- cada chunk incorpora offsets de caracteres aproximados;
- page_number y section son metadatos opcionales preparados para
  documentos estructurados/PDF.
"""

import hashlib


def split_into_chunks(
    doc_id: str,
    text: str,
    chunk_size: int = 120,
    overlap: int = 20,
    page_number=None,
    section=None,
    position_offset: int = 0,
) -> list:
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    position = position_offset
    search_from = 0

    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk_text = " ".join(words[start:end])

        # Localiza el chunk dentro del texto original.
        # Es aproximado porque split()/join() normaliza espacios,
        # pero permite mantener trazabilidad útil sin romper compatibilidad.
        char_start = text.find(chunk_text, search_from)

        if char_start < 0:
            char_start = None
            char_end = None
        else:
            char_end = char_start + len(chunk_text)
            search_from = max(char_start, 0)

        chunk_id = (
            f"{doc_id}::{position}::"
            f"{hashlib.sha1(chunk_text.encode()).hexdigest()[:8]}"
        )

        chunks.append({
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "position": position,
            "text": chunk_text,
            "page_number": page_number,
            "section": section,
            "char_start": char_start,
            "char_end": char_end,
        })

        position += 1

        if end == len(words):
            break

        start = end - overlap

    return chunks
