import asyncio
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status, Body
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import settings
from app.core.limiter import limiter
from app.core.dependencies import get_db, get_current_active_user
from app.core.audit import log_action
from app.schemas import user as schemas_user, token as schemas_token, company as schemas_company
from app.services import user_service, company_service, company_subscription_service, role_service, twofa_service
from app.models.subscription_plan import SubscriptionPlan
from app.models import user as models_user

router = APIRouter()

# ---------------------------------------------------------------------------
# Disposable email domain blocklist
# ---------------------------------------------------------------------------

_DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "guerrillamail.net", "guerrillamail.org",
    "guerrillamail.biz", "guerrillamail.de", "guerrillamail.info", "spam4.me",
    "trashmail.com", "trashmail.at", "trashmail.io", "trashmail.me", "trashmail.net",
    "throwam.com", "throwaway.email", "tempmail.com", "tempmail.net", "tempmail.org",
    "temp-mail.org", "temp-mail.io", "fakeinbox.com", "maildrop.cc", "yopmail.com",
    "yopmail.fr", "dispostable.com", "discard.email", "sharklasers.com",
    "guerrillamailblock.com", "grr.la", "gurrila.com", "spam.la",
    "getairmail.com", "mailnull.com", "spamgourmet.com", "spamgourmet.net",
    "spamgourmet.org", "spamspot.com", "spamfree.eu", "binkmail.com",
    "bob.email", "mailinater.com", "spaml.com", "jetable.fr.nf",
    "moncourrier.fr.nf", "monemail.fr.nf", "monmail.fr.nf", "cool.fr.nf",
    "jetable.net", "nospam.ze.tc", "nomail.xl.cx", "mega.zik.dj",
    "speed.1s.fr", "courriel.fr.nf", "tempr.email", "tempm.com",
    "minuteinbox.com", "mailnesia.com",
    "spamthisplease.com", "mailfreeonline.com", "spamhereplease.com",
    "wegwerfmail.de", "wegwerfmail.net", "wegwerfmail.org",
    "filzmail.com", "discardmail.com", "discardmail.de",
    "spamex.com", "spamevader.com",
}


def _is_disposable_email(email: str) -> bool:
    try:
        domain = email.split("@")[1].lower()
        return domain in _DISPOSABLE_DOMAINS
    except IndexError:
        return False


_2FA_TOKEN_EXPIRE_MINUTES = 5
_2FA_CLAIM = "2fa_pending"
_EMAIL_VERIFY_CLAIM = "email_verify"
_EMAIL_VERIFY_EXPIRE_HOURS = 24


def _create_email_verify_token(email: str) -> str:
    return security.create_access_token(
        data={"sub": email, _EMAIL_VERIFY_CLAIM: True},
        expires_delta=timedelta(hours=_EMAIL_VERIFY_EXPIRE_HOURS),
    )


async def _send_verification_email(email: str, token: str) -> None:
    """Send email verification link. Silently skips if system SMTP is not configured."""
    if not settings.SYSTEM_SMTP_HOST or not settings.SYSTEM_SMTP_USER:
        return
    from app.services.email_service import send_email_smtp
    verify_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto">
      <h2 style="color:#7c3aed">Verify your email</h2>
      <p>Thanks for signing up! Click the button below to verify your email address.</p>
      <a href="{verify_url}"
         style="display:inline-block;padding:12px 24px;background:#7c3aed;color:#fff;
                border-radius:8px;text-decoration:none;font-weight:600;margin:16px 0">
        Verify Email
      </a>
      <p style="color:#64748b;font-size:13px">This link expires in 24 hours.<br>
      If you didn't create an account, you can ignore this email.</p>
    </div>
    """
    try:
        await send_email_smtp(
            to_email=email,
            subject="Verify your AgentConnect email",
            html_content=html,
            from_email=settings.SYSTEM_SMTP_FROM_EMAIL or settings.SYSTEM_SMTP_USER,
            from_name=settings.SYSTEM_SMTP_FROM_NAME,
            smtp_config={
                "host": settings.SYSTEM_SMTP_HOST,
                "port": settings.SYSTEM_SMTP_PORT,
                "user": settings.SYSTEM_SMTP_USER,
                "password": settings.SYSTEM_SMTP_PASSWORD,
                "use_tls": settings.SYSTEM_SMTP_USE_TLS,
            },
        )
    except Exception:
        pass  # Never fail signup because of email delivery issues


def _create_temp_token(email: str) -> str:
    return security.create_access_token(
        data={"sub": email, _2FA_CLAIM: True},
        expires_delta=timedelta(minutes=_2FA_TOKEN_EXPIRE_MINUTES),
    )


def _decode_temp_token(token: str) -> str:
    """Return email from a valid 2FA-pending token, or raise 401."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        if not payload.get(_2FA_CLAIM):
            raise HTTPException(status_code=401, detail="Invalid 2FA token.")
        email: Optional[str] = payload.get("sub")
        if not email:
            raise HTTPException(status_code=401, detail="Invalid 2FA token.")
        return email
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired 2FA token.")


