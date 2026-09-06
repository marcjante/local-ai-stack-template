"""
backup.py

Exporta e importa un backup completo del proyecto: configuración
(`services.yaml`) + toda la base de datos (tasks, audit_log, rag_chunks,
documents, collections, n8n_integrations...) en un único .zip.

Usa `pg_dump`/`psql` directamente — no reinventa un formato propio de
backup. El .env real NUNCA se incluye (puede tener secretos); solo se
exporta la configuración no sensible.
"""

import json
import os
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from db.db import DB_DSN


def export_backup(services_yaml_path: Path, db_counts: dict) -> Path:
    """
    Genera un .zip con:
      - manifest.json  (fecha, recuento de filas por tabla)
      - services.yaml  (config del stack)
      - db_dump.sql    (pg_dump completo, con --clean --if-exists para
                         que restaurarlo sobrescriba limpiamente las
                         tablas existentes, no las duplique)
    Devuelve la ruta al .zip generado (en un directorio temporal).
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="lastack_backup_"))
    dump_path = tmp_dir / "db_dump.sql"

    result = subprocess.run(
        ["pg_dump", "-d", DB_DSN, "-f", str(dump_path), "--clean", "--if-exists"],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump falló: {result.stderr[-2000:]}")

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "table_counts": db_counts,
    }

    zip_path = tmp_dir / f"local-ai-stack-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        if services_yaml_path.exists():
            zf.write(services_yaml_path, "services.yaml")
        zf.write(dump_path, "db_dump.sql")

    return zip_path


def import_backup(zip_file_storage, restore_services_yaml: bool, services_yaml_path: Path) -> dict:
    """
    Restaura desde un .zip generado por export_backup(). Sobrescribe la
    base de datos actual (por diseño — es lo que significa "restaurar
    un backup"). Si restore_services_yaml es True, también sobrescribe
    config/services.yaml (validado como YAML antes de escribir).
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="lastack_restore_"))
    zip_path = tmp_dir / "uploaded.zip"
    zip_file_storage.save(zip_path)

    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            if "db_dump.sql" not in names:
                raise ValueError("el .zip no contiene db_dump.sql — no parece un backup válido de esta plantilla")
            zf.extractall(tmp_dir)
    except zipfile.BadZipFile:
        raise ValueError("el fichero subido no es un .zip válido")

    manifest = {}
    manifest_path = tmp_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())

    dump_path = tmp_dir / "db_dump.sql"
    result = subprocess.run(
        ["psql", DB_DSN, "-f", str(dump_path)],
        capture_output=True, text=True, timeout=180,
    )
    # psql devuelve 0 aunque algunas sentencias individuales fallen (p.ej.
    # "DROP TABLE IF EXISTS" de algo que no existía) — nos fijamos en
    # errores reales, no en el código de salida a secas.
    real_errors = [line for line in result.stderr.splitlines() if "ERROR" in line and "already exists" not in line]

    restored_yaml = False
    if restore_services_yaml and (tmp_dir / "services.yaml").exists():
        content = (tmp_dir / "services.yaml").read_text()
        import yaml
        parsed = yaml.safe_load(content)
        if isinstance(parsed, dict) and "services" in parsed:
            services_yaml_path.write_text(content)
            restored_yaml = True

    return {
        "manifest": manifest,
        "restored_yaml": restored_yaml,
        "warnings": real_errors[:20],
    }
