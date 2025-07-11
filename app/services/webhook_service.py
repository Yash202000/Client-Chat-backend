from sqlalchemy.orm import Session
from app.models import webhook as models_webhook
from app.schemas import webhook as schemas_webhook

def get_webhook(db: Session, webhook_id: int, company_id: int):
    return db.query(models_webhook.Webhook).filter(models_webhook.Webhook.id == webhook_id, models_webhook.Webhook.company_id == company_id).first()

def get_webhooks_by_agent(db: Session, agent_id: int, company_id: int):
    return db.query(models_webhook.Webhook).filter(models_webhook.Webhook.agent_id == agent_id, models_webhook.Webhook.company_id == company_id).all()

def create_webhook(db: Session, webhook: schemas_webhook.WebhookCreate, company_id: int):
    db_webhook = models_webhook.Webhook(**webhook.dict(), company_id=company_id)
    db.add(db_webhook)
    db.commit()
    db.refresh(db_webhook)
    return db_webhook

def update_webhook(db: Session, webhook_id: int, webhook: schemas_webhook.WebhookUpdate, company_id: int):
    db_webhook = get_webhook(db, webhook_id, company_id)
    if db_webhook:
        for key, value in webhook.dict(exclude_unset=True).items():
            setattr(db_webhook, key, value)
        db.commit()
        db.refresh(db_webhook)
    return db_webhook

def delete_webhook(db: Session, webhook_id: int, company_id: int):
    db_webhook = get_webhook(db, webhook_id, company_id)
    if db_webhook:
        db.delete(db_webhook)
        db.commit()
    return db_webhook
