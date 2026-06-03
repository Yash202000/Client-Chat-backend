"""
Communications Analytics endpoint

GET /comms-analytics/summary   — overall KPIs
GET /comms-analytics/otp       — OTP stats by channel
GET /comms-analytics/broadcast — broadcast performance
GET /comms-analytics/ctwa      — CTWA funnel
GET /comms-analytics/cod       — COD confirmation rates
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.models.otp_verification import OTPVerification, OTPStatus, OTPChannel
from app.models.broadcast import Broadcast, BroadcastStatus
from app.models.ctwa_link import CTWALink, CTWAClick
from app.models.cod_verification import CODVerification, CODStatus
from app.models.whatsapp_widget import WhatsAppWidget

router = APIRouter()
logger = logging.getLogger(__name__)


def _date_filter(model, days: int):
    since = datetime.utcnow() - timedelta(days=days)
    if hasattr(model, 'created_at'):
        return model.created_at >= since
    return None


@router.get("/summary")
def get_summary(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    """Top-level KPI summary across all communication features."""
    since = datetime.utcnow() - timedelta(days=days)

    # OTP
    otp_total = db.query(func.count(OTPVerification.id)).filter(
        OTPVerification.company_id == x_company_id,
        OTPVerification.created_at >= since,
    ).scalar() or 0

    otp_verified = db.query(func.count(OTPVerification.id)).filter(
        OTPVerification.company_id == x_company_id,
        OTPVerification.created_at >= since,
        OTPVerification.status == OTPStatus.VERIFIED,
    ).scalar() or 0

    # Broadcasts
    broadcasts_total = db.query(func.count(Broadcast.id)).filter(
        Broadcast.company_id == x_company_id,
        Broadcast.created_at >= since,
    ).scalar() or 0

    broadcasts_sent = db.query(func.sum(Broadcast.sent_count)).filter(
        Broadcast.company_id == x_company_id,
        Broadcast.created_at >= since,
        Broadcast.status == BroadcastStatus.COMPLETED,
    ).scalar() or 0

    # CTWA
    ctwa_clicks = db.query(func.sum(CTWALink.click_count)).filter(
        CTWALink.company_id == x_company_id,
    ).scalar() or 0

    ctwa_contacts = db.query(func.sum(CTWALink.contact_count)).filter(
        CTWALink.company_id == x_company_id,
    ).scalar() or 0

    # COD
    cod_total = db.query(func.count(CODVerification.id)).filter(
        CODVerification.company_id == x_company_id,
        CODVerification.created_at >= since,
    ).scalar() or 0

    cod_confirmed = db.query(func.count(CODVerification.id)).filter(
        CODVerification.company_id == x_company_id,
        CODVerification.created_at >= since,
        CODVerification.status == CODStatus.CONFIRMED,
    ).scalar() or 0

    # Widgets
    widget_count = db.query(func.count(WhatsAppWidget.id)).filter(
        WhatsAppWidget.company_id == x_company_id,
        WhatsAppWidget.is_active == True,
    ).scalar() or 0

    otp_rate = round((otp_verified / otp_total * 100), 1) if otp_total else 0
    ctwa_rate = round((ctwa_contacts / ctwa_clicks * 100), 1) if ctwa_clicks else 0
    cod_rate = round((cod_confirmed / cod_total * 100), 1) if cod_total else 0

    return {
        "period_days": days,
        "otp": {
            "total_sent": otp_total,
            "verified": otp_verified,
            "verification_rate": otp_rate,
        },
        "broadcast": {
            "total_broadcasts": broadcasts_total,
            "total_messages_sent": int(broadcasts_sent),
        },
        "ctwa": {
            "total_clicks": int(ctwa_clicks),
            "contacts_created": int(ctwa_contacts),
            "conversion_rate": ctwa_rate,
        },
        "cod": {
            "total_sent": cod_total,
            "confirmed": cod_confirmed,
            "confirmation_rate": cod_rate,
        },
        "widgets": {
            "active_widgets": widget_count,
        },
    }


@router.get("/otp")
def get_otp_stats(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    """OTP breakdown by channel and status."""
    since = datetime.utcnow() - timedelta(days=days)

    rows = db.query(
        OTPVerification.channel,
        OTPVerification.status,
        func.count(OTPVerification.id).label("count"),
    ).filter(
        OTPVerification.company_id == x_company_id,
        OTPVerification.created_at >= since,
    ).group_by(OTPVerification.channel, OTPVerification.status).all()

    by_channel: dict = {}
    for channel, status, count in rows:
        ch = channel.value if hasattr(channel, 'value') else str(channel)
        st = status.value if hasattr(status, 'value') else str(status)
        if ch not in by_channel:
            by_channel[ch] = {"total": 0, "verified": 0, "expired": 0, "failed": 0}
        by_channel[ch]["total"] += count
        by_channel[ch][st] = by_channel[ch].get(st, 0) + count

    # Add rate
    for ch, data in by_channel.items():
        total = data["total"]
        data["verification_rate"] = round(data.get("verified", 0) / total * 100, 1) if total else 0

    # Daily trend (last N days)
    daily = db.query(
        func.date_trunc('day', OTPVerification.created_at).label("day"),
        func.count(OTPVerification.id).label("sent"),
        func.sum(case((OTPVerification.status == OTPStatus.VERIFIED, 1), else_=0)).label("verified"),
    ).filter(
        OTPVerification.company_id == x_company_id,
        OTPVerification.created_at >= since,
    ).group_by("day").order_by("day").all()

    return {
        "period_days": days,
        "by_channel": by_channel,
        "daily_trend": [
            {"date": str(d.day)[:10], "sent": d.sent, "verified": int(d.verified or 0)}
            for d in daily
        ],
    }


@router.get("/broadcast")
def get_broadcast_stats(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    """Broadcast performance metrics."""
    since = datetime.utcnow() - timedelta(days=days)

    broadcasts = db.query(Broadcast).filter(
        Broadcast.company_id == x_company_id,
        Broadcast.created_at >= since,
    ).order_by(Broadcast.created_at.desc()).all()

    total_sent = sum(b.sent_count or 0 for b in broadcasts)
    total_failed = sum(b.failed_count or 0 for b in broadcasts)
    total_contacts = sum(b.total_contacts or 0 for b in broadcasts)
    delivery_rate = round(total_sent / total_contacts * 100, 1) if total_contacts else 0

    by_channel = {}
    for b in broadcasts:
        ch = b.channel.value
        if ch not in by_channel:
            by_channel[ch] = {"broadcasts": 0, "sent": 0, "failed": 0}
        by_channel[ch]["broadcasts"] += 1
        by_channel[ch]["sent"] += b.sent_count or 0
        by_channel[ch]["failed"] += b.failed_count or 0

    return {
        "period_days": days,
        "total_broadcasts": len(broadcasts),
        "total_messages_sent": total_sent,
        "total_failed": total_failed,
        "delivery_rate": delivery_rate,
        "by_channel": by_channel,
        "recent": [
            {
                "id": b.id, "name": b.name, "channel": b.channel.value,
                "status": b.status.value, "sent_count": b.sent_count or 0,
                "total_contacts": b.total_contacts or 0,
                "created_at": b.created_at.isoformat(),
            }
            for b in broadcasts[:10]
        ],
    }


@router.get("/ctwa")
def get_ctwa_stats(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    """CTWA funnel and per-link breakdown."""
    since = datetime.utcnow() - timedelta(days=days)

    links = db.query(CTWALink).filter(CTWALink.company_id == x_company_id).all()

    # Recent clicks
    recent_clicks = db.query(
        func.date_trunc('day', CTWAClick.clicked_at).label("day"),
        func.count(CTWAClick.id).label("clicks"),
        func.sum(case((CTWAClick.converted_at != None, 1), else_=0)).label("converted"),
    ).filter(
        CTWAClick.company_id == x_company_id,
        CTWAClick.clicked_at >= since,
    ).group_by("day").order_by("day").all()

    total_clicks = sum(l.click_count or 0 for l in links)
    total_contacts = sum(l.contact_count or 0 for l in links)

    return {
        "period_days": days,
        "total_links": len(links),
        "total_clicks": total_clicks,
        "total_contacts_created": total_contacts,
        "overall_conversion_rate": round(total_contacts / total_clicks * 100, 1) if total_clicks else 0,
        "daily_trend": [
            {"date": str(r.day)[:10], "clicks": r.clicks, "converted": int(r.converted or 0)}
            for r in recent_clicks
        ],
        "top_links": sorted(
            [{"name": l.name, "clicks": l.click_count or 0, "contacts": l.contact_count or 0, "is_active": l.is_active} for l in links],
            key=lambda x: x["clicks"], reverse=True
        )[:5],
    }


@router.get("/cod")
def get_cod_stats(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    x_company_id: int = Header(...),
):
    """COD verification funnel."""
    since = datetime.utcnow() - timedelta(days=days)

    rows = db.query(
        CODVerification.status,
        CODVerification.channel,
        func.count(CODVerification.id).label("count"),
    ).filter(
        CODVerification.company_id == x_company_id,
        CODVerification.created_at >= since,
    ).group_by(CODVerification.status, CODVerification.channel).all()

    totals: dict = {"total": 0, "confirmed": 0, "cancelled": 0, "expired": 0, "failed": 0, "pending": 0}
    by_channel: dict = {}

    for status, channel, count in rows:
        st = status.value if hasattr(status, 'value') else str(status)
        ch = channel.value if hasattr(channel, 'value') else str(channel)
        totals["total"] += count
        totals[st] = totals.get(st, 0) + count
        if ch not in by_channel:
            by_channel[ch] = {"total": 0}
        by_channel[ch]["total"] += count
        by_channel[ch][st] = by_channel[ch].get(st, 0) + count

    total = totals["total"]
    return {
        "period_days": days,
        "total": total,
        "confirmed": totals.get("confirmed", 0),
        "cancelled": totals.get("cancelled", 0),
        "expired": totals.get("expired", 0),
        "confirmation_rate": round(totals.get("confirmed", 0) / total * 100, 1) if total else 0,
        "cancellation_rate": round(totals.get("cancelled", 0) / total * 100, 1) if total else 0,
        "by_channel": by_channel,
    }
