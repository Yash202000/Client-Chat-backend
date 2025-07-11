from app.core.database import SessionLocal
from fastapi import Header, HTTPException

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_current_company(x_company_id: int = Header(..., alias="X-Company-ID")):
    # In a real application, you would validate the company ID against a database
    # and ensure the user making the request is authorized for this company.
    # For now, we'll just return the company ID from the header.
    if x_company_id <= 0:
        raise HTTPException(status_code=400, detail="X-Company-ID header invalid")
    return x_company_id