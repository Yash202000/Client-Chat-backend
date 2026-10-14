"""
Generate (or refresh) pre-generated speech for fixed phone prompts — IVR node text, greetings, hold
messages — for every company with contact-centre numbers. Retries failed ones, removes unused ones.

Use after changing TELEPHONY_TTS_MODEL, fixing the OpenAI key, or restoring MinIO.
Run from backend/:  python -m scripts.tts_prompt_sync [--company-id N]
"""
import argparse
import asyncio

from app.core.database import SessionLocal
from app.models.phone_number import PhoneNumber
from app.services import tts_prompt_service


async def main(company_id: int | None):
    db = SessionLocal()
    try:
        ids = [company_id] if company_id else [c for (c,) in db.query(PhoneNumber.company_id).distinct()]
    finally:
        db.close()
    for cid in sorted(ids):
        summary = await tts_prompt_service.sync_company(cid)
        print(f"company {cid:>4}: {summary['total']} prompts, {summary['generated']} generated, "
              f"{summary['failed']} failed, {summary['removed']} removed"
              + (f" — {summary['error']}" if summary["error"] else ""))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company-id", type=int)
    asyncio.run(main(parser.parse_args().company_id))
