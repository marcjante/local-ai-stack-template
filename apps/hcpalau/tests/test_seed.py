from sqlmodel import Session, SQLModel, select

from backend.app.database import build_engine
from backend.app.models import ExerciseAssignment, Player
from backend.seed import populate


def test_seed_is_repeatable_and_creates_demo_data() -> None:
    engine = build_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        first = populate(session)
        second = populate(session)
        players = session.exec(select(Player)).all()
        assignments = session.exec(select(ExerciseAssignment)).all()

    assert first["players"] == 6
    assert first["events_created"] == 7
    assert first["exercises_created"] == 21
    assert second["events_created"] == 0
    assert second["exercises_created"] == 0
    assert len(players) == 6
    assert len(assignments) == 3
