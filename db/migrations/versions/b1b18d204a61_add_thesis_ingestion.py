"""Shared originals and project-scoped Thesis ingestion (Phase 1B1)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "b1b18d204a61"
down_revision = "f1a7c93d820b"
branch_labels = None
depends_on = None

ROLES = "'own_data','own_results','study_protocol','scientific_evidence','administrative','draft','writing_guideline','bibliography','unknown'"


def _dates():
    return [sa.Column(n, sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("now()")) for n in ("created_at", "updated_at")]


def upgrade():
    # filename and content_type already provide original_filename and mime_type.
    for name in ("content_hash", "storage_key", "source_role", "extraction_status"):
        op.add_column("documents", sa.Column(name, sa.Text(), nullable=True))
    op.create_unique_constraint("uq_documents_project_doc", "documents", ["project_id", "doc_id"])
    op.create_unique_constraint("uq_documents_project_hash", "documents", ["project_id", "content_hash"])
    op.create_check_constraint("ck_documents_hash", "documents", "content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'")
    op.create_check_constraint("ck_documents_role", "documents", f"source_role IS NULL OR source_role IN ({ROLES})")
    op.create_unique_constraint("uq_rag_chunks_doc_chunk", "rag_chunks", ["doc_id", "chunk_id"])
    op.create_table(
        "thesis_file_ingestions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("thesis_profiles.project_id", ondelete="CASCADE"), nullable=False),
        sa.Column("doc_id", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("source_role", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("binary_identity", sa.Text(), nullable=False),
        sa.Column("reused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("parser", sa.Text()), sa.Column("parser_version", sa.Text()),
        sa.Column("error", sa.Text()), sa.Column("warnings", JSONB()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        *_dates(),
        sa.UniqueConstraint("project_id", "doc_id", name="uq_thesis_ingestion_doc"),
        sa.ForeignKeyConstraint(["project_id", "doc_id"], ["documents.project_id", "documents.doc_id"],
                                name="fk_thesis_ingestion_document", deferrable=True, initially="DEFERRED"),
        sa.CheckConstraint(f"source_role IN ({ROLES})", name="ck_thesis_ingestion_role"),
        sa.CheckConstraint("status IN ('pending','queued','extracting','indexed','failed')", name="ck_thesis_ingestion_status"),
        sa.CheckConstraint("binary_identity IN ('sha256_verified','legacy_unverified')", name="ck_thesis_binary_identity"),
    )
    op.create_index("idx_thesis_ingestions_project_status", "thesis_file_ingestions", ["project_id", "status"])
    op.create_table(
        "thesis_fragments",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("doc_id", sa.Text(), nullable=False),
        sa.Column("rag_chunk_id", sa.Text()),
        sa.Column("pgvector_chunk_id", sa.Text()),
        sa.Column("file_type", sa.Text(), nullable=False),
        sa.Column("source_role", sa.Text(), nullable=False),
        sa.Column("source_locator", JSONB(), nullable=False),
        sa.Column("char_start", sa.Integer()), sa.Column("char_end", sa.Integer()),
        sa.Column("fragment_hash", sa.Text(), nullable=False),
        sa.Column("extraction_status", sa.Text(), nullable=False, server_default="indexed"),
        *_dates(),
        sa.ForeignKeyConstraint(["project_id", "doc_id"], ["thesis_file_ingestions.project_id", "thesis_file_ingestions.doc_id"],
                                name="fk_thesis_fragment_ingestion", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["doc_id", "rag_chunk_id"], ["rag_chunks.doc_id", "rag_chunks.chunk_id"],
                                name="fk_thesis_fragment_chunk", deferrable=True, initially="DEFERRED"),
        sa.UniqueConstraint("project_id", "doc_id", "rag_chunk_id", name="uq_thesis_fragment_chunk"),
        sa.UniqueConstraint("project_id", "doc_id", "pgvector_chunk_id", name="uq_thesis_fragment_pgvector"),
        sa.CheckConstraint("num_nonnulls(rag_chunk_id, pgvector_chunk_id) = 1", name="ck_thesis_fragment_reference"),
        sa.CheckConstraint(f"source_role IN ({ROLES})", name="ck_thesis_fragment_role"),
        sa.CheckConstraint("char_start IS NULL OR (char_start >= 0 AND char_end >= char_start)", name="ck_thesis_fragment_offsets"),
    )
    if sa.inspect(op.get_bind()).has_table("rag_chunks_pgvector"):
        op.create_unique_constraint("uq_rag_pgvector_doc_chunk", "rag_chunks_pgvector", ["doc_id", "chunk_id"])
        op.create_foreign_key("fk_thesis_fragment_pgvector", "thesis_fragments", "rag_chunks_pgvector",
                              ["doc_id", "pgvector_chunk_id"], ["doc_id", "chunk_id"],
                              deferrable=True, initially="DEFERRED")
    else:
        # Fail closed if pgvector is enabled later without its reference migration.
        op.create_check_constraint("ck_thesis_pgvector_unavailable", "thesis_fragments", "pgvector_chunk_id IS NULL")


def downgrade():
    op.drop_table("thesis_fragments")
    op.drop_table("thesis_file_ingestions")
    if sa.inspect(op.get_bind()).has_table("rag_chunks_pgvector"):
        constraints = sa.inspect(op.get_bind()).get_unique_constraints("rag_chunks_pgvector")
        if any(c["name"] == "uq_rag_pgvector_doc_chunk" for c in constraints):
            op.drop_constraint("uq_rag_pgvector_doc_chunk", "rag_chunks_pgvector", type_="unique")
    op.drop_constraint("uq_rag_chunks_doc_chunk", "rag_chunks", type_="unique")
    for name, kind in (("ck_documents_role", "check"), ("ck_documents_hash", "check"),
                       ("uq_documents_project_hash", "unique"), ("uq_documents_project_doc", "unique")):
        op.drop_constraint(name, "documents", type_=kind)
    for name in ("extraction_status", "source_role", "storage_key", "content_hash"):
        op.drop_column("documents", name)
