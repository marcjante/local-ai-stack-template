"""Notification contract placeholder until the club selects a provider."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth import Principal, require_admin


router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("/send/{player_id}/{event_id}", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def send_notification(
    player_id: int,
    event_id: int,
    _: Principal = Depends(require_admin),
) -> None:
    """Keep the contract explicit without pretending a message was delivered."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "code": "provider_not_configured",
            "message": "Notification provider is not configured",
            "player_id": player_id,
            "event_id": event_id,
        },
    )
