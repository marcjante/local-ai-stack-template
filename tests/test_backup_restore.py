"""
test_backup_restore.py

Backup/restore GLOBAL (toda la instalación, vía pg_dump), probado de
forma destructiva: crear algo, borrarlo, restaurar, confirmar que
vuelve. Necesita pg_dump/psql instalados (los mismos que usa la
plantilla en producción).
"""

import shutil

import pytest

from common.backup import export_backup, import_backup
from db.db import get_conn, create_collection, get_project


pytestmark = pytest.mark.skipif(
    shutil.which("pg_dump") is None or shutil.which("psql") is None,
    reason="pg_dump/psql no disponibles en este entorno",
)


class _FakeFileStorage:
    def __init__(self, path):
        self._path = path

    def save(self, dest):
        shutil.copy(self._path, dest)


def test_backup_export_then_restore_brings_back_deleted_data(project_id, tmp_path):
    from pathlib import Path
    create_collection("backup-test-col", "Backup Test", project_id=project_id)

    yaml_path = tmp_path / "services.yaml"
    yaml_path.write_text("services: []\n")

    zip_path = export_backup(yaml_path, {"collections": 1})
    assert zip_path.exists()

    # Borrar la colección para simular "algo se rompió"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM collections WHERE project_id = %s AND id = %s",
                     (project_id, "backup-test-col"))

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM collections WHERE project_id = %s AND id = %s",
                     (project_id, "backup-test-col"))
        assert cur.fetchone()[0] == 0

    # Restaurar
    result = import_backup(_FakeFileStorage(zip_path), restore_services_yaml=False, services_yaml_path=yaml_path)
    assert "manifest" in result

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM collections WHERE project_id = %s AND id = %s",
                     (project_id, "backup-test-col"))
        assert cur.fetchone()[0] == 1, "La colección borrada debería haber vuelto tras restaurar"
