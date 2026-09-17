from pathlib import Path

import pytest

from integrations.local_ai_stack.sync_fecapa import extract_acta_links, parse_standings_html


FIXTURE = Path(__file__).parent / "fixtures" / "fecapa_infantil_or9.html"


def test_parse_infantil_or9_standings() -> None:
    rows = parse_standings_html(FIXTURE.read_text())

    palau = next(row for row in rows if row.team == "GENERALI HC PALAU D")
    assert palau.position == 2
    assert palau.played == 12
    assert palau.points == 22


def test_parse_standings_requires_the_requested_team() -> None:
    with pytest.raises(ValueError, match="NOT FOUND"):
        parse_standings_html(FIXTURE.read_text(), team_name="NOT FOUND")


def test_acta_links_are_discovered_only_when_published() -> None:
    links = extract_acta_links(FIXTURE.read_text(), base_url="https://fecapa.example/league/4786")

    assert links == ["https://fecapa.example/acta/12345"]
    assert extract_acta_links("<p>Partit encara no disputat</p>") == []
