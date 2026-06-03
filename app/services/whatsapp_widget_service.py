import secrets
from typing import Optional, List
from sqlalchemy.orm import Session
from app.models.whatsapp_widget import WhatsAppWidget


def _generate_key() -> str:
    return secrets.token_urlsafe(16)


def create_widget(
    db: Session,
    company_id: int,
    name: str,
    phone_number: str,
    prefill_message: Optional[str] = None,
    greeting_text: str = "Chat with us on WhatsApp!",
    subtext: str = "Typically replies within minutes",
    button_label: str = "Chat on WhatsApp",
    button_color: str = "#25D366",
    button_text_color: str = "#FFFFFF",
    position: str = "bottom-right",
    show_tooltip: bool = True,
    show_agent_avatar: bool = False,
    agent_avatar_url: Optional[str] = None,
    agent_name: Optional[str] = None,
) -> WhatsAppWidget:
    widget = WhatsAppWidget(
        widget_key=_generate_key(),
        company_id=company_id,
        name=name,
        phone_number=phone_number,
        prefill_message=prefill_message,
        greeting_text=greeting_text,
        subtext=subtext,
        button_label=button_label,
        button_color=button_color,
        button_text_color=button_text_color,
        position=position,
        show_tooltip=show_tooltip,
        show_agent_avatar=show_agent_avatar,
        agent_avatar_url=agent_avatar_url,
        agent_name=agent_name,
    )
    db.add(widget)
    db.commit()
    db.refresh(widget)
    return widget


def get_widget(db: Session, widget_id: int, company_id: int) -> Optional[WhatsAppWidget]:
    return db.query(WhatsAppWidget).filter(
        WhatsAppWidget.id == widget_id,
        WhatsAppWidget.company_id == company_id,
    ).first()


def get_widget_by_key(db: Session, widget_key: str) -> Optional[WhatsAppWidget]:
    return db.query(WhatsAppWidget).filter(
        WhatsAppWidget.widget_key == widget_key,
        WhatsAppWidget.is_active == True,
    ).first()


def list_widgets(db: Session, company_id: int) -> List[WhatsAppWidget]:
    return db.query(WhatsAppWidget).filter(
        WhatsAppWidget.company_id == company_id,
    ).order_by(WhatsAppWidget.id.desc()).all()


def update_widget(db: Session, widget_id: int, company_id: int, **kwargs) -> Optional[WhatsAppWidget]:
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


def build_wa_url(widget: WhatsAppWidget) -> str:
    """Construct the wa.me deep link."""
    phone = widget.phone_number.replace("+", "").replace(" ", "").replace("-", "")
    url = f"https://wa.me/{phone}"
    if widget.prefill_message:
        import urllib.parse
        url += f"?text={urllib.parse.quote(widget.prefill_message)}"
    return url


def build_embed_snippet(widget: WhatsAppWidget, backend_url: str) -> str:
    """Return the HTML snippet the customer pastes on their site."""
    return (
        f'<!-- WhatsApp Widget by HeyGenAlly -->\n'
        f'<script src="{backend_url}/api/v1/public/wa-widget/script/{widget.widget_key}.js" async></script>'
    )
