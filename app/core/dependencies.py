from app.core.database import SessionLocal
from fastapi import Header, HTTPException, Depends, status, WebSocket, WebSocketException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import settings
from app.schemas import token as schemas_token
from app.services import user_service, api_key_service
from app.models import user as models_user, company as models_company

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_current_company_from_api_key(
    x_api_key: str = Header(...), db: Session = Depends(get_db)
) -> models_company.Company:
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is missing",
        )
    api_key = api_key_service.get_api_key_by_key(db, key=x_api_key)
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return api_key.company


async def get_current_user(
    db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)
) -> models_user.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        print(f"[get_current_user] Decoded JWT payload: {payload}")
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = schemas_token.TokenData(email=email)
    except JWTError:
        print("[get_current_user] JWTError: Could not decode token")
        raise credentials_exception
    user = user_service.get_user_by_email(db, email=token_data.email)
    if user is None:
        print(f"[get_current_user] User not found for email: {token_data.email}")
        raise credentials_exception
    print(f"[get_current_user] User found: {user.email}")
    return user

async def get_current_user_from_ws(
    websocket: WebSocket,
    db: Session = Depends(get_db)
) -> models_user.User:
    """
    Dependency to get the current user from a WebSocket connection,
    expecting the token as a query parameter.
    """
    token = websocket.query_params.get("token")
    if token is None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Missing token")
    
    try:
        user = await get_current_user(db, token)
    except HTTPException:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        
    return user

async def get_current_active_user(
    current_user: models_user.User = Depends(get_current_user),
) -> models_user.User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def get_current_company(current_user: models_user.User = Depends(get_current_active_user)) -> int:
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User is not associated with a company")
    return current_user.company_id
