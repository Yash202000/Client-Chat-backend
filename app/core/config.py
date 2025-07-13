import os

class Settings:
    PROJECT_NAME: str = "AgentConnect API"
    API_V1_STR: str = "/api/v1"
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "your_groq_api_key_here") # Replace with actual key or env var
    SECRET_KEY: str = os.getenv("SECRET_KEY", "S48jcPB4nMH0gVLHb3Py7DBGp91Xv3bUaDzsn5zB3jg=")

settings = Settings()
