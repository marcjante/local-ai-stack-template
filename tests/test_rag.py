"""
test_rag.py

El pipeline de RAG en sí: indexar, recuperar, citar. Incluye el test
más importante de todo el proyecto multi-proyecto: que dos proyectos
con documentos distintos JAMÁS se mezclen en una búsqueda.
"""

from rag.chunking import split_into_chunks
from rag.embeddings import embed_text
from rag.vector_store import add_chunks
from rag.retrieval import retrieve
from rag.rerank import rerank
from rag.citations import format_citations
from db.db import register_document, create_collection


def _index(doc_id, text, project_id):
    create_collection("default", "Default", project_id=project_id)
    chunks = split_into_chunks(doc_id, text)
    embeddings = [embed_text(c["text"]) for c in chunks]
    add_chunks(chunks, embeddings)
    register_document(doc_id, "default", None, "text/plain", "v1",
                       "hashing_trick_256", text, len(chunks), project_id=project_id)
    return len(chunks)


def test_index_and_retrieve_same_project(project_id):
    _index("doc-basket", "El baloncesto se juega con un balón y una canasta.", project_id)
    results = retrieve("balón canasta baloncesto", top_k=5, project_id=project_id)
    assert any(r["doc_id"] == "doc-basket" for r in results)


def test_citations_include_exact_quote(project_id):
    text = "El tratamiento de tuberculosis dura seis meses con varios fármacos."
    _index("doc-tbc", text, project_id)
    candidates = retrieve("tratamiento tuberculosis", top_k=5, project_id=project_id)
    top = rerank("tratamiento tuberculosis", candidates, top_n=1)
    cited = format_citations(top)
    assert len(cited) == 1
    assert "tuberculosis" in cited[0]["quote"]
    assert cited[0]["doc_id"] == "doc-tbc"


def test_project_isolation_never_leaks(project_id):
    """
    EL TEST QUE MÁS IMPORTA: dos proyectos con documentos de contenido
    opuesto — una búsqueda en uno JAMÁS debe devolver nada del otro,
    por mucho que el contenido sea parecido o la query sea genérica.
    """
    from db.db import create_project

    project_a = project_id
    project_b = f"{project_id}-b"
    create_project(project_b, "Proyecto B para aislamiento")

    _index("doc-a-basket", "Documento del proyecto A: baloncesto, canastas, Michael Jordan.", project_a)
    _index("doc-b-chess", "Documento del proyecto B: ajedrez, jaque mate, Kasparov.", project_b)

    try:
        results_a = retrieve("cualquier cosa", top_k=20, project_id=project_a)
        results_b = retrieve("cualquier cosa", top_k=20, project_id=project_b)

        doc_ids_a = {r["doc_id"] for r in results_a}
        doc_ids_b = {r["doc_id"] for r in results_b}

        assert "doc-b-chess" not in doc_ids_a, "¡Proyecto A vio un documento del Proyecto B!"
        assert "doc-a-basket" not in doc_ids_b, "¡Proyecto B vio un documento del Proyecto A!"

        # Y con consultas dirigidas al contenido del OTRO proyecto, tampoco debe aparecer
        results_a_ajedrez = retrieve("ajedrez jaque mate Kasparov", top_k=20, project_id=project_a)
        assert all(r["doc_id"] != "doc-b-chess" for r in results_a_ajedrez)
    finally:
        from db.db import get_conn
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE project_id = %s", (project_b,))
            cur.execute("DELETE FROM collections WHERE project_id = %s", (project_b,))
            cur.execute("DELETE FROM projects WHERE id = %s", (project_b,))


def test_retrieve_scoped_to_single_doc(project_id):
    _index("doc-x", "Contenido del documento X sobre cocina.", project_id)
    _index("doc-y", "Contenido del documento Y sobre jardinería.", project_id)

    results = retrieve("cualquier consulta", top_k=10, doc_id="doc-x", project_id=project_id)
    assert all(r["doc_id"] == "doc-x" for r in results)
