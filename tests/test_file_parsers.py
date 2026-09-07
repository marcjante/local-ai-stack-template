"""test_file_parsers.py — cada formato produce texto correcto y con significado."""

import pytest

from rag.file_parsers import extract_text


def test_txt():
    assert extract_text("a.txt", b"hola mundo") == "hola mundo"


def test_md():
    assert "titulo" in extract_text("a.md", b"# titulo\ncontenido").lower()


def test_csv_becomes_readable_lines():
    content = b"nombre,edad\nAna,30\nLuis,25"
    text = extract_text("a.csv", content)
    assert "nombre: Ana" in text
    assert "edad: 30" in text


def test_json_is_flattened():
    content = b'{"deporte": "futbol", "equipo": {"nombre": "Real Madrid"}}'
    text = extract_text("a.json", content)
    assert "deporte: futbol" in text
    assert "equipo.nombre: Real Madrid" in text


def test_html_strips_script_style_and_title():
    content = b"<html><head><title>fuera</title><style>a{}</style></head><body><p>dentro</p><script>malo()</script></body></html>"
    text = extract_text("a.html", content)
    assert "dentro" in text
    assert "fuera" not in text
    assert "malo" not in text


def test_unsupported_format_raises():
    with pytest.raises(ValueError):
        extract_text("a.xyz", b"contenido")
