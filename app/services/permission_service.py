from sqlalchemy.orm import Session
from app.models import permission as models_permission
from app.schemas import permission as schemas_permission

def get_permission(db: Session, permission_id: int):
    return db.query(models_permission.Permission).filter(models_permission.Permission.id == permission_id).first()

def get_permission_by_name(db: Session, name: str):
    return db.query(models_permission.Permission).filter(models_permission.Permission.name == name).first()

def get_permissions(db: Session, skip: int = 0, limit: int = 500):
    return db.query(models_permission.Permission).offset(skip).limit(limit).all()

def create_permission(db: Session, permission: schemas_permission.PermissionCreate):
    db_permission = models_permission.Permission(
        name=permission.name,
        description=permission.description
    )
    db.add(db_permission)
    db.commit()
    db.refresh(db_permission)
    return db_permission
