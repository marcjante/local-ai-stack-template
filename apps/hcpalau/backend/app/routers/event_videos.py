"""Coach-uploaded match and training videos with explanations."""
from fastapi import APIRouter, Depends, Form, HTTPException, status
from sqlmodel import Session, select
from ..auth import Principal, get_current_principal, require_admin
from ..database import get_session
from ..models import Event, EventVideo
from ..schemas import EventVideoRead

router = APIRouter(prefix="/event-videos", tags=["event-videos"])

@router.get("/event/{event_id}", response_model=list[EventVideoRead])
def list_event_videos(event_id: int, _: Principal = Depends(get_current_principal), session: Session = Depends(get_session)) -> list[EventVideo]:
    return list(session.exec(select(EventVideo).where(EventVideo.event_id == event_id).order_by(EventVideo.created_at)))

@router.post("", response_model=EventVideoRead, status_code=status.HTTP_201_CREATED)
async def upload_event_video(event_id: int = Form(...), url: str = Form(...), comment: str = Form(default=""), _: Principal = Depends(require_admin), session: Session = Depends(get_session)) -> EventVideo:
    if session.get(Event, event_id) is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if not url.startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="Video URL must start with http:// or https://")
    row = EventVideo(event_id=event_id, filename=url.strip(), comment=comment.strip() or None)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
