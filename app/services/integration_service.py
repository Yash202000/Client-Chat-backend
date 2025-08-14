from sqlalchemy.orm import Session
import json
from typing import List, Dict, Any

from app.models import integration as models_integration
from app.schemas import integration as schemas_integration
from app.services.vault_service import vault_service

def get_integration(db: Session, integration_id: int, company_id: int) -> models_integration.Integration:
    """
    Retrieves a single integration by its ID, ensuring it belongs to the correct company.
    """
    return db.query(models_integration.Integration).filter(
        models_integration.Integration.id == integration_id,
        models_integration.Integration.company_id == company_id
    ).first()

def get_integrations_by_company(db: Session, company_id: int) -> List[models_integration.Integration]:
    """
    Retrieves all integrations for a given company.
    """
    return db.query(models_integration.Integration).filter(models_integration.Integration.company_id == company_id).all()

def create_integration(db: Session, integration: schemas_integration.IntegrationCreate, company_id: int) -> models_integration.Integration:
    """
    Creates a new integration for a company and encrypts its credentials.
    """
    # Convert credentials dict to a JSON string and encrypt it
    credentials_json = json.dumps(integration.credentials)
    encrypted_credentials = vault_service.encrypt(credentials_json)

    db_integration = models_integration.Integration(
        name=integration.name,
        type=integration.type,
        enabled=integration.enabled,
        credentials=encrypted_credentials,
        company_id=company_id
    )
    db.add(db_integration)
    db.commit()
    db.refresh(db_integration)
    return db_integration

def update_integration(db: Session, db_integration: models_integration.Integration, integration_in: schemas_integration.IntegrationUpdate) -> models_integration.Integration:
    """
    Updates an integration's details. If new credentials are provided, they are encrypted.
    """
    update_data = integration_in.dict(exclude_unset=True)
    
    if "credentials" in update_data and update_data["credentials"]:
        credentials_json = json.dumps(update_data["credentials"])
        update_data["credentials"] = vault_service.encrypt(credentials_json)

    for field, value in update_data.items():
        setattr(db_integration, field, value)

    db.add(db_integration)
    db.commit()
    db.refresh(db_integration)
    return db_integration

def delete_integration(db: Session, integration_id: int, company_id: int):
    """
    Deletes an integration.
    """
    db_integration = get_integration(db, integration_id=integration_id, company_id=company_id)
    if db_integration:
        db.delete(db_integration)
        db.commit()
    return db_integration

def get_decrypted_credentials(integration: models_integration.Integration) -> Dict[str, Any]:
    """
    Safely decrypts and parses the credentials JSON for an integration.
    """
    decrypted_json = vault_service.decrypt(integration.credentials)
    return json.loads(decrypted_json)

def get_integration_by_phone_number_id(db: Session, phone_number_id: str) -> models_integration.Integration:
    """
    Finds an active WhatsApp integration by the phone number ID.
    This is a critical function for the webhook to identify the company.
    """
    integrations = db.query(models_integration.Integration).filter(
        models_integration.Integration.type == "whatsapp",
        models_integration.Integration.enabled == True
    ).all()

    for integration in integrations:
        credentials = get_decrypted_credentials(integration)
        if credentials.get("phone_number_id") == phone_number_id:
            return integration
            
    return None

def get_integration_by_page_id(db: Session, page_id: str) -> models_integration.Integration:
    """
    Finds an active Messenger or Instagram integration by the Facebook Page ID.
    """
    integrations = db.query(models_integration.Integration).filter(
        models_integration.Integration.type.in_(["messenger", "instagram"]),
        models_integration.Integration.enabled == True
    ).all()

    for integration in integrations:
        credentials = get_decrypted_credentials(integration)
        if credentials.get("page_id") == page_id:
            return integration
            
    return None

def get_integration_by_telegram_bot_token(db: Session, bot_token: str) -> models_integration.Integration:
    """
    Finds an active Telegram integration by the bot token.
    """
    integrations = db.query(models_integration.Integration).filter(
        models_integration.Integration.type == "telegram",
        models_integration.Integration.enabled == True
    ).all()

    for integration in integrations:
        credentials = get_decrypted_credentials(integration)
        if credentials.get("bot_token") == bot_token:
            return integration
            
    return None

def get_integration_by_linkedin_company_id(db: Session, linkedin_company_id: str) -> models_integration.Integration:
    """
    Finds an active LinkedIn integration by the LinkedIn Company ID.
    """
    integrations = db.query(models_integration.Integration).filter(
        models_integration.Integration.type == "linkedin",
        models_integration.Integration.enabled == True
    ).all()

    for integration in integrations:
        credentials = get_decrypted_credentials(integration)
        if credentials.get("linkedin_company_id") == linkedin_company_id:
            return integration
            
    return None

def get_integration_by_type_and_company(db: Session, integration_type: str, company_id: int) -> models_integration.Integration:
    """
    Finds an active integration by type and company ID.
    """
    return db.query(models_integration.Integration).filter(
        models_integration.Integration.type == integration_type,
        models_integration.Integration.company_id == company_id,
        models_integration.Integration.enabled == True
    ).first()

def get_integration_by_google_account(db: Session, email: str, company_id: int) -> models_integration.Integration:
    """
    Finds an active Google Calendar integration by the user's email and company.
    """
    integrations = db.query(models_integration.Integration).filter(
        models_integration.Integration.type == "google_calendar",
        models_integration.Integration.company_id == company_id,
        models_integration.Integration.enabled == True
    ).all()

    for integration in integrations:
        credentials = get_decrypted_credentials(integration)
        if credentials.get("user_email") == email:
            return integration
            
    return None
