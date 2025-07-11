import os

class Settings:
    PROJECT_NAME: str = "AgentConnect API"
    API_V1_STR: str = "/api/v1"
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "your_grok_api_key_here") # Replace with actual key or env var

settings = Settings()
