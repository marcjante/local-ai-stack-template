"""
citations.py

Responsabilidad única: a partir de los documentos finales (ya
rerankeados), producir el formato de cita que se le muestra al usuario
junto a la respuesta del LLM. Separado a propósito: cambiar el formato
de cita no debería tocar retrieval ni rerank.
"""


def format_citations(documents: list) -> list:
    """
    Sustituye esto por el formato real de tu proyecto (autor/año, URL,
    página del PDF con resaltado como en TBC-IA, etc.).
    """
    return [{"source": d.get("source"), "snippet": d.get("text", "")[:200]} for d in documents]
