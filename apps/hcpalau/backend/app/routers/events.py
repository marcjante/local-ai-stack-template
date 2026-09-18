"""Team events, readable by every authenticated active account."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from ..auth import Principal, get_current_principal, require_admin
from ..database import get_session
from ..models import Attendance, Convocation, Event, EventVideo, MvpRecognition, Reinforcement, Team
from ..schemas import EventCreate, EventRead, EventTeamUpdate, EventTitleUpdate


router = APIRouter(prefix="/events", tags=["events"])


@router.post("", response_model=EventRead, status_code=status.HTTP_201_CREATED)
def create_event(
    body: EventCreate,
    principal: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Event:
    event = Event.model_validate(body)
    if principal.team_id is not None:
        event.team_id = principal.team_id
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


@router.get("", response_model=list[EventRead])
def list_events(
    principal: Principal = Depends(get_current_principal),
    team: Optional[str] = Query(default=None, max_length=64),
    session: Session = Depends(get_session),
) -> list[Event]:
    statement = select(Event).order_by(Event.starts_at)
    team_slug = team
    if principal.role == "admin" and principal.team_id is not None:
        team_slug = session.get(Team, principal.team_id).slug if session.get(Team, principal.team_id) else None
    if team_slug:
        statement = statement.join(Team, Team.id == Event.team_id).where(Team.slug == team_slug)
    return list(session.exec(statement))


@router.patch("/{event_id}", response_model=EventRead)
def rename_event(
    event_id: int,
    body: EventTitleUpdate,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Event:
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    event.title = body.title
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


@router.delete("/team/{team_id}")
def clear_team_events(
    team_id: int,
    principal: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, int]:
    """Remove a team's events and their attendance/video child records."""
    if principal.team_id is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the global administrator can clear a team calendar")
    if session.get(Team, team_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    events = session.exec(select(Event).where(Event.team_id == team_id)).all()
    event_ids = [event.id for event in events]
    for event_id in event_ids:
        for row in session.exec(select(Attendance).where(Attendance.event_id == event_id)).all():
            session.delete(row)
        for row in session.exec(select(Convocation).where(Convocation.event_id == event_id)).all():
            session.delete(row)
        for row in session.exec(select(EventVideo).where(EventVideo.event_id == event_id)).all():
            session.delete(row)
        for row in session.exec(select(MvpRecognition).where(MvpRecognition.event_id == event_id)).all():
            session.delete(row)
        for row in session.exec(select(Reinforcement).where(Reinforcement.event_id == event_id)).all():
            session.delete(row)
    for event in events:
        session.delete(event)
    session.commit()
    return {"events_deleted": len(events), "team_id": team_id}


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: int,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> None:
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    session.delete(event)
    session.commit()


@router.patch("/{event_id}/team", response_model=EventRead)
def assign_event_team(
    event_id: int,
    body: EventTeamUpdate,
    principal: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Event:
    if principal.team_id is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the global administrator can assign event teams")
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    if body.team_id is not None and session.get(Team, body.team_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    event.team_id = body.team_id
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


@router.get("/{event_id}", response_model=EventRead)
def get_event(
    event_id: int,
    _: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> Event:
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return event
