import os

class Settings:
    PROJECT_NAME: str = "AgentConnect"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str
    GOOGLE_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    
    SECRET_KEY: str = os.getenv("SECRET_KEY", "S48jcPB4nMH0gVLHb3Py7DBGp91Xv3bUaDzsn5zB3jg=")

    class Config:
        env_file = ".env"

settings = Settings()
