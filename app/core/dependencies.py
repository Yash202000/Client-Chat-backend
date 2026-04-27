from typing import Optional
from app.core.database import SessionLocal
from fastapi import Header, HTTPException, Depends, Query, WebSocketDisconnect, status, WebSocket, WebSocketException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session, joinedload

from app.core import security
from app.core.config import settings
from app.schemas import token as schemas_token, user as schemas_user
from app.services import user_service, api_key_service, company_subscription_service, license_service
from app.core.license_exceptions import LicenseExpiredError, LicenseInvalidError, LicenseNotConfiguredError
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
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
    x_company_id: Optional[int] = Header(default=None),
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

    validated = schemas_user.User.model_validate(user)

    # Allow super admins to switch company context via X-Company-ID header
    if validated.is_super_admin and x_company_id and x_company_id != validated.company_id:
        validated = validated.model_copy(update={'company_id': x_company_id})

    return validated

async def get_current_user_from_ws(websocket: WebSocket, db: Session = Depends(get_db), token: Optional[str] = Query(None)) -> models_user.User:
    if token is None:
        raise WebSocketDisconnect(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication token missing")
    
    credentials_exception = WebSocketDisconnect(
        code=status.WS_1008_POLICY_VIOLATION,
        reason="Could not validate credentials",
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = user_service.get_user_by_email(db, email=email)
    
    if user is None:
        raise credentials_exception
    return user

async def get_current_active_user(
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_user),
) -> models_user.User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    # On-premise mode: enforce license validation on EVERY authenticated request
    if settings.DEPLOYMENT_MODE == "on_premise":
        # Check for license key (env var or database)
        license_key = settings.LICENSE_KEY
        if not license_key:
            # Check database for activated license
            instance_license = license_service.get_instance_license(db)
            if instance_license:
                license_key = instance_license.license_key

        # If no license is configured at all, only super_admin can access (to set up license)
        if not license_key:
            if current_user.is_super_admin:
                return current_user  # Allow super_admin to configure license
            raise LicenseNotConfiguredError()

        # Validate the license
        payload = license_service.validate_license_key(license_key)
        if not payload:
            raise LicenseInvalidError()

        # Check if license is expired
        if license_service.is_license_expired(payload):
            raise LicenseExpiredError()

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


async def require_active_subscription(
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Dependency that blocks access if subscription is expired/canceled or trial ended.
    Super admins bypass this check.
    """
    if current_user.is_super_admin:
        return current_user

    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with a company.",
        )

    if not company_subscription_service.is_subscription_active(db, current_user.company_id):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Your subscription has expired. Please upgrade to continue.",
        )

    return current_user


def require_user_limit_not_exceeded(
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Dependency that blocks user creation if company is at user limit.
    Super admins bypass this check.
    """
    if current_user.is_super_admin:
        return current_user

    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with a company.",
        )

    if not company_subscription_service.can_add_user(db, current_user.company_id):
        # Get current status for helpful error message
        status_info = company_subscription_service.get_subscription_status(db, current_user.company_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User limit reached. Your plan allows {status_info.user_limit} users. Please upgrade to add more users.",
        )

    return current_user


async def require_valid_license(
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Full lockout dependency for on-premise mode.
    Blocks ALL access if license is expired/invalid.
    In cloud mode, this check is skipped (Stripe subscriptions handle access).
    Super admins bypass this check to allow license configuration.
    """
    # Cloud mode uses Stripe subscriptions
    if settings.DEPLOYMENT_MODE != "on_premise":
        return current_user

    # Super admins can bypass to configure license
    if current_user.is_super_admin:
        return current_user

    # Check license validity
    license_key = settings.LICENSE_KEY
    if not license_key:
        # Check database for activated license
        instance_license = license_service.get_instance_license(db)
        if instance_license:
            license_key = instance_license.license_key

    if not license_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No license configured. Please contact your administrator.",
        )

    if not license_service.is_license_valid(license_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="License expired or invalid. Please contact your administrator to renew the license.",
        )

    return current_user
