"""Exercise catalogue, individual assignments and bounded weekly progress."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlmodel import Session, select

from ..auth import Principal, get_current_principal, require_admin, require_player_access
from ..config import get_settings
from ..database import get_session
from ..models import Exercise, ExerciseAssignment, Player
from ..schemas import ExerciseAssignmentRead, ExerciseCreate, ExerciseRead


MAX_VIDEO_BYTES = 30 * 1024 * 1024
ALLOWED_VIDEO_SUFFIXES = {".mp4", ".webm"}
UPLOAD_CHUNK_BYTES = 1024 * 1024

router = APIRouter(prefix="/exercises", tags=["exercises"])


@router.post("", response_model=ExerciseRead, status_code=status.HTTP_201_CREATED)
def create_exercise(
    body: ExerciseCreate,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Exercise:
    exercise = Exercise.model_validate(body)
    session.add(exercise)
    session.commit()
    session.refresh(exercise)
    return exercise


@router.get("", response_model=list[ExerciseRead])
def list_exercises(
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> list[Exercise]:
    return list(session.exec(select(Exercise).order_by(Exercise.title)))


@router.post("/{exercise_id}/video", response_model=ExerciseRead)
async def upload_exercise_video(
    exercise_id: int,
    video: UploadFile = File(...),
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Exercise:
    exercise = session.get(Exercise, exercise_id)
    if exercise is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercise not found")

    suffix = Path(video.filename or "").suffix.lower()
    if suffix not in ALLOWED_VIDEO_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .mp4 and .webm videos are allowed",
        )

    video_dir = get_settings().video_dir
    video_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{suffix}"
    destination = video_dir / filename
    size = 0
    try:
        with destination.open("xb") as output:
            while chunk := await video.read(UPLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > MAX_VIDEO_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Video exceeds the 30 MB limit",
                    )
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await video.close()

    previous_filename = exercise.video_filename
    exercise.video_filename = filename
    session.add(exercise)
    session.commit()
    session.refresh(exercise)
    if previous_filename:
        (video_dir / previous_filename).unlink(missing_ok=True)
    return exercise


@router.post(
    "/{exercise_id}/assign/{player_id}",
    response_model=ExerciseAssignmentRead,
    status_code=status.HTTP_201_CREATED,
)
def assign_exercise(
    exercise_id: int,
    player_id: int,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> ExerciseAssignment:
    if session.get(Exercise, exercise_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercise not found")
    if session.get(Player, player_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    existing = session.exec(
        select(ExerciseAssignment).where(
            ExerciseAssignment.exercise_id == exercise_id,
            ExerciseAssignment.player_id == player_id,
        )
    ).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Exercise already assigned")
    assignment = ExerciseAssignment(exercise_id=exercise_id, player_id=player_id)
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


@router.get("/player/{player_id}", response_model=list[ExerciseAssignmentRead])
def list_player_exercises(
    player_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> list[ExerciseAssignment]:
    require_player_access(player_id, principal)
    statement = (
        select(ExerciseAssignment)
        .where(ExerciseAssignment.player_id == player_id)
        .order_by(ExerciseAssignment.assigned_at)
    )
    return list(session.exec(statement))
