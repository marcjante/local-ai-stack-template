"""Shared document registration and indexing for Knowledge, reviews and Thesis."""

import hashlib
import uuid
from pathlib import Path

from psycopg2.extras import Json, RealDictCursor

from common import document_storage as storage
from db.db import get_conn
from rag.file_parsers import extract_structured_text
from rag.chunking import split_into_chunks
from rag.embeddings import embed_text
from rag import vector_store


ROLES = frozenset({"own_data", "own_results", "study_protocol", "scientific_evidence",
                   "administrative", "draft", "writing_guideline", "bibliography", "unknown"})


class DocumentConflict(ValueError):
    """A caller requested overwriting an existing shared document identity."""


def validate_role(role):
    if not isinstance(role, str) or role not in ROLES:
        raise ValueError("source_role no permitido")
    return role


def chunks_for_document(cur, doc_id):
    # Consult both installed backends, independently of the current configuration.
    chunks = []
    for table, backend in (("rag_chunks", "postgres_json"), ("rag_chunks_pgvector", "pgvector")):
        cur.execute("SELECT to_regclass(%s) AS name", (table,))
        if cur.fetchone()["name"] is None:
            continue
        cur.execute(f"SELECT chunk_id, doc_id, position, text, page_number, section, char_start, char_end "
                    f"FROM {table} WHERE doc_id = %s ORDER BY position, chunk_id", (doc_id,))
        chunks.extend({**dict(row), "backend": backend} for row in cur.fetchall())
    return chunks


def index_blocks(conn, doc_id, text, blocks, *, project_id, doc_version="v1"):
    """The existing chunker/embedding/store, with an optional surrounding transaction."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT chunk_size, chunk_overlap FROM project_settings WHERE project_id = %s", (project_id,))
        settings = cur.fetchone() or {"chunk_size": 120, "chunk_overlap": 20}
    chunks = []
    locators = {}
    for block_index, block in enumerate(blocks or [{"text": text}], 1):
        block_text = block.get("text") or ""
        if not block_text.strip():
            continue
        block_chunks = split_into_chunks(
            doc_id, block_text, chunk_size=settings["chunk_size"], overlap=settings["chunk_overlap"],
            page_number=block.get("page_number"), section=block.get("section"), position_offset=len(chunks),
        )
        locator = dict(block.get("source_locator") or {})
        locator.update({"block_index": block_index, "offset_scope": "extracted_block"})
        if block.get("page_number") is not None:
            locator["page_number"] = block["page_number"]
        if block.get("section") is not None:
            locator["section"] = block["section"]
        for chunk in block_chunks:
            locators[chunk["chunk_id"]] = locator
        chunks.extend(block_chunks)
    if chunks:
        vector_store.add_chunks(chunks, [embed_text(c["text"]) for c in chunks], doc_version=doc_version, conn=conn)
    return chunks, locators


def register_upload(conn, project_id, file, *, role="unknown", collection_id="default", thesis_formats=False,
                    requested_doc_id=None, doc_version="v1"):
    """One hash lock per project/source. Caller commits the document with its ingestion."""
    validate_role(role)
    with storage.prepare(file, thesis_formats=thesis_formats) as (name, mime, digest, stream):
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM projects WHERE id = %s FOR KEY SHARE", (project_id,))
            if cur.fetchone() is None:
                raise ValueError("proyecto no encontrado")
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (project_id + ":" + digest,))
            cur.execute("SELECT * FROM documents WHERE project_id = %s AND content_hash = %s FOR UPDATE", (project_id, digest))
            existing = cur.fetchone()
            if existing:
                return dict(existing), True
            if requested_doc_id:
                cur.execute("SELECT doc_id FROM documents WHERE doc_id=%s", (requested_doc_id,))
                if cur.fetchone() is not None:
                    raise DocumentConflict("doc_id ya existe; utiliza una identidad nueva para otro original")
            if collection_id == "default":
                cur.execute("INSERT INTO collections (id, project_id, name) VALUES ('default', %s, 'Default') ON CONFLICT DO NOTHING", (project_id,))
            cur.execute("SELECT id FROM collections WHERE project_id = %s AND id = %s", (project_id, collection_id))
            if cur.fetchone() is None:
                raise ValueError("colección no encontrada en el proyecto")
            key = storage.save(project_id, digest, stream)
            cur.execute(
                "INSERT INTO documents (doc_id, project_id, collection_id, filename, content_type, "
                "content_hash, storage_key, source_role, extraction_status, doc_version) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s) RETURNING *",
                (requested_doc_id or str(uuid.uuid4()), project_id, collection_id, name, mime, digest, key, role, doc_version),
            )
            return dict(cur.fetchone()), False


def extract_document(conn, project_id, doc_id):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM documents WHERE project_id = %s AND doc_id = %s FOR UPDATE", (project_id, doc_id))
        doc = cur.fetchone()
        if doc is None:
            raise ValueError("documento no encontrado en el proyecto")
        if doc["extraction_status"] == "indexed":
            return dict(doc)
        existing = chunks_for_document(cur, doc_id)
        if existing:
            # Historical index: never infer a hash or recompute embeddings.
            return dict(doc)
        if not doc["storage_key"]:
            return dict(doc)
        path = storage.path_for(doc["storage_key"])
        digest = hashlib.sha256()
        with path.open("rb") as original:
            for block in iter(lambda: original.read(64 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != doc["content_hash"]:
            raise ValueError("el original no coincide con su SHA-256 registrado")
        blocks = extract_structured_text(doc["filename"], path.read_bytes())
        text = "\n".join(b["text"] for b in blocks if b.get("text"))
        if not text.strip():
            raise ValueError("archivo sin texto extraíble; OCR no disponible")
        chunks, locators = index_blocks(conn, doc_id, text, blocks, project_id=project_id, doc_version=doc["doc_version"])
        cur.execute(
            "UPDATE documents SET raw_text=%s, n_chunks=%s, source_metadata=%s, "
            "extraction_status='indexed', indexed_at=now() WHERE project_id=%s AND doc_id=%s RETURNING *",
            (text, len(chunks), Json({"blocks": blocks, "chunk_locators": locators,
                                    "parser": Path(doc["filename"]).suffix.lower(), "parser_version": "structured-v2"}), project_id, doc_id),
        )
        return dict(cur.fetchone())


def upload_and_index(project_id, file, *, collection_id="default", role="unknown", requested_doc_id=None, doc_version="v1"):
    with get_conn() as conn:
        doc, reused = register_upload(conn, project_id, file, role=role, collection_id=collection_id,
                                      requested_doc_id=requested_doc_id, doc_version=doc_version)
        doc = extract_document(conn, project_id, doc["doc_id"])
        return doc, reused
