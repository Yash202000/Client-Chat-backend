from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.dependencies import get_db, get_current_active_user, require_permission
from app.services import account_service
from app.schemas import account as schemas_account
from app.models import user as models_user

router = APIRouter()


@router.get("/", response_model=List[schemas_account.Account], dependencies=[Depends(require_permission("account:read"))])
def list_accounts(
    skip: int = 0,
    limit: int = 100,
    query: Optional[str] = None,
    industry: Optional[str] = None,
    owner_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    if any([query, industry, owner_id]):
        accounts = account_service.search_accounts(
            db=db, company_id=current_user.company_id,
            query=query, industry=industry, owner_id=owner_id,
            skip=skip, limit=limit
        )
    else:
        accounts = account_service.get_accounts(db=db, company_id=current_user.company_id, skip=skip, limit=limit)

    result = []
    for acc in accounts:
        acc_dict = {c.name: getattr(acc, c.name) for c in acc.__table__.columns}
        acc_dict["contact_count"] = len(acc.contacts) if acc.contacts else 0
        acc_dict["owner"] = acc.owner
        result.append(acc_dict)
    return result


@router.get("/stats", dependencies=[Depends(require_permission("account:read"))])
def get_account_stats(
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    total = account_service.count_accounts(db=db, company_id=current_user.company_id)
    return {"total": total}


@router.post("/", response_model=schemas_account.Account, dependencies=[Depends(require_permission("account:create"))])
def create_account(
    account: schemas_account.AccountCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    return account_service.create_account(db=db, account=account, company_id=current_user.company_id)


@router.get("/{account_id}", response_model=schemas_account.AccountWithContacts, dependencies=[Depends(require_permission("account:read"))])
def get_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    acc = account_service.get_account(db=db, account_id=account_id, company_id=current_user.company_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    return acc


@router.put("/{account_id}", response_model=schemas_account.Account, dependencies=[Depends(require_permission("account:update"))])
def update_account(
    account_id: int,
    account: schemas_account.AccountUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    updated = account_service.update_account(
        db=db, account_id=account_id, account=account, company_id=current_user.company_id
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Account not found")
    return updated


@router.delete("/{account_id}", dependencies=[Depends(require_permission("account:delete"))])
def delete_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    deleted = account_service.delete_account(db=db, account_id=account_id, company_id=current_user.company_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"ok": True}
