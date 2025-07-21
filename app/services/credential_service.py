from sqlalchemy.orm import Session
from app.models import credential as models_credential
from app.schemas import credential as schemas_credential

def create_credential(db: Session, credential: schemas_credential.CredentialCreate, company_id: int):
    db_credential = models_credential.Credential(provider_name=credential.provider_name, api_key=credential.api_key, company_id=company_id)
    db.add(db_credential)
    db.commit()
    db.refresh(db_credential)
    return db_credential

def get_credential(db: Session, credential_id: int, company_id: int):
    return db.query(models_credential.Credential).filter(models_credential.Credential.id == credential_id, models_credential.Credential.company_id == company_id).first()

def get_credential_by_provider_name(db: Session, provider_name: str, company_id: int):
    return db.query(models_credential.Credential).filter(models_credential.Credential.provider_name == provider_name, models_credential.Credential.company_id == company_id).first()

def get_credentials(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_credential.Credential).filter(models_credential.Credential.company_id == company_id).offset(skip).limit(limit).all()

def update_credential(db: Session, credential_id: int, credential: schemas_credential.CredentialUpdate, company_id: int):
    db_credential = db.query(models_credential.Credential).filter(models_credential.Credential.id == credential_id, models_credential.Credential.company_id == company_id).first()
    if db_credential:
        for key, value in credential.dict(exclude_unset=True).items():
            setattr(db_credential, key, value)
        db.commit()
        db.refresh(db_credential)
    return db_credential

def delete_credential(db: Session, credential_id: int, company_id: int):
    db_credential = db.query(models_credential.Credential).filter(models_credential.Credential.id == credential_id, models_credential.Credential.company_id == company_id).first()
    if db_credential:
        db.delete(db_credential)
        db.commit()
    return db_credential
