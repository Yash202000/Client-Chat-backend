"""
Re-create LiveKit SIP trunks + dispatch rules for every active contact-centre number.

Use after resetting LiveKit/Redis, or when moving to a new LiveKit server.
Run from backend/:  python -m scripts.telephony_sync [--company-id N]
"""
import argparse
import asyncio

from app.core.database import SessionLocal
from app.models.phone_number import PhoneNumber
from app.services import livekit_sip_service


async def main(company_id: int | None):
    db = SessionLocal()
    try:
        q = db.query(PhoneNumber).filter(PhoneNumber.provider == "livekit_sip")
        if company_id:
            q = q.filter(PhoneNumber.company_id == company_id)
        for phone in q.order_by(PhoneNumber.id):
            try:
                phone.provider_config = await livekit_sip_service.sync_phone_number(phone)
                db.commit()
                print(f"ok   {phone.company_id:>4} {phone.number:<16} {phone.provider_config}")
            except Exception as e:
                db.rollback()
                print(f"FAIL {phone.company_id:>4} {phone.number:<16} {e}")
        print("LiveKit now has:", await livekit_sip_service.status())
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company-id", type=int)
    asyncio.run(main(parser.parse_args().company_id))
