from typing import List

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.schemas import webhook as schemas_webhook
from app.services import webhook_service

router = APIRouter()

@router.post("/", response_model=schemas_webhook.Webhook)
def create_webhook(
    webhook: schemas_webhook.WebhookCreate,
    db: Session = Depends(get_db),
    company_id: int = Header(..., alias="x-company-id")
):
    return webhook_service.create_webhook(db=db, webhook=webhook, company_id=company_id)

@router.get("/{webhook_id}", response_model=schemas_webhook.Webhook)
def get_webhook(
    webhook_id: int,
    db: Session = Depends(get_db),
    company_id: int = Header(..., alias="x-company-id")
):
    db_webhook = webhook_service.get_webhook(db=db, webhook_id=webhook_id, company_id=company_id)
    if db_webhook is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return db_webhook

@router.get("/by_agent/{agent_id}", response_model=List[schemas_webhook.Webhook])
def get_webhooks_by_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    company_id: int = Header(..., alias="x-company-id")
):
    return webhook_service.get_webhooks_by_agent(db=db, agent_id=agent_id, company_id=company_id)

@router.put("/{webhook_id}", response_model=schemas_webhook.Webhook)
def update_webhook(
    webhook_id: int,
    webhook: schemas_webhook.WebhookUpdate,
    db: Session = Depends(get_db),
    company_id: int = Header(..., alias="x-company-id")
):
    db_webhook = webhook_service.update_webhook(db=db, webhook_id=webhook_id, webhook=webhook, company_id=company_id)
    if db_webhook is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return db_webhook

@router.delete("/{webhook_id}", response_model=schemas_webhook.Webhook)
def delete_webhook(
    webhook_id: int,
    db: Session = Depends(get_db),
    company_id: int = Header(..., alias="x-company-id")
):
    db_webhook = webhook_service.delete_webhook(db=db, webhook_id=webhook_id, company_id=company_id)
    if db_webhook is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return db_webhook
