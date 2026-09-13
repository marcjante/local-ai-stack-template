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
import re

from pypdf import PdfReader
from docx import Document as DocxDocument
from bs4 import BeautifulSoup


SECTION_ALIASES = {
    "Abstract": {
        "abstract",
        "summary",
        "resumen",
        "resum",
    },
    "Introduction": {
        "introduction",
        "introducción",
        "introduccion",
        "introducció",
        "introduccio",
    },
    "Methods": {
        "methods",
        "method",
        "methodology",
        "materials and methods",
        "patients and methods",
        "subjects and methods",
        "methods and materials",
        "métodos",
        "metodos",
        "metodología",
        "metodologia",
        "materiales y métodos",
        "materiales y metodos",
        "materials i mètodes",
        "materials i metodes",
        "mètodes",
        "metodes",
    },
    "Results": {
        "results",
        "result",
        "resultados",
        "resultats",
    },
    "Discussion": {
        "discussion",
        "discusión",
        "discusion",
        "discussió",
        "discussio",
    },
    "Conclusion": {
        "conclusion",
        "conclusions",
        "conclusión",
        "conclusiones",
        "conclusio",
        "conclusió",
    },
    "References": {
        "references",
        "reference",
        "bibliography",
        "referencias",
        "bibliografía",
        "bibliografia",
        "referències",
        "referencies",
    },
}


def _normalise_section_heading(line: str) -> str:
    """
    Normaliza únicamente posibles encabezados.

    Ejemplos:
        "2. Methods" -> "methods"
        "3.1 RESULTS" -> "results"

    No intenta inferir secciones a partir del contenido.
    """
    heading = line.strip()

    if not heading or len(heading) > 80:
        return ""

    heading = re.sub(
        r"^\s*\d+(?:\.\d+)*[\.\):\-]?\s*",
        "",
        heading,
    )

    heading = heading.strip(" \t\r\n:.-")

    return re.sub(r"\s+", " ", heading).casefold()


def detect_section_heading(line: str):
    """
    Devuelve el nombre canónico de una sección únicamente cuando toda
    la línea coincide con un encabezado conocido.
    """
    candidate = _normalise_section_heading(line)

    if not candidate:
        return None

    for canonical_name, aliases in SECTION_ALIASES.items():
        if candidate in aliases:
            return canonical_name

    return None


def split_text_by_sections(
    text: str,
    initial_section=None,
):
    """
    Divide un texto por encabezados científicos explícitos.

    Devuelve:
        (blocks, final_section)

    `initial_section` permite que una sección iniciada en una página
    continúe correctamente en la siguiente.

    Si no hay encabezados reconocibles, el texto se mantiene intacto.
    """
    lines = text.splitlines()

    blocks = []
    buffer = []
    current_section = initial_section

    def flush():
        nonlocal buffer

        block_text = "\n".join(buffer).strip()

        if block_text:
            blocks.append({
                "text": block_text,
                "section": current_section,
            })

        buffer = []

    for line in lines:
        detected = detect_section_heading(line)

        if detected is not None:
            flush()
            current_section = detected

            # Conservamos el encabezado dentro del bloque para mantener
            # fidelidad textual y contexto durante retrieval.
            buffer.append(line)
            continue

        buffer.append(line)

    flush()

    return blocks, current_section


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


def extract_structured_text(filename: str, content: bytes) -> list:
    """
    Extrae texto conservando metadatos de procedencia cuando el formato
    permite conocerlos.

    PDF:
        un bloque por página, con page_number real (1-based).

    Resto de formatos:
        un único bloque sin número de página.

    extract_text() se mantiene sin cambios para compatibilidad con el
    resto del proyecto.
    """
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in EXTRACTORS:
        raise ValueError(
            f"Formato no soportado: '{ext}'. "
            f"Soportados: {', '.join(EXTRACTORS)}"
        )

    if ext == ".pdf":
        reader = PdfReader(io.BytesIO(content))
        blocks = []
        current_section = None

        for page_number, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""

            if not page_text.strip():
                continue

            page_blocks, current_section = split_text_by_sections(
                page_text,
                initial_section=current_section,
            )

            for block in page_blocks:
                blocks.append({
                    "text": block["text"],
                    "page_number": page_number,
                    "section": block["section"],
                })

        return blocks

    plain_text = EXTRACTORS[ext](content)

    if not plain_text.strip():
        return []

    return [{
        "text": plain_text,
        "page_number": None,
        "section": None,
    }]

