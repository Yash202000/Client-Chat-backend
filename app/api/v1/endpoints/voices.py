
from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List
from app.core.dependencies import get_db, get_current_user
from app.models.user import User
from app.services.voice_profile_service import VoiceProfileService
from app.schemas.voice_profile import VoiceProfile as VoiceProfileSchema

router = APIRouter()

@router.get("/", response_model=List[VoiceProfileSchema])
async def get_voice_profiles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = VoiceProfileService(db)
    return await service.get_voice_profiles(company_id=current_user.company_id)

@router.post("/clone")
async def clone_voice(
    name: str = Form(...),
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = VoiceProfileService(db)
    return await service.clone_voice(
        name=name,
        files=files,
        company_id=current_user.company_id,
        user_id=current_user.id
    )

@router.delete("/{voice_profile_id}")
async def delete_voice_profile(
    voice_profile_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = VoiceProfileService(db)
    return await service.delete_voice_profile(
        voice_profile_id=voice_profile_id,
        company_id=current_user.company_id
    )
