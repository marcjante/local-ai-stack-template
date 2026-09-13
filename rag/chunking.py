"""
chunking.py

Responsabilidad única: partir un documento largo en trozos manejables
(chunks) para indexar y poder citar con precisión.

Compatibilidad:
- texto plano sigue funcionando;
- cada chunk incorpora offsets de caracteres reales respecto al bloque;
- page_number y section son metadatos opcionales para documentos
  estructurados/PDF.
"""

import hashlib
import re


def _word_spans(text: str):
    """
    Devuelve las palabras junto con sus posiciones reales en el texto
    original. Esto evita perder offsets cuando existen saltos de línea,
    tabulaciones o múltiples espacios.
    """
    return [
        (match.group(0), match.start(), match.end())
        for match in re.finditer(r"\S+", text)
    ]


def split_into_chunks(
    doc_id: str,
    text: str,
    chunk_size: int = 120,
    overlap: int = 20,
    page_number=None,
    section=None,
    position_offset: int = 0,
) -> list:
    spans = _word_spans(text)

    if not spans:
        return []

    if chunk_size <= 0:
        raise ValueError("chunk_size debe ser mayor que 0")

    if overlap < 0:
        raise ValueError("overlap no puede ser negativo")

    if overlap >= chunk_size:
        raise ValueError("overlap debe ser menor que chunk_size")

    chunks = []
    start = 0
    position = position_offset

    while start < len(spans):
        end = min(start + chunk_size, len(spans))

        char_start = spans[start][1]
        char_end = spans[end - 1][2]

        # Conservamos el rango real del texto original.
        original_slice = text[char_start:char_end]

        # Para embeddings/RAG normalizamos únicamente el whitespace.
        chunk_text = " ".join(original_slice.split())

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

        if end == len(spans):
            break

        start = end - overlap

    return chunks
