
from sqlalchemy.orm import Session
from app.models import user as models_user
from app.schemas import user as schemas_user
from passlib.context import CryptContext
from app.services import user_settings_service
from app.schemas import user_settings as schemas_user_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_user(db: Session, user_id: int, company_id: int):
    return db.query(models_user.User).filter(models_user.User.id == user_id, models_user.User.company_id == company_id).first()

def get_user_by_email(db: Session, email: str, company_id: int):
    return db.query(models_user.User).filter(models_user.User.email == email, models_user.User.company_id == company_id).first()

def get_users(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_user.User).filter(models_user.User.company_id == company_id).offset(skip).limit(limit).all()

from app.services import user_settings_service, company_service
from app.schemas import user_settings as schemas_user_settings, company as schemas_company

def create_user(db: Session, user: schemas_user.UserCreate, company_id: int):
    hashed_password = pwd_context.hash(user.password)

    db_user = models_user.User(email=user.email, hashed_password=hashed_password, company_id=company_id)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    # Create default settings for the new user, linked to the company
    default_settings = schemas_user_settings.UserSettingsCreate()
    user_settings_service.create_user_settings(db, user_id=db_user.id, company_id=company_id, settings=default_settings)

    return db_user
