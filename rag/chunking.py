"""
chunking.py

Responsabilidad única: partir un documento largo en trozos manejables
(chunks) para indexar y para poder citar con precisión (un chunk es la
unidad mínima que se cita, no el documento entero).

Partición por palabras con solapamiento, para no cortar una idea justo
por la mitad entre dos chunks.
"""

import hashlib


def split_into_chunks(doc_id: str, text: str, chunk_size: int = 120, overlap: int = 20) -> list:
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    position = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk_text = " ".join(words[start:end])
        chunk_id = f"{doc_id}::{position}::{hashlib.sha1(chunk_text.encode()).hexdigest()[:8]}"
        chunks.append({
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "position": position,
            "text": chunk_text,
        })
        position += 1
        if end == len(words):
            break
        start = end - overlap
    return chunks
