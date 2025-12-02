from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models import credential as models_credential
from app.schemas import credential as schemas_credential
from app.services.vault_service import vault_service

def create_credential(db: Session, credential: schemas_credential.CredentialCreate, company_id: int):
    encrypted_creds = vault_service.encrypt(credential.credentials)
    db_credential = models_credential.Credential(
        name=credential.name,
        service=credential.service.lower(),  # Normalize service name to lowercase
        encrypted_credentials=encrypted_creds,
        company_id=company_id
    )
    db.add(db_credential)
    db.commit()
    db.refresh(db_credential)
    return db_credential

def get_credential(db: Session, credential_id: int, company_id: int):
    return db.query(models_credential.Credential).filter(
        models_credential.Credential.id == credential_id, 
        models_credential.Credential.company_id == company_id
    ).first()

def get_decrypted_credential(db: Session, credential_id: int, company_id: int) -> str:
    """
    Retrieves and decrypts a credential. This should only be called by services
    that need to use the credential immediately.
    """
    db_credential = get_credential(db, credential_id, company_id)
    if db_credential and db_credential.encrypted_credentials:
        return vault_service.decrypt(db_credential.encrypted_credentials)
    return None

def get_credential_by_service_name(db: Session, service_name: str, company_id: int):
    # Case-insensitive service name comparison
    return db.query(models_credential.Credential).filter(
        func.lower(models_credential.Credential.service) == service_name.lower(),
        models_credential.Credential.company_id == company_id
    ).first()

def get_credentials(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_credential.Credential).filter(
        models_credential.Credential.company_id == company_id
    ).offset(skip).limit(limit).all()

def update_credential(db: Session, credential_id: int, credential: schemas_credential.CredentialUpdate, company_id: int):
    db_credential = get_credential(db, credential_id, company_id)
    if db_credential:
        update_data = credential.model_dump(exclude_unset=True)
        if 'credentials' in update_data:
            db_credential.encrypted_credentials = vault_service.encrypt(update_data['credentials'])
            del update_data['credentials'] # Don't try to set this attribute directly

        # Normalize service name to lowercase if being updated
        if 'service' in update_data:
            update_data['service'] = update_data['service'].lower()

        for key, value in update_data.items():
            setattr(db_credential, key, value)
            
        db.commit()
        db.refresh(db_credential)
    return db_credential

def delete_credential(db: Session, credential_id: int, company_id: int):
    db_credential = get_credential(db, credential_id, company_id)
    if db_credential:
        db.delete(db_credential)
        db.commit()
    return db_credential
