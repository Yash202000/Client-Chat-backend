import json
import logging
import httpx
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, get_user_from_token
from app.core.config import settings
from app.core.dependencies import get_db
from app.models.social_account import SocialAccount, SocialPlatform, SocialAccountStatus
from app.models.social_post import SocialPost, PostStatus
from app.models.user import User
from app.services.vault_service import vault_service

router = APIRouter()

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SocialAccountResponse(BaseModel):
    id: int
    platform: str
    account_name: str
    account_id: str
    account_type: Optional[str]
    status: str
    token_expires_at: Optional[datetime]
    scopes: Optional[list]
    metadata_: Optional[dict]
    created_at: datetime

    class Config:
        from_attributes = True


class SocialPostCreate(BaseModel):
    social_account_id: int
    content: str
    media_urls: Optional[List[str]] = None
    hashtags: Optional[List[str]] = None
    scheduled_at: Optional[datetime] = None
    ai_generated: bool = False
    source_topic: Optional[str] = None
    source_url: Optional[str] = None


class SocialPostUpdate(BaseModel):
    content: Optional[str] = None
    media_urls: Optional[List[str]] = None
    hashtags: Optional[List[str]] = None
    scheduled_at: Optional[datetime] = None


class SocialPostResponse(BaseModel):
    id: int
    platform: str
    content: str
    media_urls: Optional[list]
    hashtags: Optional[list]
    status: str
    scheduled_at: Optional[datetime]
    published_at: Optional[datetime]
    platform_post_id: Optional[str]
    error_message: Optional[str]
    ai_generated: bool
    source_topic: Optional[str]
    source_url: Optional[str]
    likes: int
    comments: int
    shares: int
    impressions: int
    created_at: datetime

    class Config:
        from_attributes = True


class AIGenerateFromTopicRequest(BaseModel):
    topic: str
    tone: str = "professional"
    target_platforms: List[str] = ["linkedin", "instagram", "facebook"]
    include_hashtags: bool = True
    credential_id: Optional[int] = None
    model: Optional[str] = None


class AIGenerateFromURLRequest(BaseModel):
    source_url: str
    target_platforms: List[str] = ["linkedin", "instagram", "facebook"]
    adaptation_style: str = "inspired_by"  # "inspired_by" | "repurpose" | "commentary"
    credential_id: Optional[int] = None
    model: Optional[str] = None


class AIImproveRequest(BaseModel):
    content: str
    platform: str
    improvements: List[str]
    credential_id: Optional[int] = None
    model: Optional[str] = None


class ScheduleRequest(BaseModel):
    scheduled_at: datetime


# ---------------------------------------------------------------------------
# Social Accounts — CRUD
# ---------------------------------------------------------------------------

