from __future__ import annotations

import re
from pathlib import Path

from backend.app.main import app


APP_ROOT = Path(__file__).parents[1]


def test_documented_routes_exist_in_openapi() -> None:
    documented = set(
        re.findall(r"\|\s*`(?:GET|POST|PUT|PATCH|DELETE)`\s*\|\s*`([^`]+)`", (APP_ROOT / "docs" / "api-spec.md").read_text())
    )
    documented = {path.split("?", 1)[0] for path in documented}
    openapi_paths = set(app.openapi()["paths"])

    assert documented <= openapi_paths
