"""
file_parsers.py

Convierte cada formato soportado a texto plano, que es lo único que
necesita el resto del pipeline de RAG (chunking, embeddings...). Añadir
un formato nuevo es añadir una función aquí y una entrada en
EXTRACTORS — no hace falta tocar nada más del pipeline.
"""

import io

from pypdf import PdfReader
from docx import Document as DocxDocument


def extract_pdf(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_docx(content: bytes) -> str:
    doc = DocxDocument(io.BytesIO(content))
    return "\n".join(p.text for p in doc.paragraphs)


def extract_plain_text(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


EXTRACTORS = {
    ".pdf": extract_pdf,
    ".docx": extract_docx,
    ".txt": extract_plain_text,
    ".md": extract_plain_text,
}


def extract_text(filename: str, content: bytes) -> str:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    extractor = EXTRACTORS.get(ext)
    if not extractor:
        raise ValueError(f"Formato no soportado: '{ext}'. Soportados: {', '.join(EXTRACTORS)}")
    return extractor(content)
