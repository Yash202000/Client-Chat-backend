from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from typing import List, Optional
from decimal import Decimal
from app.models.deal import Deal, DealStatus
from app.models.pipeline import DealStage
from app.schemas.deal import DealCreate, DealUpdate


def get_deal(db: Session, deal_id: int, company_id: int) -> Optional[Deal]:
    return db.query(Deal).filter(Deal.id == deal_id, Deal.company_id == company_id).first()


def get_deals(db: Session, company_id: int, pipeline_id: Optional[int] = None,
              stage_id: Optional[int] = None, owner_id: Optional[int] = None,
              status: Optional[str] = None, skip: int = 0, limit: int = 100) -> List[Deal]:
    q = db.query(Deal).filter(Deal.company_id == company_id)
    if pipeline_id:
        q = q.filter(Deal.pipeline_id == pipeline_id)
    if stage_id:
        q = q.filter(Deal.stage_id == stage_id)
    if owner_id:
        q = q.filter(Deal.owner_id == owner_id)
    if status:
        q = q.filter(Deal.status == status)
    return q.order_by(Deal.created_at.desc()).offset(skip).limit(limit).all()


def search_deals(db: Session, company_id: int, query: str,
                 skip: int = 0, limit: int = 100) -> List[Deal]:
    return db.query(Deal).filter(
        Deal.company_id == company_id,
        Deal.title.ilike(f"%{query}%")
    ).order_by(Deal.created_at.desc()).offset(skip).limit(limit).all()


def create_deal(db: Session, deal: DealCreate, company_id: int) -> Deal:
    db_deal = Deal(**deal.model_dump(), company_id=company_id)
    db.add(db_deal)
    db.commit()
    db.refresh(db_deal)
    return db_deal


def update_deal(db: Session, deal_id: int, deal: DealUpdate, company_id: int) -> Optional[Deal]:
    db_deal = get_deal(db, deal_id, company_id)
    if not db_deal:
        return None
    for key, value in deal.model_dump(exclude_unset=True).items():
        setattr(db_deal, key, value)
    db.commit()
    db.refresh(db_deal)
    return db_deal


def delete_deal(db: Session, deal_id: int, company_id: int) -> bool:
    db_deal = get_deal(db, deal_id, company_id)
    if not db_deal:
        return False
    db.delete(db_deal)
    db.commit()
    return True


def get_pipeline_stats(db: Session, company_id: int, pipeline_id: int) -> dict:
    """Weighted pipeline value by stage for forecasting widget."""
    stages = db.query(DealStage).filter(DealStage.pipeline_id == pipeline_id).all()
    stage_ids = [s.id for s in stages]
    stage_map = {s.id: s for s in stages}

    rows = db.query(
        Deal.stage_id,
        func.count(Deal.id).label("count"),
        func.coalesce(func.sum(Deal.amount), 0).label("total_value")
    ).filter(
        Deal.company_id == company_id,
        Deal.pipeline_id == pipeline_id,
        Deal.status == DealStatus.OPEN,
        Deal.stage_id.in_(stage_ids)
    ).group_by(Deal.stage_id).all()

    total_weighted = Decimal("0")
    by_stage = []
    for row in rows:
        stage = stage_map[row.stage_id]
        weighted = Decimal(str(row.total_value)) * Decimal(stage.probability) / 100
        total_weighted += weighted
        by_stage.append({
            "stage_id": row.stage_id,
            "stage_name": stage.name,
            "probability": stage.probability,
            "deal_count": row.count,
            "total_value": float(row.total_value),
            "weighted_value": float(weighted),
        })

    return {"by_stage": by_stage, "total_weighted_value": float(total_weighted)}
