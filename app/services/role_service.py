from sqlalchemy.orm import Session
from app.models import role as models_role, permission as models_permission
from app.schemas import role as schemas_role

def get_role(db: Session, role_id: int, company_id: int):
    return db.query(models_role.Role).filter(models_role.Role.id == role_id, models_role.Role.company_id == company_id).first()

def get_roles(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_role.Role).filter(models_role.Role.company_id == company_id).offset(skip).limit(limit).all()

def create_role(db: Session, role: schemas_role.RoleCreate, company_id: int):
    db_role = models_role.Role(
        name=role.name,
        description=role.description,
        company_id=company_id
    )
    
    if role.permission_ids:
        permissions = db.query(models_permission.Permission).filter(models_permission.Permission.id.in_(role.permission_ids)).all()
        db_role.permissions.extend(permissions)

    db.add(db_role)
    db.commit()
    db.refresh(db_role)
    return db_role

def update_role(db: Session, role_id: int, role: schemas_role.RoleUpdate, company_id: int):
    db_role = get_role(db, role_id, company_id)
    if db_role:
        db_role.name = role.name
        db_role.description = role.description
        
        if role.permission_ids is not None:
            db_role.permissions.clear()
            permissions = db.query(models_permission.Permission).filter(models_permission.Permission.id.in_(role.permission_ids)).all()
            db_role.permissions.extend(permissions)
            
        db.commit()
        db.refresh(db_role)
    return db_role

def delete_role(db: Session, role_id: int, company_id: int):
    db_role = get_role(db, role_id, company_id)
    if db_role:
        db.delete(db_role)
        db.commit()
    return db_role

def assign_permission_to_role(db: Session, role_id: int, permission_id: int, company_id: int):
    role = get_role(db, role_id, company_id)
    permission = db.query(models_permission.Permission).filter(models_permission.Permission.id == permission_id).first()
    
    if role and permission:
        role.permissions.append(permission)
        db.commit()
        db.refresh(role)
    return role

def remove_permission_from_role(db: Session, role_id: int, permission_id: int, company_id: int):
    role = get_role(db, role_id, company_id)
    permission = db.query(models_permission.Permission).filter(models_permission.Permission.id == permission_id).first()

    if role and permission and permission in role.permissions:
        role.permissions.remove(permission)
        db.commit()
        db.refresh(role)
    return role
