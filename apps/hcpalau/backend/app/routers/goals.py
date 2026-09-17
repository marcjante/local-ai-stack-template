"""Individually assigned player goals."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..auth import Principal, get_current_principal, require_admin, require_player_access
from ..database import get_session
from ..models import Goal, Player, utc_now
from ..schemas import GoalCreate, GoalDoneUpdate, GoalRead


router = APIRouter(prefix="/goals", tags=["goals"])


@router.post("", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
def create_goal(
    body: GoalCreate,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Goal:
    if session.get(Player, body.player_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    goal = Goal.model_validate(body)
    session.add(goal)
    session.commit()
    session.refresh(goal)
    return goal


@router.get("/player/{player_id}", response_model=list[GoalRead])
def list_player_goals(
    player_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> list[Goal]:
    require_player_access(player_id, principal)
    if session.get(Player, player_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    statement = select(Goal).where(Goal.player_id == player_id).order_by(Goal.created_at)
    return list(session.exec(statement))


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(
    goal_id: int,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> None:
    goal = session.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    session.delete(goal)
    session.commit()


@router.patch("/{goal_id}/done", response_model=GoalRead)
def update_goal_done(
    goal_id: int,
    body: GoalDoneUpdate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> Goal:
    goal = session.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    require_player_access(goal.player_id, principal)

    if principal.role == "player" and goal.done and not body.done:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Players cannot reopen completed goals",
        )

    if body.done != goal.done:
        goal.done = body.done
        goal.done_at = utc_now() if body.done else None
        session.add(goal)
        session.commit()
        session.refresh(goal)
    return goal
