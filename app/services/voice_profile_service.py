
import os
import aiohttp
from sqlalchemy.orm import Session
from fastapi import UploadFile
from app.models.voice_profile import VoiceProfile
from app.schemas.voice_profile import VoiceProfileCreate
from app.core.config import settings

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1"

class VoiceProfileService:
    def __init__(self, db: Session):
        self.db = db

    async def get_voice_profiles(self, company_id: int):
        return self.db.query(VoiceProfile).filter(VoiceProfile.company_id == company_id).all()

    async def clone_voice(self, name: str, files: list[UploadFile], company_id: int, user_id: int):
        url = f"{ELEVENLABS_API_URL}/voices/add"
        headers = {"xi-api-key": ELEVENLABS_API_KEY}
        form_data = aiohttp.FormData()
        form_data.add_field('name', name)
        
        for file in files:
            form_data.add_field('files', await file.read(), filename=file.filename, content_type=file.content_type)

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=form_data) as response:
                if response.status == 200:
                    data = await response.json()
                    provider_voice_id = data.get("voice_id")
                    
                    # Save to our database
                    db_voice_profile = VoiceProfile(
                        name=name,
                        provider_voice_id=provider_voice_id,
                        company_id=company_id,
                        user_id=user_id
                    )
                    self.db.add(db_voice_profile)
                    self.db.commit()
                    self.db.refresh(db_voice_profile)
                    return db_voice_profile
                else:
                    error_details = await response.text()
                    raise Exception(f"Failed to clone voice with ElevenLabs: {error_details}")

    async def delete_voice_profile(self, voice_profile_id: int, company_id: int):
        db_voice_profile = self.db.query(VoiceProfile).filter(
            VoiceProfile.id == voice_profile_id,
            VoiceProfile.company_id == company_id
        ).first()

        if not db_voice_profile:
            return None

        # Delete from ElevenLabs
        url = f"{ELEVENLABS_API_URL}/voices/{db_voice_profile.provider_voice_id}"
        headers = {"xi-api-key": ELEVENLABS_API_KEY}
        
        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers) as response:
                if response.status != 200:
                    # Log the error but proceed with deleting from our DB anyway
                    print(f"Warning: Failed to delete voice from ElevenLabs. Status: {response.status}")

        # Delete from our database
        self.db.delete(db_voice_profile)
        self.db.commit()
        return {"message": "Voice profile deleted"}