@limiter.limit("5/minute")
@router.post("/signup", response_model=schemas_user.User)
def signup(request: Request, user: schemas_user.UserCreate, db: Session = Depends(get_db)):
    if settings.SIGNUP_PAUSED:
        raise HTTPException(
            status_code=503,
            detail=(
                "New signups are temporarily paused. "
                "Please try again later or contact support@heygenally.com"
            ),
        )
    if _is_disposable_email(user.email):
        raise HTTPException(status_code=400, detail="Please use a real email address. Disposable or temporary email addresses are not allowed.")
    db_user = user_service.get_user_by_email(db, email=user.email)
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create a new company for each user signup.
    company = company_service.create_company(db, company=schemas_company.CompanyCreate(name=f"{user.email}'s Company"))

    # Link the trial to the "Free Trial" plan so billing page shows the plan name
    free_trial_plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.name == "Free Trial").first()

    # Create trial subscription for the new company
    company_subscription_service.create_trial_subscription(
        db=db,
        company_id=company.id,
        subscription_plan_id=free_trial_plan.id if free_trial_plan else None,
        trial_days=14,
        user_limit=5
    )

    # Roles are already created inside create_company — just fetch Admin role
    admin_role = role_service.get_role_by_name(db, "Admin", company_id=company.id)

    new_user = user_service.create_user(db=db, user=user, company_id=company.id, role_id=admin_role.id if admin_role else None)

    # Send verification email (fire-and-forget, never blocks signup)
    token = _create_email_verify_token(new_user.email)
    asyncio.create_task(_send_verification_email(new_user.email, token)) if asyncio.get_event_loop().is_running() else None

    return new_user


