"""
project_export.py

Exporta/importa UN proyecto concreto, no toda la instalación (eso ya lo
cubre common/backup.py). Pensado para: copiar un proyecto entre
ordenadores, o compartirlo como plantilla de partida sin exportar el
resto de proyectos que puedan convivir en la misma instalación.

Formato: un .zip con un único manifest.json que contiene, en JSON (no
pg_dump — aquí interesa exportar FILAS concretas de un proyecto, no
tablas enteras): datos del proyecto, su project_settings, sus
colecciones, sus documentos (incluido el texto extraído, para poder
reindexar en el destino) y sus integraciones de n8n. Los chunks NO se
incluyen — se regeneran reindexando en el destino, así el export no
depende de qué backend de embeddings tenga configurado el otro lado.
"""

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from db.db import (
    get_project, get_project_settings, list_collections,
    list_documents, get_document, create_project, update_project_settings,
    create_collection, set_integration_enabled, list_integrations, register_document,
)
from rag.chunking import split_into_chunks
from rag.embeddings import embed_text
from rag.vector_store import add_chunks


def export_project(project_id: str) -> Path:
    project = get_project(project_id)
    if not project:
        raise ValueError(f"proyecto '{project_id}' no encontrado")

    settings = get_project_settings(project_id)
    collections = list_collections(project_id=project_id)
    docs_summary = list_documents(project_id=project_id)
    documents_full = [get_document(d["doc_id"]) for d in docs_summary]
    integrations = list_integrations(project_id=project_id)

    manifest = {
        "format": "local-ai-stack-project-export/v1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "project": dict(project),
        "settings": dict(settings) if settings else {},
        "collections": [dict(c) for c in collections],
        "documents": [dict(d) for d in documents_full],
        "integrations": [dict(i) for i in integrations],
    }

    def _default(o):
        if hasattr(o, "isoformat"):
            return o.isoformat()
        return str(o)

    tmp_dir = Path(tempfile.mkdtemp(prefix="lastack_project_export_"))
    zip_path = tmp_dir / f"{project_id}.ai-project.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, default=_default))

    return zip_path


def import_project(zip_file_storage, new_project_id: str = None, include_documents: bool = True) -> dict:
    tmp_dir = Path(tempfile.mkdtemp(prefix="lastack_project_import_"))
    zip_path = tmp_dir / "uploaded.zip"
    zip_file_storage.save(zip_path)

    try:
        with zipfile.ZipFile(zip_path) as zf:
            if "manifest.json" not in zf.namelist():
                raise ValueError("el .zip no contiene manifest.json — no parece un export de proyecto válido")
            manifest = json.loads(zf.read("manifest.json"))
    except zipfile.BadZipFile:
        raise ValueError("el fichero subido no es un .zip válido")

    if manifest.get("format") != "local-ai-stack-project-export/v1":
        raise ValueError("formato de export de proyecto desconocido")

    src_project = manifest["project"]
    project_id = new_project_id or src_project["id"]

    create_project(project_id, src_project["name"], src_project.get("description"), src_project.get("project_type", "blank"))

    settings = manifest.get("settings") or {}
    settings_fields = {k: v for k, v in settings.items() if k not in ("project_id", "updated_at")}
    if settings_fields:
        update_project_settings(project_id, **settings_fields)

    for c in manifest.get("collections", []):
        create_collection(c["id"], c["name"], project_id=project_id, description=c.get("description"))

    n_documents = 0
    if include_documents:
        for d in manifest.get("documents", []):
            if d.get("raw_text"):
                chunks = split_into_chunks(d["doc_id"], d["raw_text"])
                embeddings = [embed_text(c["text"]) for c in chunks]
                if chunks:
                    add_chunks(chunks, embeddings, doc_version=d.get("doc_version", "v1"))
                register_document(
                    d["doc_id"], d.get("collection_id"), d.get("filename"), d.get("content_type"),
                    d.get("doc_version", "v1"), d.get("embedding_model", "hashing_trick_256"),
                    d["raw_text"], len(chunks), project_id=project_id,
                )
                n_documents += 1

    for i in manifest.get("integrations", []):
        set_integration_enabled(i["flow_name"], i["enabled"], project_id=project_id, description=i.get("description"))

    return {
        "project_id": project_id,
        "exported_at": manifest.get("exported_at"),
        "n_collections": len(manifest.get("collections", [])),
        "n_documents_imported": n_documents,
        "n_integrations": len(manifest.get("integrations", [])),
    }
