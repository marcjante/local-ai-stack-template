"""Populate a small, repeatable local demo dataset.

Run with ``python -m backend.seed`` from ``apps/hcpalau``. The command only
allows SQLite by default, so it cannot accidentally seed a managed database.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, SQLModel, select

from .app.config import get_settings
from .app.database import build_engine
from .app.models import Event, Exercise, ExerciseAssignment, Goal, Player, Routine, RoutineExercise, Standing


PLAYERS = (
    ("biel", "Biel", "biel-demo-token-2026"),
    ("pau", "Pau", "pau-demo-token-2026"),
    ("arnau", "Arnau", "arnau-demo-token-2026"),
    ("marti", "Martí", "marti-demo-token-2026"),
    ("pol", "Pol", "pol-demo-token-2026"),
    ("nil", "Nil", "nil-demo-token-2026"),
)
EXERCISES = (
    "Frenada en paral·lel", "Creuats endavant", "Creuats enrere",
    "Canvi de sentit", "Conducció de bola", "Passada de revés",
    "Passada de drive", "Control orientat", "Finalització de cullera",
    "Finalització de pala", "1 contra 1", "Defensa en línia",
    "Pressió després de pèrdua", "Sortida de zona", "Transició ràpida",
    "Circuit de velocitat", "Equilibri i coordinació", "Potència de cames",
    "Mobilitat de maluc", "Recuperació activa", "Visualització de partit",
)


def _player(session: Session, slug: str, name: str, token: str) -> Player:
    player = session.exec(select(Player).where(Player.slug == slug)).first()
    if player is None:
        player = Player(slug=slug, name=name, access_token=token)
        session.add(player)
        session.flush()
    return player


def populate(session: Session) -> dict[str, int]:
    players = [_player(session, *data) for data in PLAYERS]
    existing_events = set(session.exec(select(Event.title)).all())
    today = datetime.now(timezone.utc).replace(hour=18, minute=0, second=0, microsecond=0)
    events_created = 0
    for offset, (title, event_type) in enumerate(
        (("Entrenament d'equip", "training"), ("Partit de lliga", "match"),
         ("Entrenament tècnic", "training"), ("Partit amistós", "match"),
         ("Entrenament tàctic", "training"), ("Partit de lliga", "match"),
         ("Reunió d'equip", "meeting")),
    ):
        unique_title = f"{title} · Demo {offset + 1}"
        if unique_title not in existing_events:
            session.add(Event(title=unique_title, event_type=event_type, starts_at=today + timedelta(days=offset * 3), location="Pavelló HC Palau"))
            events_created += 1

    exercises_created = 0
    exercise_rows: list[Exercise] = []
    for title in EXERCISES:
        exercise = session.exec(select(Exercise).where(Exercise.title == title)).first()
        if exercise is None:
            exercise = Exercise(title=title, description="Exercici de catàleg demo")
            session.add(exercise)
            session.flush()
            exercises_created += 1
        exercise_rows.append(exercise)

    biel = players[0]
    goal = session.exec(select(Goal).where(Goal.player_id == biel.id, Goal.title == "Millorar la presa de decisions")).first()
    if goal is None:
        session.add(Goal(player_id=biel.id, title="Millorar la presa de decisions", description="Escollir la millor línia després de recuperar la bola."))
    routine = session.exec(select(Routine).where(Routine.player_id == biel.id, Routine.title == "Rutina demo de Biel")).first()
    if routine is None:
        routine = Routine(player_id=biel.id, title="Rutina demo de Biel")
        session.add(routine)
        session.flush()
        for position, exercise in enumerate(exercise_rows[:3], start=1):
            session.add(RoutineExercise(routine_id=routine.id, exercise_id=exercise.id, position=position, target_repetitions=2))
    for exercise in exercise_rows[:3]:
        assigned = session.exec(select(ExerciseAssignment).where(ExerciseAssignment.player_id == biel.id, ExerciseAssignment.exercise_id == exercise.id)).first()
        if assigned is None:
            session.add(ExerciseAssignment(player_id=biel.id, exercise_id=exercise.id))

    standings = (("HC Palau", 1, 18), ("CP Vic", 2, 15), ("FC Barcelona", 3, 12), ("CH Mataró", 4, 9), ("CP Voltregà", 5, 6), ("Igualada HC", 6, 3))
    standings_created = 0
    for team, position, points in standings:
        row = session.exec(select(Standing).where(Standing.season == "2026-27", Standing.team == team)).first()
        if row is None:
            session.add(Standing(season="2026-27", team=team, position=position, played=6, won=points // 3, points=points, goals_for=20 - position, goals_against=position * 2))
            standings_created += 1
    session.commit()
    return {"players": len(players), "events_created": events_created, "exercises_created": exercises_created, "standings_created": standings_created}


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the local HC Palau demo dataset")
    parser.add_argument("--allow-non-sqlite", action="store_true", help="allow seeding a non-SQLite DATABASE_URL")
    args = parser.parse_args()
    settings = get_settings()
    if not args.allow_non_sqlite and not settings.database_url.startswith("sqlite"):
        raise SystemExit("Refusing to seed a non-SQLite database; pass --allow-non-sqlite explicitly")
    engine = build_engine(settings.database_url)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        summary = populate(session)
    print("HC Palau demo seeded:", summary)
    print("Admin URL: http://127.0.0.1:8000/app/?token=dev-admin-token")
    print("Biel URL:  http://127.0.0.1:8000/app/?jugador=biel&token=biel-demo-token-2026")


if __name__ == "__main__":
    main()
