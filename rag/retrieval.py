"""
retrieval.py

Responsabilidad única: dado un texto de consulta, devolver los documentos
candidatos (de ChromaDB, de un índice BM25, o de ambos combinados). No
decide el orden final (eso es rerank.py) ni cómo se citan (citations.py).
"""

from rag.embeddings import embed_text


def retrieve(query: str, top_k: int = 20) -> list:
    """
    Sustituye esto por la consulta real a ChromaDB (y opcionalmente BM25,
    fusionando resultados con RRF como en TBC-IA). Debe devolver una
    lista de documentos candidatos, sin reordenar todavía.
    """
    _ = embed_text(query)
    raise NotImplementedError("Conecta aquí tu base vectorial real")