@router.get("/verify-email")
def verify_email(token: str, db: Session = Depends(get_db)):
    """Verify a user's email address via a signed token sent at signup."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        if not payload.get(_EMAIL_VERIFY_CLAIM):
            raise HTTPException(status_code=400, detail="Invalid verification token.")
        email: Optional[str] = payload.get("sub")
        if not email:
            raise HTTPException(status_code=400, detail="Invalid verification token.")
    except JWTError:
        raise HTTPException(status_code=400, detail="Verification link is invalid or has expired.")

    db_user = user_service.get_user_by_email(db, email=email)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found.")

    if not db_user.email_verified:
        db_user.email_verified = True
        db.commit()

    return {"message": "Email verified successfully.", "email": email}


@limiter.limit("3/minute")
@router.post("/resend-verification")
def resend_verification_email(
    request: Request,
    current_user: models_user.User = Depends(get_current_active_user),
):
    """Resend the email verification link to the current user."""
    if current_user.email_verified:
        return {"message": "Email is already verified."}
    token = _create_email_verify_token(current_user.email)
    asyncio.create_task(_send_verification_email(current_user.email, token)) if asyncio.get_event_loop().is_running() else None
    return {"message": "Verification email sent."}


@limiter.limit("10/minute")
@router.post("/login", response_model=schemas_token.Token)
def login_for_access_token(
    request: Request,
    db: Session = Depends(get_db), form_data: OAuth2PasswordRequestForm = Depends()
):
    user = user_service.get_user_by_email(db, email=form_data.username)
    if not user or not security.verify_password(form_data.password, user.hashed_password):
        if user:
            log_action(db, company_id=user.company_id, user_id=user.id,
                       action="auth.login_failed", entity_type="user",
                       entity_id=user.id, entity_name=user.email)
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if user account is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated. Please contact your administrator.",
        )

    # If 2FA is enabled, issue a short-lived pending token instead of a full session
    if user.totp_enabled and user.totp_secret:
        temp_token = _create_temp_token(user.email)
        return {"requires_2fa": True, "temp_token": temp_token, "token_type": "bearer"}

    # Update user presence status to online
    user_service.update_user_presence(db, user.id, "online")

    log_action(db, company_id=user.company_id, user_id=user.id,
               action="auth.login", entity_type="user",
               entity_id=user.id, entity_name=user.email)
    db.commit()

    access_token_expires = timedelta(minutes=60 * 24 * 7) # 7 days
    access_token = security.create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer", "company_id": user.company_id, "requires_2fa": False}


@router.post("/refresh", response_model=schemas_token.Token)
def refresh_access_token(
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """Issue a new access token for the currently authenticated user."""
    access_token_expires = timedelta(minutes=60 * 24 * 7)  # 7 days
    access_token = security.create_access_token(
        data={"sub": current_user.email}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer", "company_id": current_user.company_id}


@router.post("/logout")
def logout(
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    # Update user presence status to offline
    user_service.update_user_presence(db, current_user.id, "offline")
    log_action(db, company_id=current_user.company_id, user_id=current_user.id,
               action="auth.logout", entity_type="user",
               entity_id=current_user.id, entity_name=current_user.email)
    db.commit()
    return {"message": "Successfully logged out"}


@router.post("/presence")
def update_presence(
    presence_status: str,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Update current user's presence status.
    Valid values: online, offline, busy, away, do_not_disturb, in_call, inactive
    """
    valid_statuses = ["online", "offline", "busy", "away", "do_not_disturb", "in_call", "inactive"]
    if presence_status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid presence status. Must be one of: {', '.join(valid_statuses)}"
        )

    updated_user = user_service.update_user_presence(db, current_user.id, presence_status)
    return {"presence_status": updated_user.presence_status, "last_seen": updated_user.last_seen}


# ---------------------------------------------------------------------------
# Two-Factor Authentication (TOTP)
# ---------------------------------------------------------------------------

class TwoFAVerifySetupRequest(BaseModel):
    code: str

class TwoFADisableRequest(BaseModel):
    code: str

class TwoFALoginRequest(BaseModel):
    temp_token: str
    code: str


@router.post("/2fa/setup")
def setup_2fa(
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
):
    """Generate a new TOTP secret and return provisioning URI + QR code."""
    if current_user.totp_enabled:
        raise HTTPException(status_code=400, detail="2FA is already enabled.")
    secret = twofa_service.generate_totp_secret()
    current_user.totp_secret = secret
    db.commit()

    uri = twofa_service.get_provisioning_uri(secret, current_user.email)
    qr_b64 = twofa_service.get_qr_code_base64(uri)
    return {
        "secret": secret,
        "provisioning_uri": uri,
        "qr_code": f"data:image/png;base64,{qr_b64}",
    }


