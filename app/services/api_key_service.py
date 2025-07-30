from sqlalchemy.orm import Session
from app.models.api_key import ApiKey
from app.schemas.api_key import ApiKeyCreate
import secrets

def create_api_key(db: Session, api_key: ApiKeyCreate, company_id: int) -> ApiKey:
    db_api_key = ApiKey(
        name=api_key.name,
        key=secrets.token_urlsafe(32),
        company_id=company_id
    )
    db.add(db_api_key)
    db.commit()
    db.refresh(db_api_key)
    return db_api_key

def get_api_key_by_key(db: Session, key: str) -> ApiKey | None:
    return db.query(ApiKey).filter(ApiKey.key == key).first()

def get_api_keys_by_company(db: Session, company_id: int) -> list[ApiKey]:
    return db.query(ApiKey).filter(ApiKey.company_id == company_id).all()

def delete_api_key(db: Session, api_key_id: int):
    db_api_key = db.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if db_api_key:
        db.delete(db_api_key)
        db.commit()
    return db_api_key
