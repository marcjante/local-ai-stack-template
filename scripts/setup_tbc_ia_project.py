"""
setup_tbc_ia_project.py

Crea el proyecto "TBC-IA" dentro de Local AI Studio, con la
configuración que corresponde a un asistente clínico de tuberculosis
(plantilla "clinical" + ajustes propios). NO copia tu base de
conocimiento real (bibliografía, FAQs, PDFs) — eso vive en tu Mac, no
en este repo. Lo que hace este script es dejar el proyecto listo para
que tú subas esos documentos desde Knowledge, o los indexes en bloque
con --knowledge-dir.

Uso:
    python3 scripts/setup_tbc_ia_project.py
    python3 scripts/setup_tbc_ia_project.py --knowledge-dir ~/Desktop/"TBC IA"/knowledge_base

--knowledge-dir: opcional. Si lo pasas, sube TODOS los .pdf/.docx/.txt/
.md/.csv/.json/.html que encuentre ahí (recursivo), como haría el botón
"Upload" de Knowledge, uno por uno.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.db import (  # noqa: E402
    create_project, update_project_settings, create_collection,
    register_document, get_project,
)
from rag.file_parsers import extract_text, EXTRACTORS  # noqa: E402
from rag.chunking import split_into_chunks  # noqa: E402
from rag.embeddings import embed_text  # noqa: E402
from rag.vector_store import add_chunks  # noqa: E402

PROJECT_ID = "tbc-ia"

SYSTEM_PROMPT = (
    "Eres un asistente clínico especializado en tuberculosis. Responde con "
    "precisión clínica, citando siempre la fuente exacta del documento del "
    "que sale cada afirmación. Si la información no es concluyente o no "
    "está en los documentos indexados, dilo explícitamente en vez de "
    "inventar una respuesta. No sustituyes el criterio de un profesional "
    "sanitario."
)


def create_tbc_ia_project(default_model: str = "llama3.1:8b"):
    if get_project(PROJECT_ID):
        print(f"El proyecto '{PROJECT_ID}' ya existe — se actualiza su configuración, no se recrea.")
    else:
        print(f"Creando proyecto '{PROJECT_ID}'...")

    create_project(PROJECT_ID, "TBC-IA", "Asistente clínico de tuberculosis", "clinical")
    update_project_settings(
        PROJECT_ID,
        default_model=default_model,
        embedding_model="hashing_trick_256",  # backend por defecto; ver nota sobre bge-m3 más abajo
        system_prompt=SYSTEM_PROMPT,
        temperature=0.2,  # bajo a propósito: respuestas clínicas, no creativas
        top_k=8,
        chunk_size=330,   # ≈2000 caracteres (tu TBC-IA real usa 2000/300 en caracteres;
        chunk_overlap=50,  # aquí se trocea por palabras, esto es el equivalente aproximado)
    )
    create_collection("default", "Default", project_id=PROJECT_ID)
    print(f"Proyecto '{PROJECT_ID}' listo. Ábrelo en el panel: /projects → 'TBC-IA' → Switch to")def bulk_upload(knowledge_dir: str):
    supported = tuple(EXTRACTORS.keys())
    uploaded, skipped = 0, 0
    for root, _, files in os.walk(knowledge_dir):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in supported:
                skipped += 1
                continue
            path = os.path.join(root, fname)
            try:
                with open(path, "rb") as f:
                    content = f.read()
                text = extract_text(fname, content)
                if not text.strip():
                    print(f"  (vacío tras extraer texto, se omite) {fname}")
                    skipped += 1
                    continue
                chunks = split_into_chunks(fname, text, chunk_size=330, overlap=50)
                embeddings = [embed_text(c["text"]) for c in chunks]
                if chunks:
                    add_chunks(chunks, embeddings)
                register_document(fname, "default", fname, None, "v1",
                                   "hashing_trick_256", text, len(chunks), project_id=PROJECT_ID)
                print(f"  indexado: {fname} ({len(chunks)} chunks)")
                uploaded += 1
            except Exception as e:
                print(f"  ERROR con {fname}: {e}")
                skipped += 1
    print(f"\nSubida en bloque terminada: {uploaded} documentos indexados, {skipped} omitidos/con error.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="llama3.1:8b", help="Modelo por defecto del proyecto")
    parser.add_argument("--knowledge-dir", default=None, help="Carpeta con documentos a indexar en bloque")
    args = parser.parse_args()

    create_tbc_ia_project(default_model=args.model)

    if args.knowledge_dir:
        if not os.path.isdir(args.knowledge_dir):
            print(f"AVISO: '{args.knowledge_dir}' no existe o no es una carpeta — nada que subir.")
        else:
            print(f"\nSubiendo documentos desde: {args.knowledge_dir}")
            bulk_upload(args.knowledge_dir)
