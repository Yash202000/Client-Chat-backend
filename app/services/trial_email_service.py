"""Trial expiry and dunning email sequences."""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.company_subscription import CompanySubscription
from app.models.user import User

logger = logging.getLogger(__name__)


def _send_system_email(to_email: str, subject: str, html_body: str) -> bool:
    """Send via system SMTP. Returns True on success, False on failure (never raises)."""
    if not settings.SYSTEM_SMTP_HOST or not settings.SYSTEM_SMTP_FROM_EMAIL:
        logger.debug("System SMTP not configured — skipping email to %s", to_email)
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        from_address = (
            f"{settings.SYSTEM_SMTP_FROM_NAME} <{settings.SYSTEM_SMTP_FROM_EMAIL}>"
            if settings.SYSTEM_SMTP_FROM_NAME
            else settings.SYSTEM_SMTP_FROM_EMAIL
        )
        msg["From"] = from_address
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html"))
        port = int(settings.SYSTEM_SMTP_PORT or 587)
        with smtplib.SMTP(settings.SYSTEM_SMTP_HOST, port) as smtp:
            smtp.ehlo()
            smtp.starttls()
            if settings.SYSTEM_SMTP_USER and settings.SYSTEM_SMTP_PASSWORD:
                smtp.login(settings.SYSTEM_SMTP_USER, settings.SYSTEM_SMTP_PASSWORD)
            smtp.sendmail(settings.SYSTEM_SMTP_FROM_EMAIL, to_email, msg.as_string())
        logger.info("Sent email '%s' to %s", subject, to_email)
        return True
    except Exception as e:
        logger.error("Failed to send email to %s: %s", to_email, e)
        return False


def _get_admin_email(db: Session, company_id: int) -> str | None:
    """Get the email of the company owner / first admin."""
    user = (
        db.query(User)
        .filter(User.company_id == company_id, User.is_active == True)
        .order_by(User.id)
        .first()
    )
    return user.email if user else None


# ── Trial email templates ──────────────────────────────────────────────────

def _trial_welcome_html(name: str, trial_end: str) -> str:
    return f"""
<p>Hi {name or "there"},</p>
<p>Welcome to <strong>HeyGenAlly</strong>! Your 14-day free trial is now active.</p>
<p>Your trial ends on <strong>{trial_end}</strong>. Here's what you can do right now:</p>
<ul>
  <li>Create your first AI agent</li>
  <li>Connect a channel (WhatsApp, Email, Web Chat)</li>
  <li>Upload knowledge base documents</li>
</ul>
<p><a href="https://app.heygenally.com/dashboard">Go to your dashboard &rarr;</a></p>
<p>The HeyGenAlly Team</p>
"""

def _trial_day7_html(name: str, days_left: int) -> str:
    return f"""
<p>Hi {name or "there"},</p>
<p>You're halfway through your free trial — <strong>{days_left} days left</strong>.</p>
<p>Have you connected your first channel yet? Teams that connect a channel in the first week see 3x better results.</p>
<p><a href="https://app.heygenally.com/dashboard">Continue building &rarr;</a></p>
<p>The HeyGenAlly Team</p>
"""

def _trial_day12_html(name: str) -> str:
    return f"""
<p>Hi {name or "there"},</p>
<p>Your trial ends in <strong>2 days</strong>. Don't lose your agents, contacts, and conversations.</p>
<p>Upgrade now to keep everything and unlock the full platform.</p>
<p><a href="https://app.heygenally.com/dashboard/billing">Choose a plan &rarr;</a></p>
<p>The HeyGenAlly Team</p>
"""

def _trial_expired_html(name: str) -> str:
    return f"""
<p>Hi {name or "there"},</p>
<p>Your HeyGenAlly free trial has ended. Your data is safe — we'll hold it for 30 days.</p>
<p>Upgrade now to restore full access instantly.</p>
<p><a href="https://app.heygenally.com/dashboard/billing">Reactivate your account &rarr;</a></p>
<p>The HeyGenAlly Team</p>
"""

# ── Dunning email templates ────────────────────────────────────────────────

def _dunning_attempt1_html(name: str) -> str:
    return f"""
<p>Hi {name or "there"},</p>
<p>We couldn't process your payment for HeyGenAlly. Your account is still active while we retry.</p>
<p>Please update your payment method to avoid any interruption.</p>
<p><a href="https://app.heygenally.com/dashboard/billing">Update payment &rarr;</a></p>
<p>The HeyGenAlly Team</p>
"""

def _dunning_attempt2_html(name: str) -> str:
    return f"""
<p>Hi {name or "there"},</p>
<p>We tried again but your payment is still failing. Please update your card details today.</p>
<p><a href="https://app.heygenally.com/dashboard/billing">Update payment &rarr;</a></p>
<p>The HeyGenAlly Team</p>
"""

