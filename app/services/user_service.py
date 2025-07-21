
from sqlalchemy.orm import Session
from app.models import user as models_user
from app.schemas import user as schemas_user
from app.core.security import get_password_hash
from app.services import user_settings_service
from app.schemas import user_settings as schemas_user_settings

def get_user(db: Session, user_id: int):
    return db.query(models_user.User).filter(models_user.User.id == user_id).first()

def get_user_by_email(db: Session, email: str):
    return db.query(models_user.User).filter(models_user.User.email == email).first()

def get_users(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_user.User).filter(models_user.User.company_id == company_id).offset(skip).limit(limit).all()

from app.services import user_settings_service, company_service
from app.schemas import user_settings as schemas_user_settings, company as schemas_company

def create_user(db: Session, user: schemas_user.UserCreate, company_id: int):
    hashed_password = get_password_hash(user.password)

    # Check if this is the first user for the company
    is_first_user = db.query(models_user.User).filter(models_user.User.company_id == company_id).first() is None

    db_user = models_user.User(
        email=user.email,
        hashed_password=hashed_password,
        company_id=company_id,
        first_name=user.first_name,
        last_name=user.last_name,
        phone_number=user.phone_number,
        job_title=user.job_title,
        profile_picture_url=user.profile_picture_url,
        is_active=True, # New users are active by default
        is_admin=is_first_user # First user is admin
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    # Create default settings for the new user, linked to the company
    default_settings = schemas_user_settings.UserSettingsCreate()
    user_settings_service.create_user_settings(db, user_id=db_user.id, company_id=company_id, settings=default_settings)

    return db_user

def update_user(db: Session, db_obj: models_user.User, obj_in: schemas_user.UserUpdate):
    if isinstance(obj_in, dict):
        update_data = obj_in
    else:
        update_data = obj_in.dict(exclude_unset=True)

    if update_data.get("password"):
        hashed_password = get_password_hash(update_data["password"])
        del update_data["password"]
        update_data["hashed_password"] = hashed_password

    for field, value in update_data.items():
        setattr(db_obj, field, value)

    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj
