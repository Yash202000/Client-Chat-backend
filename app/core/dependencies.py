from app.core.database import SessionLocal
from fastapi import Header, HTTPException, Depends, status, WebSocket, WebSocketException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session, joinedload

from app.core import security
from app.core.config import settings
from app.schemas import token as schemas_token, user as schemas_user
from app.services import user_service, api_key_service
from app.models import user as models_user, company as models_company, role as models_role

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
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = schemas_token.TokenData(email=email)
    except JWTError:
        raise credentials_exception
    
    # Eager load role and permissions
    user = db.query(models_user.User).options(
        joinedload(models_user.User.role).joinedload(models_role.Role.permissions)
    ).filter(models_user.User.email == token_data.email).first()

    if user is None:
        raise credentials_exception
    return schemas_user.User.from_orm(user)

async def get_current_user_from_ws(
    websocket: WebSocket,
    db: Session = Depends(get_db)
) -> models_user.User:
    """
    Dependency to get the current user from a WebSocket connection,
    expecting the token as a query parameter.
    """
    from app.core.auth import get_user_from_token # Import internally

    token = websocket.query_params.get("token")
    if token is None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Missing token")
    
    try:
        user = get_user_from_token(db, token) # Use the new function
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

# Permission checking dependency
def require_permission(permission_name: str):
    """
    Dependency factory that creates a dependency to check for a specific permission.
    """
    async def permission_checker(current_user: models_user.User = Depends(get_current_active_user)):
        if current_user.is_super_admin:
            return current_user

        if not current_user.role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no assigned role.",
            )
        
        user_permissions = {p.name for p in current_user.role.permissions}
        if permission_name not in user_permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Not enough permissions. Requires '{permission_name}'.",
            )
        return current_user
    return permission_checker

def require_super_admin(current_user: models_user.User = Depends(get_current_active_user)):
    """
    Dependency that requires the current user to be a super admin.
    """
    if not current_user.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires super admin privileges.",
        )
    return current_user
