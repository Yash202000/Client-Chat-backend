import secrets
import urllib.parse
from typing import Optional, List
from sqlalchemy.orm import Session
from app.models.social_widget import SocialWidget


CHANNEL_DEFAULTS = {
    "instagram": {
        "greeting_text": "DM us on Instagram!",
        "subtext": "We reply to every message",
        "button_label": "Message on Instagram",
        "button_color": "#E1306C",
    },
    "telegram": {
        "greeting_text": "Chat with us on Telegram!",
        "subtext": "Typically replies within minutes",
        "button_label": "Open Telegram",
        "button_color": "#26A5E4",
    },
    "messenger": {
        "greeting_text": "Message us on Messenger!",
        "subtext": "We usually reply quickly",
        "button_label": "Chat on Messenger",
        "button_color": "#0078FF",
    },
}


def _generate_key() -> str:
    return secrets.token_urlsafe(16)


def build_channel_url(widget: SocialWidget) -> str:
    handle = widget.handle.lstrip("@")
    if widget.channel == "instagram":
        return f"https://ig.me/m/{handle}"
    if widget.channel == "telegram":
        return f"https://t.me/{handle}"
    if widget.channel == "messenger":
        return f"https://m.me/{handle}"
    return "#"


def build_embed_snippet(widget: SocialWidget, backend_url: str) -> str:
    return (
        f"<!-- {widget.channel.title()} Widget by HeyGenAlly -->\n"
        f'<script src="{backend_url}/api/v1/public/social-widget/script/{widget.widget_key}.js" async></script>'
    )


def create_widget(db: Session, company_id: int, channel: str, name: str, handle: str, **kwargs) -> SocialWidget:
    defaults = CHANNEL_DEFAULTS.get(channel, {})
    widget = SocialWidget(
        widget_key=_generate_key(),
        company_id=company_id,
        channel=channel,
        name=name,
        handle=handle,
        greeting_text=kwargs.pop("greeting_text", defaults.get("greeting_text", "Chat with us!")),
        subtext=kwargs.pop("subtext", defaults.get("subtext", "Typically replies within minutes")),
        button_label=kwargs.pop("button_label", defaults.get("button_label", "Chat now")),
        button_color=kwargs.pop("button_color", defaults.get("button_color", "#000000")),
        **kwargs,
    )
    db.add(widget)
    db.commit()
    db.refresh(widget)
    return widget


def get_widget(db: Session, widget_id: int, company_id: int) -> Optional[SocialWidget]:
    return db.query(SocialWidget).filter(
        SocialWidget.id == widget_id,
        SocialWidget.company_id == company_id,
    ).first()


def get_widget_by_key(db: Session, widget_key: str) -> Optional[SocialWidget]:
    return db.query(SocialWidget).filter(
        SocialWidget.widget_key == widget_key,
        SocialWidget.is_active == True,
    ).first()


def list_widgets(db: Session, company_id: int, channel: Optional[str] = None) -> List[SocialWidget]:
    q = db.query(SocialWidget).filter(SocialWidget.company_id == company_id)
    if channel:
        q = q.filter(SocialWidget.channel == channel)
    return q.order_by(SocialWidget.id.desc()).all()


def update_widget(db: Session, widget_id: int, company_id: int, **kwargs) -> Optional[SocialWidget]:
    widget = get_widget(db, widget_id, company_id)
    if not widget:
        return None
    for key, value in kwargs.items():
        if hasattr(widget, key) and value is not None:
            setattr(widget, key, value)
    db.commit()
    db.refresh(widget)
    return widget


def delete_widget(db: Session, widget_id: int, company_id: int) -> bool:
    widget = get_widget(db, widget_id, company_id)
    if not widget:
        return False
    db.delete(widget)
    db.commit()
    return True
