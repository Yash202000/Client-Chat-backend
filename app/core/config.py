import os
from typing import Optional

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "AgentConnect"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str
    GOOGLE_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    NVIDIA_API_KEY: str = ""
    LIVEKIT_API_KEY: str = ""
    LIVEKIT_API_SECRET: str = ""
    LIVEKIT_URL: str = ""
    FRONTEND_URL: str = "http://localhost:8080"
    WHATSAPP_VERIFY_TOKEN: str = ""
    MESSENGER_VERIFY_TOKEN: str = ""
    INSTAGRAM_VERIFY_TOKEN: str = ""
    GMAIL_CLIENT_ID: str = ""
    GMAIL_CLIENT_SECRET: str = ""
    GMAIL_REDIRECT_URI: str = ""
    GOOGLE_CLIENT_SECRETS_FILE: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    LINKEDIN_CLIENT_ID: str = ""
    LINKEDIN_CLIENT_SECRET: str = ""
    LINKEDIN_REDIRECT_URI: str = ""
    LINKEDIN_COMPANY_ID: str = ""
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    LOCALAI_TTS_URL: str = "http://localhost:8082/tts"

    # MinIO/S3 settings
    minio_endpoint: str
    minio_secure: bool = False
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str = "agentconnect"
    minio_strict: bool = True

    FAISS_INDEX_DIR: str = "./faiss_indexes"

    CHROMA_DB_HOST: Optional[str] = None
    CHROMA_DB_PORT: Optional[int] = None

    SECRET_KEY: str = "S48jcPB4nMH0gVLHb3Py7DBGp91Xv3bUaDzsn5zB3jg="
    ALGORITHM: str = "HS256"

    # Server configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGINS: str = "http://localhost:8080,http://localhost:5173,*"

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'

settings = Settings()
