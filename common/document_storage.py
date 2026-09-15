"""Original document bytes shared by all ingestion entry points.

Only relative, generated keys are persisted. Temporary writes are atomically
published after fsync; cleanup only concerns this operation's temporary file.
"""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import tempfile
import zipfile

from werkzeug.utils import secure_filename


ROOT = Path(__file__).resolve().parents[1] / "data" / "documents"
MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
}


def safe_name(filename):
    if not filename or "/" in filename or "\\" in filename or "\x00" in filename:
        raise ValueError("nombre de archivo no permitido")
    name = secure_filename(filename)
    if not name or name in {".", ".."}:
        raise ValueError("nombre de archivo no permitido")
    return name


def path_for(key):
    root = ROOT.resolve()
    path = (root / key).resolve()
    if Path(key).is_absolute() or root not in path.parents:
        raise ValueError("clave de almacenamiento inválida")
    return path


@contextmanager
def prepare(file, *, thesis_formats=False):
    name = safe_name(file.filename)
    suffix = Path(name).suffix.lower()
    if thesis_formats and suffix not in MIME_TYPES:
        raise ValueError("formato no permitido: PDF, DOCX, XLSX o CSV")
    if thesis_formats and file.mimetype not in {
        MIME_TYPES[suffix], "application/octet-stream", "",
        *( ["text/plain", "application/vnd.ms-excel"] if suffix == ".csv" else [] ),
    }:
        raise ValueError("tipo MIME incompatible con la extensión")
    limit = int(os.environ.get("THESIS_MAX_FILE_MB", "50")) * 1024 * 1024
    if limit <= 0:
        raise ValueError("THESIS_MAX_FILE_MB debe ser positivo")
    ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, dir=ROOT) as stream:
        digest = hashlib.sha256()
        size = 0
        while True:
            block = file.stream.read(64 * 1024)
            if not block:
                break
            size += len(block)
            if size > limit:
                raise ValueError("archivo superior al límite permitido")
            digest.update(block)
            stream.write(block)
        if not size:
            raise ValueError("archivo vacío")
        stream.seek(0)
        if thesis_formats:
            _validate_signature(stream, suffix)
        stream.seek(0)
        yield name, file.mimetype or MIME_TYPES.get(suffix, "application/octet-stream"), digest.hexdigest(), stream


def _validate_signature(stream, suffix):
    prefix = stream.read(8)
    stream.seek(0)
    if suffix == ".pdf" and not prefix.startswith(b"%PDF-"):
        raise ValueError("firma PDF inválida")
    if suffix in {".docx", ".xlsx"}:
        try:
            with zipfile.ZipFile(stream) as archive:
                members = archive.infolist()
                if len(members) > 10000 or sum(m.file_size for m in members) > 200 * 1024 * 1024:
                    raise ValueError("documento comprimido demasiado grande")
                required = "word/document.xml" if suffix == ".docx" else "xl/workbook.xml"
                if required not in archive.namelist() or "[Content_Types].xml" not in archive.namelist():
                    raise ValueError("contenido incompatible con el formato Office")
        except zipfile.BadZipFile as exc:
            raise ValueError("archivo Office inválido") from exc
    if suffix == ".csv":
        import codecs
        decoder = codecs.getincrementaldecoder("utf-8-sig")()
        while True:
            block = stream.read(64 * 1024)
            if not block:
                decoder.decode(b"", final=True)
                break
            if b"\x00" in block:
                raise ValueError("CSV contiene datos binarios")
            decoder.decode(block)


def save(project_id, content_hash, stream):
    key = f"{hashlib.sha256(project_id.encode()).hexdigest()}/{content_hash}.original"
    target = path_for(key)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return key
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".writing-", delete=False) as output:
            temporary = Path(output.name)
            stream.seek(0)
            while True:
                block = stream.read(64 * 1024)
                if not block:
                    break
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return key
