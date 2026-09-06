"""
rerank.py

Responsabilidad única: reordenar los candidatos de retrieval.py combinando
la similitud vectorial (ya viene en 'score') con una señal barata de
coincidencia léxica, y quedarse con los N mejores.

Combinar dos señales, aunque ambas sean simples, da un resultado más
robusto que confiar en una sola — sobre todo porque el embedding por
defecto (hashing trick) es limitado. Al conectar un modelo de embeddings
real, el peso léxico puede bajarse o quitarse.
"""


def _lexical_overlap(query: str, text: str) -> float:
    q_words = set(query.lower().split())
    t_words = set(text.lower().split())
    if not q_words:
        return 0.0
    return len(q_words & t_words) / len(q_words)


def rerank(query: str, candidates: list, top_n: int = 5,
           vector_weight: float = 0.7, lexical_weight: float = 0.3) -> list:
    for c in candidates:
        lexical = _lexical_overlap(query, c.get("text", ""))
        c["lexical_overlap"] = lexical
        c["combined_score"] = vector_weight * c.get("score", 0.0) + lexical_weight * lexical

    ranked = sorted(candidates, key=lambda c: c["combined_score"], reverse=True)
    return ranked[:top_n]