def _dunning_final_html(name: str) -> str:
    return f"""
<p>Hi {name or "there"},</p>
<p>After 3 failed payment attempts, your HeyGenAlly subscription has been paused. Your data is safe.</p>
<p>Update your payment method to restore access immediately.</p>
<p><a href="https://app.heygenally.com/dashboard/billing">Restore access &rarr;</a></p>
<p>The HeyGenAlly Team</p>
"""

# ── Scheduler functions ────────────────────────────────────────────────────

def run_trial_email_scheduler(db: Session) -> None:
    """Called daily. Sends trial lifecycle emails based on days elapsed."""
    now = datetime.utcnow()
    subs = (
        db.query(CompanySubscription)
        .filter(
            CompanySubscription.status == "trial",
            CompanySubscription.trial_end_date.isnot(None),
        )
        .all()
    )
    for sub in subs:
        try:
            email = _get_admin_email(db, sub.company_id)
            if not email:
                continue
            trial_start = sub.trial_start_date or sub.created_at
            if not trial_start:
                continue
            days_elapsed = (now - trial_start).days
            days_left = max(0, (sub.trial_end_date - now).days)

            # Day 0-1: welcome email
            if days_elapsed <= 1 and not sub.trial_welcome_sent:
                sent = _send_system_email(
                    email,
                    "Welcome to HeyGenAlly — your trial has started!",
                    _trial_welcome_html(email.split("@")[0], sub.trial_end_date.strftime("%B %d, %Y")),
                )
                if sent:
                    sub.trial_welcome_sent = True
                    db.commit()

            # Day 7
            elif days_elapsed >= 7 and not sub.trial_day7_sent:
                sent = _send_system_email(
                    email,
                    f"Your HeyGenAlly trial: {days_left} days left",
                    _trial_day7_html(email.split("@")[0], days_left),
                )
                if sent:
                    sub.trial_day7_sent = True
                    db.commit()

            # Day 12
            elif days_elapsed >= 12 and not sub.trial_day12_sent:
                sent = _send_system_email(
                    email,
                    "2 days left on your HeyGenAlly trial",
                    _trial_day12_html(email.split("@")[0]),
                )
                if sent:
                    sub.trial_day12_sent = True
                    db.commit()

            # Expired (day 14+, status still trial or grace)
            elif now > sub.trial_end_date and not sub.trial_expiry_sent:
                sent = _send_system_email(
                    email,
                    "Your HeyGenAlly trial has ended",
                    _trial_expired_html(email.split("@")[0]),
                )
                if sent:
                    sub.trial_expiry_sent = True
                    db.commit()

        except Exception as e:
            logger.error("Trial email error for company %s: %s", sub.company_id, e)


def run_dunning_email_scheduler(db: Session) -> None:
    """Called daily. Sends dunning emails for past_due subscriptions."""
    now = datetime.utcnow()
    subs = (
        db.query(CompanySubscription)
        .filter(CompanySubscription.status == "past_due")
        .all()
    )
    for sub in subs:
        try:
            email = _get_admin_email(db, sub.company_id)
            if not email:
                continue

            last_sent = sub.last_dunning_sent_at

            # Attempt 1: immediately when past_due
            if not sub.dunning_attempt_1_sent:
                sent = _send_system_email(
                    email,
                    "Action required: payment failed for HeyGenAlly",
                    _dunning_attempt1_html(email.split("@")[0]),
                )
                if sent:
                    sub.dunning_attempt_1_sent = True
                    sub.last_dunning_sent_at = now
                    db.commit()

            # Attempt 2: 3 days after attempt 1
            elif not sub.dunning_attempt_2_sent and last_sent and (now - last_sent).days >= 3:
                sent = _send_system_email(
                    email,
                    "Second notice: payment still failing — HeyGenAlly",
                    _dunning_attempt2_html(email.split("@")[0]),
                )
                if sent:
                    sub.dunning_attempt_2_sent = True
                    sub.last_dunning_sent_at = now
                    db.commit()

            # Attempt 3: 7 days after attempt 2
            elif not sub.dunning_attempt_3_sent and last_sent and (now - last_sent).days >= 7:
                sent = _send_system_email(
                    email,
                    "Final notice: your HeyGenAlly subscription is paused",
                    _dunning_final_html(email.split("@")[0]),
                )
                if sent:
                    sub.dunning_attempt_3_sent = True
                    sub.last_dunning_sent_at = now
                    db.commit()

        except Exception as e:
            logger.error("Dunning email error for company %s: %s", sub.company_id, e)
