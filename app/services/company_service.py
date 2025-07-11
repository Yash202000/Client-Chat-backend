
from sqlalchemy.orm import Session
from app.models import company as models_company
from app.schemas import company as schemas_company

def get_company(db: Session, company_id: int):
    return db.query(models_company.Company).filter(models_company.Company.id == company_id).first()

def get_companies(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models_company.Company).offset(skip).limit(limit).all()

def create_company(db: Session, company: schemas_company.CompanyCreate):
    db_company = models_company.Company(name=company.name)
    db.add(db_company)
    db.commit()
    db.refresh(db_company)
    return db_company
