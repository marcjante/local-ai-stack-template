"""
embeddings.py

Responsabilidad única: convertir texto en un vector numérico comparable
por similitud coseno.

Implementación por defecto: hashing trick (bag-of-words con hash a un
espacio de dimensión fija) — determinista, sin dependencias externas, y
FUNCIONA de verdad, a diferencia de un placeholder. No es tan bueno como
un modelo de embeddings real (bge-m3, OpenAI, etc.), pero permite que
todo el pipeline de RAG se pueda probar de punta a punta sin depender de
un modelo pesado.

Para producción: sustituye embed_text() por tu modelo real. El resto del
pipeline (chunking, vector_store, retrieval, rerank) no necesita cambiar,
solo espera "una lista de floats de longitud fija".
"""

import hashlib
import math
import re

DIMENSIONS = 256


def embed_text(text: str) -> list:
    vector = [0.0] * DIMENSIONS
    words = re.findall(r"[a-záéíóúñü0-9]+", text.lower())
    if not words:
        return vector

    for word in words:
        h = int(hashlib.md5(word.encode()).hexdigest(), 16)
        idx = h % DIMENSIONS
        sign = 1.0 if (h // DIMENSIONS) % 2 == 0 else -1.0
        vector[idx] += sign

    norm = math.sqrt(sum(v * v for v in vector))
    if norm > 0:
        vector = [v / norm for v in vector]
    return vector


def cosine_similarity(a: list, b: list) -> float:
    return sum(x * y for x, y in zip(a, b))