@router.get("/accounts", response_model=List[SocialAccountResponse])
def list_social_accounts(
    platform: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(SocialAccount).filter(SocialAccount.company_id == current_user.company_id)
    if platform:
        query = query.filter(SocialAccount.platform == platform)
    return query.order_by(SocialAccount.created_at.desc()).all()


@router.get("/accounts/{account_id}", response_model=SocialAccountResponse)
def get_social_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = db.query(SocialAccount).filter(
        SocialAccount.id == account_id,
        SocialAccount.company_id == current_user.company_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Social account not found")
    return account


@router.get("/accounts/{account_id}/status")
def get_account_status(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = db.query(SocialAccount).filter(
        SocialAccount.id == account_id,
        SocialAccount.company_id == current_user.company_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Social account not found")

    days_until_expiry = None
    if account.token_expires_at:
        delta = account.token_expires_at - datetime.utcnow()
        days_until_expiry = max(0, delta.days)

    return {
        "id": account.id,
        "platform": account.platform,
        "status": account.status,
        "token_expires_at": account.token_expires_at,
        "days_until_expiry": days_until_expiry,
        "expiry_warning": days_until_expiry is not None and days_until_expiry <= 7,
    }


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_social_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = db.query(SocialAccount).filter(
        SocialAccount.id == account_id,
        SocialAccount.company_id == current_user.company_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Social account not found")
    db.delete(account)
    db.commit()


# ---------------------------------------------------------------------------
# OAuth Flows
# ---------------------------------------------------------------------------

@router.get("/auth/linkedin/connect")
def linkedin_connect(
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """Redirect to LinkedIn OAuth authorization page. Token passed as query param (browser navigation)."""
    current_user = get_user_from_token(db, token)
    if not settings.LINKEDIN_CLIENT_ID:
        raise HTTPException(status_code=400, detail="LinkedIn client ID not configured")

    scope = "openid profile email w_member_social"
    # Reuse the same /linkedin-callback frontend route — state prefix "social:" distinguishes from the old integration flow
    redirect_uri = settings.LINKEDIN_REDIRECT_URI
    state = f"social:{current_user.company_id}:{current_user.id}"

    url = (
        f"https://www.linkedin.com/oauth/v2/authorization"
        f"?response_type=code"
        f"&client_id={settings.LINKEDIN_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scope}"
        f"&state={state}"
    )
    return RedirectResponse(url=url)


@router.post("/auth/linkedin/exchange")
async def linkedin_exchange(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Exchange LinkedIn auth code for access token and store SocialAccount. Called by frontend callback page."""
    code = payload.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")
    company_id, user_id = current_user.company_id, current_user.id

    redirect_uri = settings.LINKEDIN_REDIRECT_URI

    async with httpx.AsyncClient(timeout=30.0) as client:
        token_resp = await client.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": settings.LINKEDIN_CLIENT_ID,
                "client_secret": settings.LINKEDIN_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status_code != 200:
            raise HTTPException(status_code=400, detail=f"LinkedIn token exchange failed: {token_resp.text}")
        token_data = token_resp.json()

        access_token = token_data.get("access_token")
        expires_in = token_data.get("expires_in", 5184000)  # default 60 days

        # Fetch profile via OpenID Connect userinfo endpoint
        profile_resp = await client.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if profile_resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to fetch LinkedIn profile: {profile_resp.status_code} {profile_resp.text}"
            )
        profile = profile_resp.json()

    account_name = profile.get("name") or (
        f"{profile.get('given_name', '')} {profile.get('family_name', '')}".strip()
    ) or "LinkedIn Account"
    account_id = profile.get("sub") or "unknown"
    avatar_url = profile.get("picture")

    credentials_json = json.dumps({
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
    })

    # Delete any stale records (account_id = "unknown") for this company/platform
    db.query(SocialAccount).filter(
        SocialAccount.company_id == company_id,
        SocialAccount.platform == SocialPlatform.LINKEDIN,
        SocialAccount.account_id == "unknown",
    ).delete()

    # Upsert — update existing account for this member instead of creating duplicates
    account = db.query(SocialAccount).filter(
        SocialAccount.company_id == company_id,
        SocialAccount.platform == SocialPlatform.LINKEDIN,
        SocialAccount.account_id == account_id,
    ).first()

    if account:
        account.account_name = account_name
        account.credentials = vault_service.encrypt(credentials_json)
        account.status = SocialAccountStatus.ACTIVE
        account.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        account.metadata_ = {"avatar_url": avatar_url}
    else:
        account = SocialAccount(
            company_id=company_id,
            platform=SocialPlatform.LINKEDIN,
            account_name=account_name,
            account_id=account_id,
            account_type="personal",
            credentials=vault_service.encrypt(credentials_json),
            status=SocialAccountStatus.ACTIVE,
            token_expires_at=datetime.utcnow() + timedelta(seconds=expires_in),
            scopes=["openid", "profile", "email", "w_member_social"],
            metadata_={"avatar_url": avatar_url},
        )
        db.add(account)

    db.commit()
    db.refresh(account)

    return {"status": "connected", "account_id": account.id, "account_name": account_name}


@router.get("/auth/facebook/connect")
def facebook_connect(
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """Redirect to Facebook OAuth authorization page. Token passed as query param (browser navigation)."""
    current_user = get_user_from_token(db, token)
    if not settings.FACEBOOK_APP_ID:
        raise HTTPException(status_code=400, detail="Facebook app ID not configured")

    scope = "pages_manage_posts,pages_read_engagement,pages_show_list"
    redirect_uri = settings.FACEBOOK_REDIRECT_URI or f"{settings.FRONTEND_URL}/api/v1/social/auth/facebook/callback"
    state = f"{current_user.company_id}:{current_user.id}"

    url = (
        f"https://www.facebook.com/v19.0/dialog/oauth"
        f"?client_id={settings.FACEBOOK_APP_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scope}"
        f"&state={state}"
    )
    return RedirectResponse(url=url)


@router.get("/auth/facebook/callback")
async def facebook_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    """Handle Facebook OAuth callback."""
    parts = state.split(":")
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid state parameter")
    company_id, user_id = int(parts[0]), int(parts[1])

    redirect_uri = settings.FACEBOOK_REDIRECT_URI or f"{settings.FRONTEND_URL}/api/v1/social/auth/facebook/callback"

    async with httpx.AsyncClient() as client:
        token_resp = await client.get(
            "https://graph.facebook.com/v19.0/oauth/access_token",
            params={
                "client_id": settings.FACEBOOK_APP_ID,
                "client_secret": settings.FACEBOOK_APP_SECRET,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to exchange Facebook authorization code")
        token_data = token_resp.json()
        access_token = token_data.get("access_token")

        # Fetch pages list
        pages_resp = await client.get(
            "https://graph.facebook.com/v19.0/me/accounts",
            params={"access_token": access_token},
        )
        pages = pages_resp.json().get("data", []) if pages_resp.status_code == 200 else []

    for page in pages:
        credentials_json = json.dumps({
            "access_token": page.get("access_token", access_token),
            "page_id": page.get("id"),
            "token_type": "Bearer",
        })
        account = SocialAccount(
            company_id=company_id,
            platform=SocialPlatform.FACEBOOK,
            account_name=page.get("name", "Facebook Page"),
            account_id=page.get("id", "unknown"),
            account_type="page",
            credentials=vault_service.encrypt(credentials_json),
            status=SocialAccountStatus.ACTIVE,
            token_expires_at=datetime.utcnow() + timedelta(days=60),
            scopes=["pages_manage_posts", "pages_read_engagement"],
            metadata_={"category": page.get("category")},
        )
        db.add(account)

    if not pages:
        credentials_json = json.dumps({"access_token": access_token, "token_type": "Bearer"})
        account = SocialAccount(
            company_id=company_id,
            platform=SocialPlatform.FACEBOOK,
            account_name="Facebook Account",
            account_id="unknown",
            account_type="personal",
            credentials=vault_service.encrypt(credentials_json),
            status=SocialAccountStatus.ACTIVE,
            token_expires_at=datetime.utcnow() + timedelta(days=60),
            scopes=["pages_manage_posts", "pages_read_engagement"],
        )
        db.add(account)

    db.commit()
    return RedirectResponse(url=f"{settings.FRONTEND_URL}/dashboard/social/accounts?connected=facebook")


@router.get("/auth/instagram/connect")
def instagram_connect(
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """Instagram uses Facebook OAuth — redirect there with instagram scopes. Token passed as query param."""
    current_user = get_user_from_token(db, token)
    if not settings.FACEBOOK_APP_ID:
        raise HTTPException(status_code=400, detail="Facebook/Instagram app ID not configured")

    scope = "instagram_basic,instagram_content_publish,pages_read_engagement,pages_show_list"
    redirect_uri = settings.FACEBOOK_REDIRECT_URI.replace("facebook", "instagram") if settings.FACEBOOK_REDIRECT_URI else f"{settings.FRONTEND_URL}/api/v1/social/auth/instagram/callback"
    state = f"{current_user.company_id}:{current_user.id}"

    url = (
        f"https://www.facebook.com/v19.0/dialog/oauth"
        f"?client_id={settings.FACEBOOK_APP_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scope}"
        f"&state={state}"
    )
    return RedirectResponse(url=url)


@router.get("/auth/instagram/callback")
async def instagram_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    """Handle Instagram OAuth callback via Facebook Graph API."""
    parts = state.split(":")
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid state parameter")
    company_id, user_id = int(parts[0]), int(parts[1])

    redirect_uri = settings.FACEBOOK_REDIRECT_URI.replace("facebook", "instagram") if settings.FACEBOOK_REDIRECT_URI else f"{settings.FRONTEND_URL}/api/v1/social/auth/instagram/callback"

    async with httpx.AsyncClient() as client:
        token_resp = await client.get(
            "https://graph.facebook.com/v19.0/oauth/access_token",
            params={
                "client_id": settings.FACEBOOK_APP_ID,
                "client_secret": settings.FACEBOOK_APP_SECRET,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to exchange Instagram authorization code")
        access_token = token_resp.json().get("access_token")

        # Get pages, then their linked Instagram Business accounts
        pages_resp = await client.get(
            "https://graph.facebook.com/v19.0/me/accounts",
            params={"access_token": access_token},
        )
        pages = pages_resp.json().get("data", []) if pages_resp.status_code == 200 else []

        for page in pages:
            ig_resp = await client.get(
                f"https://graph.facebook.com/v19.0/{page['id']}",
                params={
                    "fields": "instagram_business_account",
                    "access_token": page.get("access_token", access_token),
                },
            )
            ig_data = ig_resp.json().get("instagram_business_account") if ig_resp.status_code == 200 else None
            if not ig_data:
                continue

            ig_id = ig_data.get("id")
            ig_profile_resp = await client.get(
                f"https://graph.facebook.com/v19.0/{ig_id}",
                params={
                    "fields": "username,followers_count,profile_picture_url",
                    "access_token": page.get("access_token", access_token),
                },
            )
            ig_profile = ig_profile_resp.json() if ig_profile_resp.status_code == 200 else {}

            credentials_json = json.dumps({
                "access_token": page.get("access_token", access_token),
                "ig_user_id": ig_id,
                "page_id": page.get("id"),
                "token_type": "Bearer",
            })
            account = SocialAccount(
                company_id=company_id,
                platform=SocialPlatform.INSTAGRAM,
                account_name=f"@{ig_profile.get('username', 'instagram')}",
                account_id=ig_id,
                account_type="business",
                credentials=vault_service.encrypt(credentials_json),
                status=SocialAccountStatus.ACTIVE,
                token_expires_at=datetime.utcnow() + timedelta(days=60),
                scopes=["instagram_basic", "instagram_content_publish"],
                metadata_={
                    "username": ig_profile.get("username"),
                    "followers_count": ig_profile.get("followers_count"),
                    "avatar_url": ig_profile.get("profile_picture_url"),
                },
            )
            db.add(account)

    db.commit()
    return RedirectResponse(url=f"{settings.FRONTEND_URL}/dashboard/social/accounts?connected=instagram")


# ---------------------------------------------------------------------------
# Social Posts — CRUD
# ---------------------------------------------------------------------------

@router.get("/posts", response_model=List[SocialPostResponse])
def list_posts(
    platform: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(SocialPost).filter(SocialPost.company_id == current_user.company_id)
    if platform:
        query = query.filter(SocialPost.platform == platform)
    if status_filter:
        query = query.filter(SocialPost.status == status_filter)
    if from_date and to_date:
        query = query.filter(
            or_(
                (SocialPost.scheduled_at >= from_date) & (SocialPost.scheduled_at <= to_date),
                (SocialPost.published_at >= from_date) & (SocialPost.published_at <= to_date),
                (SocialPost.created_at >= from_date) & (SocialPost.created_at <= to_date),
            )
        )
    elif from_date:
        query = query.filter(
            or_(SocialPost.scheduled_at >= from_date, SocialPost.published_at >= from_date, SocialPost.created_at >= from_date)
        )
    elif to_date:
        query = query.filter(
            or_(SocialPost.scheduled_at <= to_date, SocialPost.published_at <= to_date, SocialPost.created_at <= to_date)
        )
    return query.order_by(SocialPost.created_at.desc()).offset(skip).limit(limit).all()


@router.post("/posts", response_model=SocialPostResponse, status_code=status.HTTP_201_CREATED)
def create_post(
    payload: SocialPostCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = db.query(SocialAccount).filter(
        SocialAccount.id == payload.social_account_id,
        SocialAccount.company_id == current_user.company_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Social account not found")

    post_status = PostStatus.SCHEDULED if payload.scheduled_at else PostStatus.DRAFT
    post = SocialPost(
        company_id=current_user.company_id,
        social_account_id=payload.social_account_id,
        platform=account.platform,
        content=payload.content,
        media_urls=payload.media_urls,
        hashtags=payload.hashtags,
        status=post_status,
        scheduled_at=payload.scheduled_at,
        ai_generated=payload.ai_generated,
        source_topic=payload.source_topic,
        source_url=payload.source_url,
        created_by_user_id=current_user.id,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


@router.get("/posts/{post_id}", response_model=SocialPostResponse)
def get_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = db.query(SocialPost).filter(
        SocialPost.id == post_id,
        SocialPost.company_id == current_user.company_id,
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.put("/posts/{post_id}", response_model=SocialPostResponse)
def update_post(
    post_id: int,
    payload: SocialPostUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = db.query(SocialPost).filter(
        SocialPost.id == post_id,
        SocialPost.company_id == current_user.company_id,
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.status == PostStatus.PUBLISHED:
        raise HTTPException(status_code=400, detail="Cannot edit a published post")

    for field, value in payload.dict(exclude_none=True).items():
        setattr(post, field, value)

    if payload.scheduled_at and post.status == PostStatus.DRAFT:
        post.status = PostStatus.SCHEDULED

    post.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(post)
    return post


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = db.query(SocialPost).filter(
        SocialPost.id == post_id,
        SocialPost.company_id == current_user.company_id,
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    db.delete(post)
    db.commit()


@router.post("/posts/{post_id}/schedule", response_model=SocialPostResponse)
def schedule_post(
    post_id: int,
    payload: ScheduleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = db.query(SocialPost).filter(
        SocialPost.id == post_id,
        SocialPost.company_id == current_user.company_id,
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.status == PostStatus.PUBLISHED:
        raise HTTPException(status_code=400, detail="Post is already published")
    scheduled_at_naive = payload.scheduled_at.replace(tzinfo=None) if payload.scheduled_at.tzinfo else payload.scheduled_at
    if scheduled_at_naive <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="Scheduled time must be in the future")

    post.scheduled_at = scheduled_at_naive
    post.status = PostStatus.SCHEDULED
    post.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(post)
    return post


@router.post("/posts/{post_id}/cancel", response_model=SocialPostResponse)
def cancel_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = db.query(SocialPost).filter(
        SocialPost.id == post_id,
        SocialPost.company_id == current_user.company_id,
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.status != PostStatus.SCHEDULED:
        raise HTTPException(status_code=400, detail="Only scheduled posts can be cancelled")

    post.status = PostStatus.DRAFT
    post.scheduled_at = None
    post.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(post)
    return post


@router.post("/posts/{post_id}/publish", response_model=SocialPostResponse)
async def publish_post_now(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.social_publishing_service import SocialPublishingService
    post = db.query(SocialPost).filter(
        SocialPost.id == post_id,
        SocialPost.company_id == current_user.company_id,
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.status == PostStatus.PUBLISHED:
        raise HTTPException(status_code=400, detail="Post is already published")

    service = SocialPublishingService()
    await service.publish_post_to_platform(db, post)
    db.refresh(post)
    return post


# ---------------------------------------------------------------------------
# AI Content Generation
# ---------------------------------------------------------------------------

@router.post("/ai/generate-from-topic")
async def ai_generate_from_topic(
    payload: AIGenerateFromTopicRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.social_content_ai_service import SocialContentAIService
    service = SocialContentAIService()
    return await service.generate_from_topic(
        db=db,
        company_id=current_user.company_id,
        credential_id=payload.credential_id,
        topic=payload.topic,
        tone=payload.tone,
        target_platforms=payload.target_platforms,
        include_hashtags=payload.include_hashtags,
        model=payload.model,
    )


@router.post("/ai/generate-from-url")
async def ai_generate_from_url(
    payload: AIGenerateFromURLRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.social_content_ai_service import SocialContentAIService
    service = SocialContentAIService()
    return await service.generate_from_url(
        db=db,
        company_id=current_user.company_id,
        credential_id=payload.credential_id,
        source_url=payload.source_url,
        target_platforms=payload.target_platforms,
        adaptation_style=payload.adaptation_style,
        model=payload.model,
    )


@router.post("/ai/improve")
async def ai_improve_post(
    payload: AIImproveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.social_content_ai_service import SocialContentAIService
    service = SocialContentAIService()
    return await service.improve_post(
        db=db,
        company_id=current_user.company_id,
        credential_id=payload.credential_id,
        content=payload.content,
        platform=payload.platform,
        improvements=payload.improvements,
        model=payload.model,
    )


class AIChatRequest(BaseModel):
    message: str
    history: List[dict] = []
    current_content: str = ""
    platform: str = "linkedin"
    credential_id: Optional[int] = None
    model: Optional[str] = None


@router.post("/ai/chat")
async def ai_chat_post(
    payload: AIChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.social_content_ai_service import SocialContentAIService
    service = SocialContentAIService()
    return await service.chat_about_post(
        db=db,
        company_id=current_user.company_id,
        credential_id=payload.credential_id,
        message=payload.message,
        history=payload.history,
        current_content=payload.current_content,
        platform=payload.platform,
        model=payload.model,
    )


# ---------------------------------------------------------------------------
# URL Content Extraction
# ---------------------------------------------------------------------------

@router.get("/search-linkedin")
async def search_linkedin_posts(
    keyword: str,
    sort_by: str = "RECENCY",  # RECENCY | RELEVANCE
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search LinkedIn posts by hashtag via the official LinkedIn API using the connected SocialAccount."""
    import json
    from app.services.trending_content_service import TrendingContentService

    # Try official LinkedIn hashtag search; fall back to Google News if API not yet approved
    account = (
        db.query(SocialAccount)
        .filter(
            SocialAccount.company_id == current_user.company_id,
            SocialAccount.platform == SocialPlatform.LINKEDIN,
            SocialAccount.status == SocialAccountStatus.ACTIVE,
        )
        .first()
    )

    svc = TrendingContentService()

    if account:
        try:
            creds = json.loads(vault_service.decrypt(account.credentials))
            access_token = creds.get("access_token", "")
            if access_token:
                results = await svc.search_linkedin_posts(access_token, keyword, sort_by, limit)
                return {"posts": results, "keyword": keyword, "source": "linkedin_official"}
        except ValueError as e:
            err = str(e)
            # Community Management API not yet approved — fall through to Google News
            if "404" in err or "RESOURCE_NOT_FOUND" in err or "permissions" in err or "review" in err:
                logger.info(f"LinkedIn hashtag API not available yet, falling back to Google News for keyword={keyword!r}")
            else:
                raise HTTPException(status_code=400, detail=err)
        except Exception as e:
            logger.warning(f"LinkedIn search unexpected error: {e}")

    # Fallback: Google News search with the same keyword
    news = await svc.get_google_news_rss(query=keyword, limit=limit)
    return {
        "posts": news,
        "keyword": keyword,
        "source": "google_news_fallback",
        "notice": "LinkedIn post search requires Community Management API approval (under review). Showing Google News results instead.",
    }


@router.get("/extract-url")
async def extract_url_content(
    url: str,
    current_user: User = Depends(get_current_user),
):
    """Fetch a URL and return its title, description, image, and readable body text."""
    from app.services.trending_content_service import TrendingContentService
    svc = TrendingContentService()
    data = await svc.extract_post_metadata(url)
    return data


# ---------------------------------------------------------------------------
# Trending Topics
# ---------------------------------------------------------------------------

@router.get("/trending")
async def get_trending(
    keyword: Optional[str] = None,
    geo: str = "US",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.trending_content_service import TrendingContentService
    service = TrendingContentService()
    google = await service.get_google_trends(keywords=[keyword] if keyword else ["AI", "technology"], geo=geo)
    linkedin = await service.get_linkedin_trending() if settings.RAPIDAPI_KEY else []
    return {"google": google, "linkedin": linkedin}


@router.get("/trending/google")
async def get_google_trends(
    keyword: str = "AI",
    geo: str = "US",
    timeframe: str = "now 7-d",
    current_user: User = Depends(get_current_user),
):
    from app.services.trending_content_service import TrendingContentService
    service = TrendingContentService()
    return await service.get_google_trends(keywords=[keyword], timeframe=timeframe, geo=geo)


@router.get("/trending/linkedin")
async def get_linkedin_trends(
    category: Optional[str] = None,
    source: str = Query(default="all"),  # all | linkedin | hackernews | google_news
    query: str = Query(default="business technology linkedin"),
    current_user: User = Depends(get_current_user),
):
    """Return trending content. Uses RapidAPI LinkedIn if configured, otherwise Hacker News + Google News."""
    from app.services.trending_content_service import TrendingContentService
    import asyncio
    service = TrendingContentService()

    tasks = []
    # get-trending-feed requires a paid RapidAPI plan; only call it when explicitly requested
    if source == "linkedin" and settings.RAPIDAPI_KEY:
        tasks.append(service.get_linkedin_trending(category=category))
    if source in ("all", "hackernews"):
        tasks.append(service.get_hackernews_trending())
    if source in ("all", "google_news"):
        tasks.append(service.get_google_news_rss(query=query))

    if not tasks:
        tasks = [service.get_hackernews_trending(), service.get_google_news_rss(query=query)]

    results = await asyncio.gather(*tasks)
    items = [item for sublist in results for item in sublist]
    return {"items": items}


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@router.get("/analytics/overview")
def get_analytics_overview(
    days: int = 30,
    platform: Optional[str] = None,
    account_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    since = datetime.utcnow() - timedelta(days=days)
    q = db.query(SocialPost).filter(
        SocialPost.company_id == current_user.company_id,
        SocialPost.created_at >= since,
    )
    if platform:
        q = q.filter(SocialPost.platform == platform)
    if account_id:
        q = q.filter(SocialPost.social_account_id == account_id)
    posts = q.all()

    published = [p for p in posts if p.status == PostStatus.PUBLISHED]
    scheduled = [p for p in posts if p.status == PostStatus.SCHEDULED]

    total_likes = sum(p.likes for p in published)
    total_comments = sum(p.comments for p in published)
    total_shares = sum(p.shares for p in published)
    total_impressions = sum(p.impressions for p in published)
    total_engagements = total_likes + total_comments + total_shares
    engagement_rate = round((total_engagements / total_impressions * 100), 2) if total_impressions > 0 else 0

    return {
        "period_days": days,
        "total_posts": len(published),   # only count published so the KPI is meaningful
        "published_posts": len(published),
        "scheduled_posts": len(scheduled),
        "total_impressions": total_impressions,
        "total_engagements": total_engagements,
        "engagement_rate": engagement_rate,
        "total_likes": total_likes,
        "total_comments": total_comments,
        "total_shares": total_shares,
    }


@router.get("/analytics/posts")
def get_post_analytics(
    days: int = 30,
    platform: Optional[str] = None,
    account_id: Optional[int] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    since = datetime.utcnow() - timedelta(days=days)
    query = db.query(SocialPost).filter(
        SocialPost.company_id == current_user.company_id,
        SocialPost.status == PostStatus.PUBLISHED,
        SocialPost.published_at >= since,
    )
    if platform:
        query = query.filter(SocialPost.platform == platform)
    if account_id:
        query = query.filter(SocialPost.social_account_id == account_id)

    posts = query.order_by(SocialPost.impressions.desc()).limit(limit).all()
    return [
        {
            "id": p.id,
            "platform": p.platform,
            "content_preview": p.content[:100],
            "published_at": p.published_at,
            "likes": p.likes,
            "comments": p.comments,
            "shares": p.shares,
            "impressions": p.impressions,
            "engagement_rate": round(
                ((p.likes + p.comments + p.shares) / p.impressions * 100), 2
            ) if p.impressions > 0 else 0,
        }
        for p in posts
    ]


@router.post("/analytics/refresh/{post_id}")
async def refresh_post_analytics(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.social_publishing_service import SocialPublishingService
    post = db.query(SocialPost).filter(
        SocialPost.id == post_id,
        SocialPost.company_id == current_user.company_id,
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    service = SocialPublishingService()
    await service.refresh_analytics(db, post)
    db.refresh(post)
    return {"message": "Analytics refreshed", "post_id": post_id}


@router.get("/accounts/{account_id}/platform-posts")
async def get_platform_posts(
    account_id: int,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch posts published directly on the platform (LinkedIn etc.) via official API."""
    account = db.query(SocialAccount).filter(
        SocialAccount.id == account_id,
        SocialAccount.company_id == current_user.company_id,
        SocialAccount.status == SocialAccountStatus.ACTIVE,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    creds = json.loads(vault_service.decrypt(account.credentials))
    access_token = creds.get("access_token", "")
    if not access_token:
        raise HTTPException(status_code=400, detail="Account token missing. Please reconnect.")

    if account.platform == SocialPlatform.LINKEDIN:
        person_urn = f"urn:li:person:{account.account_id}"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # Use v2/ugcPosts — works with standard w_member_social OAuth scope
                resp = await client.get(
                    "https://api.linkedin.com/v2/ugcPosts",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "X-Restli-Protocol-Version": "2.0.0",
                    },
                    params={
                        "q": "authors",
                        "authors": f"List({person_urn})",
                        "count": min(limit, 50),
                        "sortBy": "LAST_MODIFIED",
                    },
                )
            if resp.status_code == 401:
                raise HTTPException(status_code=400, detail="LinkedIn token expired. Please reconnect your account.")
            if resp.status_code != 200:
                logger.warning(f"LinkedIn ugcPosts returned {resp.status_code}: {resp.text[:300]}")
                raise HTTPException(status_code=400, detail=f"LinkedIn API returned {resp.status_code}: {resp.text[:200]}")

            elements = resp.json().get("elements", [])
            posts = []
            for item in elements:
                share = (item.get("specificContent") or {}).get("com.linkedin.ugc.ShareContent", {})
                commentary = (share.get("shareCommentary") or {}).get("text", "") or ""
                post_urn = item.get("id", "")
                created_ms = item.get("created", {}).get("time", 0)
                created_at = datetime.utcfromtimestamp(created_ms / 1000).isoformat() if created_ms else None
                posts.append({
                    "id": post_urn,
                    "platform": "linkedin",
                    "content_preview": commentary[:150],
                    "published_at": created_at,
                    "likes": 0,
                    "comments": 0,
                    "shares": 0,
                    "impressions": 0,
                    "url": f"https://www.linkedin.com/feed/update/{post_urn}",
                    "source": "platform_direct",
                })

            # Fetch engagement stats for each post concurrently
            import asyncio as _asyncio
            import urllib.parse as _urlparse

            async def _fetch_stats(post_urn: str) -> dict:
                encoded = _urlparse.quote(post_urn, safe="")
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(
                        f"https://api.linkedin.com/v2/socialActions/{encoded}",
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "X-Restli-Protocol-Version": "2.0.0",
                        },
                    )
                if r.status_code == 200:
                    d = r.json()
                    return {
                        "likes":    d.get("likesSummary",    {}).get("totalLikes",                  0),
                        "comments": d.get("commentsSummary", {}).get("totalFirstLevelComments",     0),
                        "shares":   d.get("sharesSummary",   {}).get("totalShares",                 0),
                    }
                return {"likes": 0, "comments": 0, "shares": 0}

            stats_list = await _asyncio.gather(*[_fetch_stats(p["id"]) for p in posts], return_exceptions=True)
            for post, stats in zip(posts, stats_list):
                if isinstance(stats, dict):
                    post.update(stats)

            return {"posts": posts, "account_name": account.account_name, "platform": "linkedin"}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    raise HTTPException(status_code=400, detail=f"Platform post sync not yet supported for {account.platform}")
