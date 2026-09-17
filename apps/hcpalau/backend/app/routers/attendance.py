"""Per-player attendance with server-side ownership checks."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..auth import Principal, get_current_principal, require_player_access
from ..database import get_session
from ..models import Attendance, Event, Player, utc_now
from ..schemas import AttendanceRead, AttendanceUpdate


router = APIRouter(prefix="/attendance", tags=["attendance"])


@router.get("/{player_id}", response_model=list[AttendanceRead])
def list_attendance(
    player_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> list[Attendance]:
    require_player_access(player_id, principal)
    if session.get(Player, player_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    statement = (
        select(Attendance)
        .where(Attendance.player_id == player_id)
        .order_by(Attendance.event_id)
    )
    return list(session.exec(statement))


@router.patch("/{event_id}/{player_id}", response_model=AttendanceRead)
def set_attendance(
    event_id: int,
    player_id: int,
    body: AttendanceUpdate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> Attendance:
    require_player_access(player_id, principal)
    if session.get(Player, player_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    if session.get(Event, event_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    attendance = session.exec(
        select(Attendance).where(
            Attendance.event_id == event_id,
            Attendance.player_id == player_id,
        )
    ).first()
    if attendance is None:
        attendance = Attendance(
            event_id=event_id,
            player_id=player_id,
            attending=body.attending,
            absence_reason=body.absence_reason,
        )
    else:
        attendance.attending = body.attending
        attendance.absence_reason = body.absence_reason
        attendance.updated_at = utc_now()

    session.add(attendance)
    session.commit()
    session.refresh(attendance)
    return attendance
