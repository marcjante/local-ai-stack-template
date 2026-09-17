"""Team events, readable by every authenticated active account."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..auth import Principal, get_current_principal, require_admin
from ..database import get_session
from ..models import Event
from ..schemas import EventCreate, EventRead, EventTitleUpdate


router = APIRouter(prefix="/events", tags=["events"])


@router.post("", response_model=EventRead, status_code=status.HTTP_201_CREATED)
def create_event(
    body: EventCreate,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Event:
    event = Event.model_validate(body)
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


@router.get("", response_model=list[EventRead])
def list_events(
    _: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> list[Event]:
    return list(session.exec(select(Event).order_by(Event.starts_at)))


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
