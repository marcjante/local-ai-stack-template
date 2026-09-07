"""
file_parsers.py

Convierte cada formato soportado a texto plano, que es lo único que
necesita el resto del pipeline de RAG (chunking, embeddings...). Añadir
un formato nuevo es añadir una función aquí y una entrada en
EXTRACTORS — no hace falta tocar nada más del pipeline.
"""

import csv
import io
import json

from pypdf import PdfReader
from docx import Document as DocxDocument
from bs4 import BeautifulSoup


def extract_pdf(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_docx(content: bytes) -> str:
    doc = DocxDocument(io.BytesIO(content))
    return "\n".join(p.text for p in doc.paragraphs)


def extract_plain_text(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


def extract_csv(content: bytes) -> str:
    """
    Cada fila se convierte en una línea "columna: valor, columna: valor"
    en vez de volcar el CSV tal cual — así el chunking/embeddings trabaja
    sobre texto con significado, no sobre comas sueltas.
    """
    text = content.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    lines = []
    for row in reader:
        lines.append(", ".join(f"{k}: {v}" for k, v in row.items() if k))
    return "\n".join(lines)


def extract_json(content: bytes) -> str:
    """
    Aplana el JSON a líneas "ruta.de.claves: valor" — legible para
    embeddings de texto, a diferencia del JSON crudo con llaves y comas.
    """
    data = json.loads(content.decode("utf-8", errors="replace"))
    lines = []

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        else:
            lines.append(f"{path}: {node}")

    walk(data)
    return "\n".join(lines)


def extract_html(content: bytes) -> str:
    """Texto visible de la página, sin etiquetas, scripts/estilos, ni <title>/<head>."""
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "title", "head"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


EXTRACTORS = {
    ".pdf": extract_pdf,
    ".docx": extract_docx,
    ".txt": extract_plain_text,
    ".md": extract_plain_text,
    ".csv": extract_csv,
    ".json": extract_json,
    ".html": extract_html,
    ".htm": extract_html,
}


def extract_text(filename: str, content: bytes) -> str:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    extractor = EXTRACTORS.get(ext)
    if not extractor:
        raise ValueError(f"Formato no soportado: '{ext}'. Soportados: {', '.join(EXTRACTORS)}")
    return extractor(content)
