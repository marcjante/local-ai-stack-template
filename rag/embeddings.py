"""
embeddings.py

Responsabilidad única: convertir texto en vectores. Nada de retrieval,
nada de reranking, nada de formatear citas — eso vive en los otros
ficheros de este paquete. Separarlo así permite cambiar de modelo de
embeddings sin tocar el resto del pipeline de RAG.
"""


def embed_text(text: str) -> list:
    """
    Sustituye esto por la llamada real (bge-m3, OpenAI embeddings, etc.).
    Debe devolver siempre un vector de la misma dimensión.
    """
    raise NotImplementedError("Conecta aquí tu modelo de embeddings real")
