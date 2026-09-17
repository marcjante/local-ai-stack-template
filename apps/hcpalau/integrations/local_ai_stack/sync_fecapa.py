"""Parse the public FECAPA competition page for HC Palau Infantil D.

The federation page is rendered as HTML and has no documented API.  This
module intentionally keeps fetching/parsing separate from persistence so a
markup change cannot affect the application API.  It currently imports the
standings table; match-sheet/player-stat imports remain pending a stable acta
HTML sample.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from sqlmodel import Session, select

from backend.app.models import Standing as StandingModel, utc_now


SOURCE_URL = "https://www.hoqueipatins.fecapa.cat/league/4786"
DEFAULT_GROUP = "INFANTIL OR 9"
DEFAULT_TEAM = "GENERALI HC PALAU D"


@dataclass(frozen=True)
class Standing:
    position: int
    team: str
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    points: int


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "table" and self._table is None:
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None


class _ActaLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "a":
            href = dict(attrs).get("href", "")
            if "acta" in href.lower():
                self.links.append(href)


def extract_acta_links(html: str, *, base_url: str = SOURCE_URL) -> list[str]:
    """Return published acta links; upcoming matches may have none."""
    parser = _ActaLinkParser()
    parser.feed(html)
    return list(dict.fromkeys(urljoin(base_url, link) for link in parser.links))


def _number(value: str) -> int:
    match = re.search(r"-?\d+", value.replace(".", ""))
    if not match:
        raise ValueError(f"Expected a number, got {value!r}")
    return int(match.group())


def parse_standings_html(
    html: str,
    *,
    group_name: str = DEFAULT_GROUP,
    team_name: str = DEFAULT_TEAM,
) -> list[Standing]:
    """Extract the standings table containing the requested team.

    FECAPA has historically emitted one table per competition group.  We use
    the row shape rather than CSS classes, which keeps this parser resilient to
    presentation-only changes while still rejecting an unrelated group.
    """
    if " ".join(group_name.upper().split()) not in " ".join(html.upper().split()):
        raise ValueError(f"Could not find group {group_name!r}")
    parser = _TableParser()
    parser.feed(html)
    normalized_team = " ".join(team_name.upper().split())
    candidates: list[Standing] = []
    for table in parser.tables:
        contains_team = any(
            len(row) > 1 and normalized_team in " ".join(row[1].upper().split())
            for row in table
        )
        if not contains_team:
            continue
        for row in table:
            if len(row) < 9 or not re.fullmatch(r"\d+", row[0].strip()):
                continue
            try:
                candidates.append(
                    Standing(
                        position=_number(row[0]),
                        team=row[1],
                        played=_number(row[2]),
                        won=_number(row[3]),
                        drawn=_number(row[4]),
                        lost=_number(row[5]),
                        goals_for=_number(row[6]),
                        goals_against=_number(row[7]),
                        points=_number(row[9] if len(row) > 9 else row[8]),
                    )
                )
            except ValueError:
                continue
    if not candidates:
        raise ValueError(f"Could not find {team_name!r} in group {group_name!r}")
    return candidates


def fetch_standings(url: str = SOURCE_URL) -> list[Standing]:
    request = Request(url, headers={"User-Agent": "HC-Palau-FECAPA-Sync/1.0"})
    with urlopen(request, timeout=20) as response:
        return parse_standings_html(response.read().decode("utf-8", errors="replace"))


def fetch_acta_links(url: str = SOURCE_URL) -> list[str]:
    request = Request(url, headers={"User-Agent": "HC-Palau-FECAPA-Sync/1.0"})
    with urlopen(request, timeout=20) as response:
        html = response.read().decode("utf-8", errors="replace")
        return extract_acta_links(html, base_url=url)


def upsert_standings(rows: list[Standing], session: Session, *, season: str = "2026-27") -> int:
    """Persist a parsed group idempotently and return the number of rows saved."""
    for row in rows:
        current = session.exec(
            select(StandingModel).where(
                StandingModel.season == season,
                StandingModel.team == row.team,
            )
        ).first()
        if current is None:
            current = StandingModel(season=season, team=row.team)
        current.position = row.position
        current.played = row.played
        current.won = row.won
        current.drawn = row.drawn
        current.lost = row.lost
        current.goals_for = row.goals_for
        current.goals_against = row.goals_against
        current.points = row.points
        current.updated_at = utc_now()
        session.add(current)
    session.commit()
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=SOURCE_URL)
    parser.add_argument("--season", default="2026-27")
    parser.add_argument("--persist", action="store_true", help="persist standings in the configured database")
    parser.add_argument(
        "--actas-only",
        action="store_true",
        help="print published acta links instead of parsing standings",
    )
    args = parser.parse_args()
    if args.actas_only:
        payload = fetch_acta_links(args.url)
    else:
        rows = fetch_standings(args.url)
        if args.persist:
            from backend.app.database import engine

            with Session(engine) as session:
                upsert_standings(rows, session, season=args.season)
        payload = [asdict(row) for row in rows]
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
