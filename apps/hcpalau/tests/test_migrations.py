from __future__ import annotations

import os
import subprocess
import sys


def _run_alembic(database_url: str, *arguments: str) -> None:
    environment = os.environ.copy()
    environment["HCPALAU_DATABASE_URL"] = database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode == 0, result.stderr


def test_initial_migration_can_upgrade_and_downgrade(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"

    _run_alembic(database_url, "upgrade", "head")
    _run_alembic(database_url, "downgrade", "base")

