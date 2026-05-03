from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.dependencies import get_db, get_current_active_user, require_permission
from app.services import deal_service, pipeline_service
from app.schemas import deal as schemas_deal
from app.models import user as models_user

router = APIRouter()


@router.get("/", response_model=List[schemas_deal.Deal], dependencies=[Depends(require_permission("deal:read"))])
def list_deals(
    pipeline_id: Optional[int] = None,
    stage_id: Optional[int] = None,
    owner_id: Optional[int] = None,
    status: Optional[str] = None,
    query: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    if query:
        return deal_service.search_deals(db=db, company_id=current_user.company_id, query=query, skip=skip, limit=limit)
    return deal_service.get_deals(
        db=db, company_id=current_user.company_id,
        pipeline_id=pipeline_id, stage_id=stage_id,
        owner_id=owner_id, status=status,
        skip=skip, limit=limit
    )


@router.get("/forecast", dependencies=[Depends(require_permission("deal:read"))])
def get_forecast(
    pipeline_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """Weighted pipeline value by stage — used by the forecasting widget."""
    pl = pipeline_service.get_pipeline(db=db, pipeline_id=pipeline_id, company_id=current_user.company_id)
    if not pl:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return deal_service.get_pipeline_stats(db=db, company_id=current_user.company_id, pipeline_id=pipeline_id)


@router.post("/", response_model=schemas_deal.Deal, dependencies=[Depends(require_permission("deal:create"))])
def create_deal(
    deal: schemas_deal.DealCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    return deal_service.create_deal(db=db, deal=deal, company_id=current_user.company_id)


@router.get("/{deal_id}", response_model=schemas_deal.Deal, dependencies=[Depends(require_permission("deal:read"))])
def get_deal(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    d = deal_service.get_deal(db=db, deal_id=deal_id, company_id=current_user.company_id)
    if not d:
        raise HTTPException(status_code=404, detail="Deal not found")
    return d


@router.put("/{deal_id}", response_model=schemas_deal.Deal, dependencies=[Depends(require_permission("deal:update"))])
def update_deal(
    deal_id: int,
    deal: schemas_deal.DealUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    updated = deal_service.update_deal(db=db, deal_id=deal_id, deal=deal, company_id=current_user.company_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Deal not found")
    return updated


@router.delete("/{deal_id}", dependencies=[Depends(require_permission("deal:delete"))])
def delete_deal(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    deleted = deal_service.delete_deal(db=db, deal_id=deal_id, company_id=current_user.company_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Deal not found")
    return {"ok": True}
