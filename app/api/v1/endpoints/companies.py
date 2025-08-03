
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.schemas import company as schemas_company
from app.services import company_service
from app.core.dependencies import get_db, get_current_active_user, require_super_admin
from app.models import user as models_user

router = APIRouter()

@router.post("/", response_model=schemas_company.Company, dependencies=[Depends(require_super_admin)])
def create_company_as_super_admin(company: schemas_company.CompanyCreate, db: Session = Depends(get_db)):
    """
    Create a new company. Only accessible by super admins.
    """
    return company_service.create_company(db=db, company=company)

@router.get("/", response_model=List[schemas_company.Company], dependencies=[Depends(require_super_admin)])
def read_all_companies_as_super_admin(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    Retrieve all companies. Only accessible by super admins.
    """
    companies = company_service.get_companies(db, skip=skip, limit=limit)
    return companies

@router.get("/my-company", response_model=schemas_company.Company)
def read_my_company(db: Session = Depends(get_db), current_user: models_user.User = Depends(get_current_active_user)):
    """
    Retrieve the company associated with the currently logged-in user.
    """
    if not current_user.company_id:
        raise HTTPException(status_code=404, detail="User is not associated with a company")
    
    db_company = company_service.get_company(db, company_id=current_user.company_id)
    if db_company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return db_company
