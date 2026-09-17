"""Coach-uploaded match and training videos with explanations."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlmodel import Session, select
from ..auth import Principal, get_current_principal, require_admin
from ..database import get_session
from ..config import get_settings
from ..models import Event, EventVideo
from ..schemas import EventVideoRead

router = APIRouter(prefix="/event-videos", tags=["event-videos"])

@router.get("/event/{event_id}", response_model=list[EventVideoRead])
def list_event_videos(event_id: int, _: Principal = Depends(get_current_principal), session: Session = Depends(get_session)) -> list[EventVideo]:
    return list(session.exec(select(EventVideo).where(EventVideo.event_id == event_id).order_by(EventVideo.created_at)))

@router.post("", response_model=EventVideoRead, status_code=status.HTTP_201_CREATED)
async def upload_event_video(event_id: int = Form(...), url: str = Form(default=""), comment: str = Form(default=""), video: Optional[UploadFile] = File(default=None), _: Principal = Depends(require_admin), session: Session = Depends(get_session)) -> EventVideo:
    if session.get(Event, event_id) is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if url.strip():
        if not url.startswith(("https://", "http://")):
            raise HTTPException(status_code=400, detail="Video URL must start with http:// or https://")
        filename = url.strip()
    elif video and video.filename:
        suffix = Path(video.filename).suffix.lower()
        if suffix not in {".mp4", ".webm", ".mov"}:
            raise HTTPException(status_code=400, detail="Only MP4, WebM or MOV videos are allowed")
        video_dir = get_settings().video_dir
        video_dir.mkdir(parents=True, exist_ok=True)
        filename = f"event-{uuid4().hex}{suffix}"
        with (video_dir / filename).open("xb") as output:
            while chunk := await video.read(1024 * 1024):
                output.write(chunk)
        await video.close()
    else:
        raise HTTPException(status_code=400, detail="Provide a video URL or upload a file")
    row = EventVideo(event_id=event_id, filename=filename, comment=comment.strip() or None)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
