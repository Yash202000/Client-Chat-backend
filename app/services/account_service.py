from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from app.models.account import Account
from app.schemas.account import AccountCreate, AccountUpdate


def get_account(db: Session, account_id: int, company_id: int) -> Optional[Account]:
    return db.query(Account).filter(
        Account.id == account_id,
        Account.company_id == company_id
    ).first()


def get_accounts(db: Session, company_id: int, skip: int = 0, limit: int = 100) -> List[Account]:
    return db.query(Account).filter(
        Account.company_id == company_id
    ).order_by(Account.name).offset(skip).limit(limit).all()


def search_accounts(
    db: Session,
    company_id: int,
    query: Optional[str] = None,
    industry: Optional[str] = None,
    owner_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100
) -> List[Account]:
    q = db.query(Account).filter(Account.company_id == company_id)
    if query:
        q = q.filter(or_(
            Account.name.ilike(f"%{query}%"),
            Account.domain.ilike(f"%{query}%"),
        ))
    if industry:
        q = q.filter(Account.industry == industry)
    if owner_id:
        q = q.filter(Account.owner_id == owner_id)
    return q.order_by(Account.name).offset(skip).limit(limit).all()


def count_accounts(db: Session, company_id: int) -> int:
    return db.query(Account).filter(Account.company_id == company_id).count()


def create_account(db: Session, account: AccountCreate, company_id: int) -> Account:
    db_account = Account(**account.model_dump(), company_id=company_id)
    db.add(db_account)
    db.commit()
    db.refresh(db_account)
    return db_account


def update_account(db: Session, account_id: int, account: AccountUpdate, company_id: int) -> Optional[Account]:
    db_account = get_account(db, account_id, company_id)
    if not db_account:
        return None
    for key, value in account.model_dump(exclude_unset=True).items():
        setattr(db_account, key, value)
    db.commit()
    db.refresh(db_account)
    return db_account


def delete_account(db: Session, account_id: int, company_id: int) -> bool:
    db_account = get_account(db, account_id, company_id)
    if not db_account:
        return False
    db.delete(db_account)
    db.commit()
    return True
