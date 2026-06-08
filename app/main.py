from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.core.limiter import limiter
import uvicorn
import os
import sentry_sdk
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.database import Base, engine, SessionLocal
from app.models import role, permission, contact, comment, otp_verification, cod_verification, whatsapp_widget, ctwa_link, broadcast, webhook_delivery_log, api_key_log, short_link, social_widget, cts_link # Import new models
from app.core.config import settings

# Sentry init - only if DSN configured
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=0.1,
        environment=settings.ENVIRONMENT if hasattr(settings, 'ENVIRONMENT') else 'production',
    )
from app.api.v1.main import api_router, websocket_router
from app.api.v1.endpoints import ws_updates, comments, gmail, google, published, ai_images, ai_chat, public_pages
from app.core.dependencies import get_db
from app.core.license_exceptions import LicenseError, license_exception_handler
from app.services.connection_manager import manager
from app.services.websocket_cleanup_service import cleanup_inactive_sessions
from app.services.call_timeout_service import call_timeout_service
from app.services import tool_service, widget_settings_service
from app.schemas import widget_settings as schemas_widget_settings
from create_tool import create_api_call_tool
import asyncio

# Create all database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

# Rate limiting — limiter instance lives in app.core.limiter to avoid circular imports
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Register license exception handler (shows HTML page for browser, JSON for API)
app.add_exception_handler(LicenseError, license_exception_handler)

# CORS middleware to allow frontend to connect
# Note: Widget needs to be accessible from any origin
# Parse CORS origins from comma-separated string in settings
cors_origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# ---------------------------------------------------------------------------
# Maintenance mode middleware
# Paths listed here bypass the 503 gate so health checks and super-admin
# toggle endpoints remain reachable even when maintenance mode is active.
# ---------------------------------------------------------------------------
MAINTENANCE_EXEMPT_PREFIXES = [
    "/api/v1/health",
    "/api/v1/system/",
    "/docs",
    "/redoc",
    "/openapi.json",
]


class MaintenanceModeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if settings.MAINTENANCE_MODE:
            path = request.url.path
            if not any(path.startswith(p) for p in MAINTENANCE_EXEMPT_PREFIXES):
                return JSONResponse(
                    {
                        "detail": (
                            "HeyGenAlly is under maintenance. "
                            "We'll be back shortly. Follow @HeyGenAlly for updates."
                        )
                    },
                    status_code=503,
                    headers={"Retry-After": "300"},
                )
        return await call_next(request)


app.add_middleware(MaintenanceModeMiddleware)

app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(ws_updates.router, prefix="/ws") # New company-wide updates
app.include_router(comments.router, prefix="/api/v1/comments")
app.include_router(gmail.router, prefix="/api/v1/gmail")
app.include_router(google.router, prefix="/api/v1/google")
app.include_router(published.router, prefix="/api/v1/published")
app.include_router(ai_images.router, prefix="/api/v1/ai-images", tags=["ai-images"])
app.include_router(ai_chat.router, prefix="/api/v1/ai-chat", tags=["ai-chat"])
app.include_router(public_pages.router, tags=["public-pages"])  # Public pages (privacy policy, terms) at root

# Mount static files for serving the widget
widget_static_path = os.path.join(os.path.dirname(__file__), "static", "widget")
if os.path.exists(widget_static_path):
    app.mount("/widget", StaticFiles(directory=widget_static_path), name="widget")

@app.get("/")
async def read_root():
    return {"message": "HeyGenAlly backend is running"}


from app.initial_data import create_initial_data
from app.services.builtin_tools_service import seed_builtin_tools

# Initialize scheduler for background tasks
scheduler = AsyncIOScheduler()

async def run_campaign_scheduler():
    """Wrapper to run the campaign scheduler with a fresh DB session"""
    from app.services import campaign_execution_service
    db = SessionLocal()
    try:
        await campaign_execution_service.process_all_scheduled_campaigns(db)
    finally:
        db.close()


async def run_whatsapp_token_refresh():
    """Wrapper to run the WhatsApp token refresh with a fresh DB session"""
    from app.services.whatsapp_token_refresh_service import run_whatsapp_token_refresh_scheduler
    await run_whatsapp_token_refresh_scheduler()


async def run_social_post_scheduler():
    """Publish any social posts whose scheduled_at has passed."""
    from app.services.social_publishing_service import SocialPublishingService
    db = SessionLocal()
    try:
        service = SocialPublishingService()
        due_posts = await service.get_posts_due_for_publishing(db)
        for post in due_posts:
            try:
                await service.publish_post_to_platform(db, post)
            except Exception as e:
                print(f"[SocialScheduler] Failed to publish post {post.id}: {e}")
    finally:
        db.close()


async def run_webhook_retry_job():
    """Retry failed outbound webhooks whose next_retry_at has passed."""
    from app.services.webhook_delivery_service import retry_failed_webhooks
    db = SessionLocal()
    try:
        await retry_failed_webhooks(db)
    except Exception as e:
        print(f"[WebhookRetry] Unexpected error in retry job: {e}")
    finally:
        db.close()


