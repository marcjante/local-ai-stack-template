from pathlib import Path

import pytest

from sqlmodel import SQLModel, Session, select

from backend.app.database import build_engine
from backend.app.models import Standing
from integrations.local_ai_stack.sync_fecapa import (
    extract_acta_links,
    fetch_acta_links,
    parse_standings_html,
    upsert_standings,
)


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


def test_fetch_acta_links_uses_the_competition_page(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'<a href="/acta/77">Acta</a>'

    monkeypatch.setattr("integrations.local_ai_stack.sync_fecapa.urlopen", lambda *_args, **_kwargs: Response())

    assert fetch_acta_links("https://fecapa.example/league/4786") == [
        "https://fecapa.example/acta/77"
    ]


def test_upsert_standings_is_idempotent(tmp_path) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'fecapa.db'}")
    SQLModel.metadata.create_all(engine)
    rows = parse_standings_html(FIXTURE.read_text())

    with Session(engine) as session:
        assert upsert_standings(rows, session) == 2
        assert upsert_standings(rows, session) == 2
        saved = session.exec(select(Standing)).all()

    assert len(saved) == 2