@router.post("/2fa/verify-setup")
def verify_2fa_setup(
    body: TwoFAVerifySetupRequest,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
):
    """Confirm TOTP code is correct, then enable 2FA on the account."""
    if current_user.totp_enabled:
        raise HTTPException(status_code=400, detail="2FA is already enabled.")
    if not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="Call /auth/2fa/setup first.")
    if not twofa_service.verify_totp_code(current_user.totp_secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid code. Please try again.")

    current_user.totp_enabled = True
    log_action(db, company_id=current_user.company_id, user_id=current_user.id,
               action="auth.2fa_enabled", entity_type="user",
               entity_id=current_user.id, entity_name=current_user.email)
    db.commit()
    return {"message": "2FA enabled successfully."}


@router.post("/2fa/disable")
def disable_2fa(
    body: TwoFADisableRequest,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
):
    """Disable 2FA — requires a valid current TOTP code."""
    if not current_user.totp_enabled:
        raise HTTPException(status_code=400, detail="2FA is not enabled.")
    if not twofa_service.verify_totp_code(current_user.totp_secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid code.")

    current_user.totp_enabled = False
    current_user.totp_secret = None
    log_action(db, company_id=current_user.company_id, user_id=current_user.id,
               action="auth.2fa_disabled", entity_type="user",
               entity_id=current_user.id, entity_name=current_user.email)
    db.commit()
    return {"message": "2FA disabled."}


@router.post("/2fa/verify")
def verify_2fa_login(
    body: TwoFALoginRequest,
    db: Session = Depends(get_db),
):
    """Exchange a 2FA-pending temp token + TOTP code for a full session token."""
    email = _decode_temp_token(body.temp_token)

    user = user_service.get_user_by_email(db, email)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive.")
    if not user.totp_enabled or not user.totp_secret:
        raise HTTPException(status_code=400, detail="2FA not configured for this account.")
    if not twofa_service.verify_totp_code(user.totp_secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid authenticator code.")

    user_service.update_user_presence(db, user.id, "online")
    log_action(db, company_id=user.company_id, user_id=user.id,
               action="auth.login", entity_type="user",
               entity_id=user.id, entity_name=user.email)
    db.commit()

    access_token = security.create_access_token(
        data={"sub": user.email},
        expires_delta=timedelta(minutes=60 * 24 * 7),
    )
    return {"access_token": access_token, "token_type": "bearer", "company_id": user.company_id}


# ---------------------------------------------------------------------------
# Phone Verification (disabled until Twilio is configured)
# ---------------------------------------------------------------------------

class PhoneOTPRequest(BaseModel):
    phone_number: str


class PhoneOTPVerifyRequest(BaseModel):
    phone_number: str
    code: str


@limiter.limit("3/minute")
@router.post("/send-phone-otp")
def send_phone_otp(
    request: Request,
    body: PhoneOTPRequest,
    current_user: models_user.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Send a 6-digit OTP to the given phone number via Twilio. Disabled until Twilio is configured."""
    if not settings.PHONE_VERIFICATION_ENABLED:
        raise HTTPException(status_code=503, detail="Phone verification is not enabled yet.")
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        raise HTTPException(status_code=503, detail="Phone verification is not configured.")
    import random
    import string
    code = "".join(random.choices(string.digits, k=6))
    token = security.create_access_token(
        data={"sub": current_user.email, "phone_otp": code, "phone": body.phone_number},
        expires_delta=timedelta(minutes=10),
    )
    try:
        from twilio.rest import Client as TwilioClient
        client = TwilioClient(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        client.messages.create(
            body=f"Your AgentConnect verification code is: {code}",
            from_=settings.TWILIO_PHONE_NUMBER,
            to=body.phone_number,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send OTP: {str(e)}")
    return {"message": "OTP sent.", "otp_token": token}


@router.post("/verify-phone-otp")
def verify_phone_otp(
    body: PhoneOTPVerifyRequest,
    otp_token: str,
    current_user: models_user.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Verify the phone OTP token. otp_token is from send-phone-otp response."""
    if not settings.PHONE_VERIFICATION_ENABLED:
        raise HTTPException(status_code=503, detail="Phone verification is not enabled yet.")
    try:
        payload = jwt.decode(otp_token, settings.SECRET_KEY, algorithms=["HS256"])
        stored_code = payload.get("phone_otp")
        stored_phone = payload.get("phone")
        if payload.get("sub") != current_user.email:
            raise HTTPException(status_code=400, detail="Token mismatch.")
    except JWTError:
        raise HTTPException(status_code=400, detail="OTP token is invalid or expired.")
    if stored_phone != body.phone_number:
        raise HTTPException(status_code=400, detail="Phone number mismatch.")
    if stored_code != body.code:
        raise HTTPException(status_code=400, detail="Invalid OTP code.")
    current_user.phone_number = body.phone_number
    current_user.phone_verified = True
    db.commit()
    return {"message": "Phone number verified successfully."}
