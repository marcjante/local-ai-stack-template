"""
citations.py

Responsabilidad única: producir el formato de cita a partir de los chunks
finales (ya rerankeados) — con el fragmento EXACTO citado, no un resumen,
para que la cita se pueda verificar contra el chunk original.
"""


def format_citations(chunks: list) -> list:
    return [
        {
            "doc_id": c.get("doc_id"),
            "chunk_id": c.get("chunk_id"),
            "doc_version": c.get("doc_version"),
            "quote": c.get("text", "")[:300],
            "score": round(c.get("combined_score", c.get("score", 0.0)), 4),
        }
        for c in chunks
    ]
