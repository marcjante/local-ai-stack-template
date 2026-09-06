"""
rerank.py

Responsabilidad única: dado un texto de consulta y una lista de
documentos candidatos (de retrieval.py), reordenarlos por relevancia
real y quedarse con los N mejores antes de pasarlos al LLM.
"""


def rerank(query: str, candidates: list, top_n: int = 5) -> list:
    """
    Sustituye esto por un CrossEncoder, un reranker de la propia base
    vectorial, o cualquier otro criterio de relevancia real.
    """
    raise NotImplementedError("Conecta aquí tu reranker real")
