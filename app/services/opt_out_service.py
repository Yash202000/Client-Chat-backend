"""
Opt-out / opt-in service.

Handles keyword detection and contact preference updates for broadcast
messaging compliance.
"""
import datetime
from sqlalchemy.orm import Session
from app.models.contact import Contact, OptInStatus

OPT_OUT_KEYWORDS = {"stop", "unsubscribe", "optout", "opt out", "opt-out", "cancel", "end", "quit"}
OPT_IN_KEYWORDS  = {"start", "subscribe", "optin", "opt in", "opt-in", "yes", "unstop"}


def is_opt_out_message(text: str) -> bool:
    """Return True if the message text is a recognised opt-out keyword."""
    return text.strip().lower() in OPT_OUT_KEYWORDS


def is_opt_in_message(text: str) -> bool:
    """Return True if the message text is a recognised opt-in keyword."""
    return text.strip().lower() in OPT_IN_KEYWORDS


def opt_out_contact(db: Session, company_id: int, phone_number: str) -> bool:
    """Mark contact as opted-out. Returns True if a contact was found and updated."""
    contact = db.query(Contact).filter(
        Contact.company_id == company_id,
        Contact.phone_number == phone_number,
    ).first()
    if contact and contact.opt_in_status != OptInStatus.OPTED_OUT:
        contact.opt_in_status = OptInStatus.OPTED_OUT
        contact.opt_out_date = datetime.datetime.utcnow()
        db.commit()
        return True
    return False


def opt_in_contact(db: Session, company_id: int, phone_number: str) -> bool:
    """Re-subscribe a previously opted-out contact. Returns True if updated."""
    contact = db.query(Contact).filter(
        Contact.company_id == company_id,
        Contact.phone_number == phone_number,
    ).first()
    if contact and contact.opt_in_status == OptInStatus.OPTED_OUT:
        contact.opt_in_status = OptInStatus.OPTED_IN
        contact.opt_in_date = datetime.datetime.utcnow()
        db.commit()
        return True
    return False
