
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.schemas import company as schemas_company
from app.services import company_service
from app.core.dependencies import get_db, get_current_active_user
from app.models import user as models_user

router = APIRouter()

@router.post("/", response_model=schemas_company.Company)
def create_company(company: schemas_company.CompanyCreate, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    return company_service.create_company(db=db, company=company)

@router.get("/", response_model=List[schemas_company.Company])
def read_companies(skip: int = 0, limit: int = 100, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    companies = company_service.get_companies(db, skip=skip, limit=limit)
    return companies

@router.get("/{company_id}", response_model=schemas_company.Company)
def read_company(company_id: int, db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    if current_user.company_id != company_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this company")
    db_company = company_service.get_company(db, company_id=company_id)
    if db_company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return db_company
