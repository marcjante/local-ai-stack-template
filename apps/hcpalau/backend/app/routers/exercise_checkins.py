"""Daily yes/no completion for home strength and stretching work."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..auth import Principal, get_current_principal, require_player_access
from ..database import get_session
from ..models import Exercise, ExerciseCheckin, Player, utc_now
from ..schemas import ExerciseCheckinRead, ExerciseCheckinUpdate

router = APIRouter(prefix="/exercise-checkins", tags=["exercise-checkins"])


@router.get("/player/{player_id}", response_model=list[ExerciseCheckinRead])
def list_checkins(player_id: int, _: Principal = Depends(get_current_principal), session: Session = Depends(get_session)) -> list[ExerciseCheckin]:
    require_player_access(player_id, _)
    return list(session.exec(select(ExerciseCheckin).where(ExerciseCheckin.player_id == player_id).order_by(ExerciseCheckin.activity_date)))


@router.patch("/{player_id}/{exercise_id}", response_model=ExerciseCheckinRead)
def set_checkin(player_id: int, exercise_id: int, body: ExerciseCheckinUpdate, principal: Principal = Depends(get_current_principal), session: Session = Depends(get_session)) -> ExerciseCheckin:
    require_player_access(player_id, principal)
    if session.get(Player, player_id) is None or session.get(Exercise, exercise_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player or exercise not found")
    activity_date = body.activity_date or date.today()
    checkin = session.exec(select(ExerciseCheckin).where(ExerciseCheckin.player_id == player_id, ExerciseCheckin.exercise_id == exercise_id, ExerciseCheckin.activity_date == activity_date)).first()
    if checkin is None:
        checkin = ExerciseCheckin(player_id=player_id, exercise_id=exercise_id, activity_date=activity_date, completed=body.completed)
    else:
        checkin.completed = body.completed
        checkin.updated_at = utc_now()
    session.add(checkin)
    session.commit()
    session.refresh(checkin)
    return checkin
