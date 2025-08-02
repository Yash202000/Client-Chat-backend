import os

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "AgentConnect"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str
    GOOGLE_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    LIVEKIT_API_KEY: str = ""
    LIVEKIT_API_SECRET: str = ""
    LIVEKIT_URL: str = ""
    FRONTEND_URL: str = "http://localhost:8080"
    WHATSAPP_VERIFY_TOKEN: str = ""
    MESSENGER_VERIFY_TOKEN: str = ""
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    LOCALAI_TTS_URL: str = "http://localhost:8082/tts"
    
    SECRET_KEY: str = "S48jcPB4nMH0gVLHb3Py7DBGp91Xv3bUaDzsn5zB3jg="
    ALGORITHM: str = "HS256"

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'

settings = Settings()
