"""test_file_parsers.py — extracción de formatos y procedencia científica."""

import pytest

from rag.file_parsers import (
    extract_text,
    detect_section_heading,
    split_text_by_sections,
)


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
    content = (
        b"<html><head><title>fuera</title><style>a{}</style></head>"
        b"<body><p>dentro</p><script>malo()</script></body></html>"
    )
    text = extract_text("a.html", content)
    assert "dentro" in text
    assert "fuera" not in text
    assert "malo" not in text


def test_unsupported_format_raises():
    with pytest.raises(ValueError):
        extract_text("a.xyz", b"contenido")


def test_detects_conservative_scientific_section_headings():
    assert detect_section_heading("Methods") == "Methods"
    assert detect_section_heading("2. METHODS") == "Methods"
    assert detect_section_heading("3.1 Results") == "Results"
    assert detect_section_heading("Discussion") == "Discussion"
    assert detect_section_heading("Conclusions") == "Conclusion"
    assert detect_section_heading("References") == "References"


def test_does_not_invent_section_from_normal_sentence():
    assert detect_section_heading(
        "The results showed a significant improvement."
    ) is None

    assert detect_section_heading(
        "Methods were selected according to previous studies."
    ) is None


def test_splits_multiple_sections_on_same_page():
    text = """Introduction
Background information about the study.

Methods
Patients were recruited prospectively.

Results
Thirty patients completed follow-up.
"""

    blocks, final_section = split_text_by_sections(text)

    assert [b["section"] for b in blocks] == [
        "Introduction",
        "Methods",
        "Results",
    ]

    assert final_section == "Results"
    assert "Patients were recruited" in blocks[1]["text"]
    assert "Thirty patients" in blocks[2]["text"]


def test_section_can_continue_on_next_page():
    page_1 = """Methods
Patients were recruited at two hospitals.
"""

    blocks_1, current_section = split_text_by_sections(page_1)

    assert current_section == "Methods"
    assert blocks_1[0]["section"] == "Methods"

    page_2 = """Follow-up was performed at six months.

Results
The intervention improved the primary outcome.
"""

    blocks_2, current_section = split_text_by_sections(
        page_2,
        initial_section=current_section,
    )

    assert blocks_2[0]["section"] == "Methods"
    assert blocks_2[1]["section"] == "Results"
    assert current_section == "Results"
