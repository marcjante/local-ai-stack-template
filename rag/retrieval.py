"""
retrieval.py

Responsabilidad única: dada una consulta en texto, indexar un documento
o devolver los chunks más parecidos ya indexados. No decide el orden
final (eso es rerank.py) ni cómo se citan (citations.py).
"""

from rag.chunking import split_into_chunks
from rag.embeddings import embed_text
from rag.vector_store import add_chunks, search


def index_document(doc_id: str, text: str, doc_version: str = "v1") -> int:
    """Trocea, calcula embeddings y guarda un documento. Devuelve nº de chunks creados."""
    chunks = split_into_chunks(doc_id, text)
    embeddings = [embed_text(c["text"]) for c in chunks]
    if chunks:
        add_chunks(chunks, embeddings, doc_version=doc_version)
    return len(chunks)


def retrieve(query: str, top_k: int = 20, doc_id: str = None, project_id: str = None) -> list:
    """Devuelve los chunks más parecidos a la consulta, acotado al proyecto si se indica."""
    query_embedding = embed_text(query)
    return search(query_embedding, top_k=top_k, doc_id=doc_id, project_id=project_id)
