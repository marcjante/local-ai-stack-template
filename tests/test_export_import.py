"""test_export_import.py — exportar/importar UN proyecto, con datos reales."""

from common.project_export import export_project, import_project
from db.db import get_conn, create_collection


class _FakeFileStorage:
    """Simula el objeto que Flask pasa desde request.files — solo necesita .save()."""
    def __init__(self, path):
        self._path = path

    def save(self, dest):
        import shutil
        shutil.copy(self._path, dest)


def test_export_then_import_preserves_document(project_id):
    from rag.chunking import split_into_chunks
    from rag.embeddings import embed_text
    from rag.vector_store import add_chunks
    from db.db import register_document

    create_collection("default", "Default", project_id=project_id)
    text = "Documento de prueba para export/import, sobre fotosíntesis."
    chunks = split_into_chunks("doc-export-test", text)
    embeddings = [embed_text(c["text"]) for c in chunks]
    add_chunks(chunks, embeddings)
    register_document("doc-export-test", "default", "test.txt", "text/plain", "v1",
                       "hashing_trick_256", text, len(chunks), project_id=project_id)

    zip_path = export_project(project_id)
    assert zip_path.exists()

    new_project_id = project_id + "-imported"
    try:
        result = import_project(_FakeFileStorage(zip_path), new_project_id=new_project_id)
        assert result["n_documents_imported"] == 1

        from db.db import get_document
        doc = get_document("doc-export-test")
        assert doc is not None
        assert doc["project_id"] == new_project_id
    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM rag_chunks WHERE doc_id = %s", ("doc-export-test",))
            cur.execute("DELETE FROM documents WHERE doc_id = %s", ("doc-export-test",))
            cur.execute("DELETE FROM collections WHERE project_id = %s", (new_project_id,))
            cur.execute("DELETE FROM project_settings WHERE project_id = %s", (new_project_id,))
            cur.execute("DELETE FROM projects WHERE id = %s", (new_project_id,))
