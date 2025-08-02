
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from typing import Literal
from app.services.stt_service import GroqSTTService
from app.core.dependencies import get_current_user
from app.models.user import User

router = APIRouter()

@router.post("/audio/transcriptions", tags=["STT"])
async def transcribe_audio(
    file: UploadFile = File(...),
    model: Literal["whisper-large-v3-turbo", "whisper-large-v3"] = "whisper-large-v3-turbo",
    current_user: User = Depends(get_current_user)
):
    """
    Convert audio to text using Groq's transcription service.
    """
    stt_service = GroqSTTService()
    try:
        result = await stt_service.transcribe(file, model)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/audio/translations", tags=["STT"])
async def translate_audio(
    file: UploadFile = File(...),
    model: Literal["whisper-large-v3-turbo", "whisper-large-v3"] = "whisper-large-v3-turbo",
    current_user: User = Depends(get_current_user)
):
    """
    Translate audio to English text using Groq's translation service.
    """
    stt_service = GroqSTTService()
    try:
        result = await stt_service.translate(file, model)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
