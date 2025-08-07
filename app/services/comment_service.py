
from sqlalchemy.orm import Session, joinedload
from app.models import comment as models_comment, user as models_user
from app.schemas import comment as schemas_comment

def create_comment(db: Session, comment: schemas_comment.CommentCreate, workflow_id: int, user_id: int):
    db_comment = models_comment.Comment(
        **comment.dict(),
        workflow_id=workflow_id,
        user_id=user_id,
    )
    db.add(db_comment)
    db.commit()
    db.refresh(db_comment)
    return db_comment

def get_comments_by_workflow(db: Session, workflow_id: int):
    return db.query(models_comment.Comment).options(joinedload(models_comment.Comment.user)).filter(models_comment.Comment.workflow_id == workflow_id).all()