async def run_broadcast_scheduler():
    """Fire any broadcasts whose scheduled_at has passed and status is SCHEDULED."""
    from app.models.broadcast import Broadcast, BroadcastStatus
    from app.services.broadcast_service import send_broadcast
    from datetime import datetime
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        due = db.query(Broadcast).filter(
            Broadcast.status == BroadcastStatus.SCHEDULED,
            Broadcast.scheduled_at <= now,
        ).all()
        for b in due:
            asyncio.create_task(send_broadcast(db, b.id, b.company_id))
    finally:
        db.close()


@app.on_event("startup")
async def on_startup():
    create_initial_data()

    # Seed built-in tools (idempotent)
    db = SessionLocal()
    try:
        seed_builtin_tools(db)
    finally:
        db.close()

    # Start WebSocket cleanup scheduler if enabled
    if settings.WS_ENABLE_HEARTBEAT:
        scheduler.add_job(
            cleanup_inactive_sessions,
            'interval',
            seconds=settings.WS_CLEANUP_INTERVAL,
            args=[manager],
            id='websocket_cleanup',
            replace_existing=True
        )
        print(f"[Startup] WebSocket cleanup scheduler started (interval: {settings.WS_CLEANUP_INTERVAL}s)")
        print(f"[Startup] Preview session timeout: {settings.WS_PREVIEW_SESSION_TIMEOUT}s")
        print(f"[Startup] Regular session timeout: {settings.WS_REGULAR_SESSION_TIMEOUT}s")
    else:
        print("[Startup] WebSocket heartbeat disabled (WS_ENABLE_HEARTBEAT=False)")

    # Add campaign scheduler job - runs every 30 seconds to process scheduled campaigns
    scheduler.add_job(
        run_campaign_scheduler,
        'interval',
        seconds=30,
        id='campaign_scheduler',
        replace_existing=True
    )
    print("[Startup] Campaign scheduler started (interval: 30s)")

    # Add WhatsApp token refresh job - runs every hour to refresh expiring tokens
    scheduler.add_job(
        run_whatsapp_token_refresh,
        'interval',
        hours=1,
        id='whatsapp_token_refresh',
        replace_existing=True
    )
    print("[Startup] WhatsApp token refresh scheduler started (interval: 1 hour)")

    # Social post publishing scheduler — runs every minute to publish scheduled posts
    scheduler.add_job(
        run_social_post_scheduler,
        'interval',
        minutes=1,
        id='social_post_scheduler',
        replace_existing=True
    )
    print("[Startup] Social post scheduler started (interval: 1 min)")

    # Broadcast scheduler — runs every minute to fire due scheduled broadcasts
    scheduler.add_job(
        run_broadcast_scheduler,
        'interval',
        minutes=1,
        id='broadcast_scheduler',
        replace_existing=True,
    )
    print("[Startup] Broadcast scheduler started (interval: 1 min)")

    # Calendar reminders — runs every minute to push WS notifications to users
    from app.services.calendar_reminder_service import run_calendar_reminder_scheduler
    scheduler.add_job(
        run_calendar_reminder_scheduler,
        'interval',
        minutes=1,
        id='calendar_reminder_scheduler',
        replace_existing=True,
    )
    print("[Startup] Calendar reminder scheduler started (interval: 1 min)")

    # Queue overflow / SLA checker — runs every 30s
    from app.services.queue_overflow_service import run_queue_overflow_check
    scheduler.add_job(
        run_queue_overflow_check,
        'interval',
        seconds=30,
        id='queue_overflow_check',
        replace_existing=True,
    )
    print("[Startup] Queue overflow/SLA checker started (interval: 30s)")

    # Trial expiry email sequence — runs daily at 9am UTC
    async def run_trial_email_job():
        from app.services.trial_email_service import run_trial_email_scheduler
        db = SessionLocal()
        try:
            run_trial_email_scheduler(db)
        finally:
            db.close()

    async def run_dunning_email_job():
        from app.services.trial_email_service import run_dunning_email_scheduler
        db = SessionLocal()
        try:
            run_dunning_email_scheduler(db)
        finally:
            db.close()

    scheduler.add_job(run_trial_email_job, 'cron', hour=9, minute=0, id='trial_email_scheduler', replace_existing=True)
    scheduler.add_job(run_dunning_email_job, 'cron', hour=9, minute=30, id='dunning_email_scheduler', replace_existing=True)
    print("[Startup] Trial and dunning email schedulers started (daily at 9:00 and 9:30 UTC)")

    # Webhook retry scheduler — runs every 5 minutes to retry failed outbound deliveries
    scheduler.add_job(
        run_webhook_retry_job,
        'interval',
        minutes=5,
        id='webhook_retry_scheduler',
        replace_existing=True,
    )
    print("[Startup] Webhook retry scheduler started (interval: 5 min)")

    # Start the scheduler if not already started
    if not scheduler.running:
        scheduler.start()

    # Start call timeout service
    asyncio.create_task(call_timeout_service.start())
    print("[Startup] Call timeout service started (timeout: 30s, check interval: 10s)")

@app.on_event("shutdown")
async def on_shutdown():
    print("Server is shutting down...")

    # Stop call timeout service
    call_timeout_service.stop()
    print("[Shutdown] Call timeout service stopped")

    # Shutdown scheduler
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("[Shutdown] Scheduler stopped")

    # Disconnect all WebSocket clients
    await manager.disconnect_all()
    print("[Shutdown] All WebSocket clients disconnected")

if __name__ == "__main__":
    uvicorn.run(app, host=settings.HOST, port=settings.PORT, ws="websockets")