
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import List

from app.schemas import comment as schemas_comment
from app.services import comment_service
from app.core.dependencies import get_db, get_current_active_user
from app.models import user as models_user

router = APIRouter()

@router.post("/", response_model=schemas_comment.Comment)
def create_comment(
    comment: schemas_comment.CommentCreate,
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
):
    return comment_service.create_comment(db, comment, workflow_id, current_user.id)

@router.get("/", response_model=List[schemas_comment.Comment])
def get_comments(
    workflow_id: int,
    db: Session = Depends(get_db),
):
    return comment_service.get_comments_by_workflow(db, workflow_id)

@router.websocket("/ws/{workflow_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    workflow_id: int,
    db: Session = Depends(get_db),
):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            # Here you would handle real-time comment creation and broadcasting
            # For simplicity, we will just broadcast the message to all clients
            await websocket.send_text(f"Message text was: {data}")
    except WebSocketDisconnect:
        pass
