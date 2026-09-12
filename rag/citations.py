"""
citations.py

Produce citas verificables a partir de chunks finales ya rerankeados.
Incluye el fragmento exacto y, cuando exista, metadatos de localización.
"""


def format_citations(chunks: list) -> list:
    return [
        {
            "doc_id": c.get("doc_id"),
            "chunk_id": c.get("chunk_id"),
            "doc_version": c.get("doc_version"),
            "page_number": c.get("page_number"),
            "section": c.get("section"),
            "char_start": c.get("char_start"),
            "char_end": c.get("char_end"),
            "quote": c.get("text", "")[:300],
            "score": round(
                c.get("combined_score", c.get("score", 0.0)),
                4,
            ),
        }
        for c in chunks
    ]
