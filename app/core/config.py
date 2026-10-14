import os
from typing import Optional

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "HeyGenAlly"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str
    GOOGLE_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    NVIDIA_API_KEY: str = ""
    LIVEKIT_API_KEY: str = ""
    LIVEKIT_API_SECRET: str = ""
    LIVEKIT_URL: str = ""
    # Redis used to fan out websocket broadcasts across processes (API workers, voice process).
    # Empty = single-process mode (broadcasts only reach sockets in the current process).
    # High availability: all LiveKit nodes of the cluster (comma separated ws:// URLs) and the matching
    # addresses for browsers; the backend uses a healthy one (services/livekit_nodes.py). Empty = LIVEKIT_URL.
    LIVEKIT_URLS: str = ""
    LIVEKIT_PUBLIC_URLS: str = ""
    REDIS_URL: str = ""
    # High availability: Redis Sentinel instead of REDIS_URL ("host:26379,host2:26379"); clients follow failovers
    REDIS_SENTINELS: str = ""
    REDIS_SENTINEL_MASTER: str = "agentconnect"
    REDIS_SENTINEL_PASSWORD: str = ""
    REDIS_PASSWORD: str = ""
    WS_FANOUT_CHANNEL: str = "agentconnect:ws"

    # Telephony (LiveKit SIP contact centre). LIVEKIT_URL/KEY/SECRET above must point at the
    # LiveKit server that runs LiveKit SIP (see telephony/README.md).
    # LiveKit URL browsers use to join calls (defaults to LIVEKIT_URL); e.g. ws://192.168.1.10:7880
    LIVEKIT_PUBLIC_URL: str = ""
    # How long an inbound call may ring before LiveKit SIP gives up (direct-to-agent numbers)
    TELEPHONY_RINGING_TIMEOUT_SECONDS: int = 45
    TELEPHONY_VOICE_AGENT_NAME: str = "agentconnect-voice"  # voice process registers under this name
    TELEPHONY_ROOM_PREFIX: str = "call"  # LiveKit names rooms <prefix>_<caller>_<random>
    # Warm job processes kept ready for incoming calls (each holds the backend + embedding model in memory)
    TELEPHONY_VOICE_IDLE_PROCESSES: int = 2
    # Load the local embedding model in each voice process up front (only needed if call flows use it)
    TELEPHONY_PREWARM_EMBEDDINGS: bool = False
    # SIP registrar (Kamailio) for softphones such as PortSIP — accounts are system users (sip_accounts)
    TELEPHONY_SIP_REALM: str = "agentconnect"            # digest realm; changing it requires resetting SIP passwords
    TELEPHONY_SIP_REGISTRAR_ADDRESS: str = "192.168.31.107:5080"  # what softphones use as SIP server (shown in the UI)
    # AI -> human handoff on calls: how long the caller holds before the AI takes the call back
    TELEPHONY_HANDOFF_WAIT_SECONDS: int = 90
    TELEPHONY_DEEPGRAM_MODEL: str = "nova-3"
    # Speech-to-text for calls on numbers without an Agent; otherwise the Agent's stt_provider is used
    # (deepgram | openai | groq | localai). Without a working key the call runs keypad-only.
    TELEPHONY_STT_DEFAULT_PROVIDER: str = "groq"
    GROQ_STT_MODEL: str = "whisper-large-v3-turbo"
    OPENAI_STT_MODEL: str = "gpt-4o-mini-transcribe"
    # LocalAI speech-to-text (OpenAI-compatible /audio/transcriptions, no key)
    LOCALAI_STT_URL: str = "http://localhost:8082/v1"
    LOCALAI_STT_MODEL: str = "whisper-1"
    # Text-to-speech for calls on numbers without an Agent; otherwise the Agent's TTS provider / voice is used
    TELEPHONY_TTS_DEFAULT_PROVIDER: str = "voice_engine"
    # Groq text-to-speech (TTSService provider "groq"): model picked from the text (Arabic script -> AR).
    # Default voices are used when the Agent's voice_id is "default".
    GROQ_TTS_MODEL_EN: str = "canopylabs/orpheus-v1-english"
    GROQ_TTS_MODEL_AR: str = "canopylabs/orpheus-arabic-saudi"
    GROQ_TTS_VOICE_EN: str = "troy"
    GROQ_TTS_VOICE_AR: str = "fahad"
    # On a rate limit (on_demand tier: 10 requests/min per model) wait and retry up to this many seconds in total
    GROQ_TTS_MAX_RETRY_WAIT: float = 60
    # Pre-generate speech for fixed IVR prompts / greetings / hold messages (tts_prompt_service)
    TELEPHONY_TTS_CACHE: bool = True
    # Who may send calls into inbound trunks: comma-separated IPs/CIDRs (softphone or SIP provider).
    # Empty = no IP restriction (dev only); use auth username/password or IPs in production.
    TELEPHONY_SIP_ALLOWED_ADDRESSES: str = ""
    TELEPHONY_SIP_AUTH_USERNAME: str = ""
    TELEPHONY_SIP_AUTH_PASSWORD: str = ""
    FRONTEND_URL: str
    BACKEND_URL: str = ""  # Public URL of this backend (used for widget script URLs)
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

    # Marketing Hub — Social Publishing
    FACEBOOK_APP_ID: str = ""
    FACEBOOK_APP_SECRET: str = ""
    FACEBOOK_REDIRECT_URI: str = ""
    INSTAGRAM_GRAPH_API_VERSION: str = "v19.0"
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_REDIRECT_URI: str = ""  # e.g. https://api.yourdomain.com/api/v1/social/auth/reddit/callback
    TWITTER_CLIENT_ID: str = ""
    TWITTER_CLIENT_SECRET: str = ""
    TWITTER_REDIRECT_URI: str = ""  # e.g. https://api.yourdomain.com/api/v1/social/auth/twitter/callback
    RAPIDAPI_KEY: str = ""
    RAPIDAPI_LINKEDIN_TRENDS_HOST: str = "linkedin-data-api.p.rapidapi.com"
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""
    LOCALAI_TTS_URL: str = "http://localhost:8082/tts"

    # Deployment Mode: "cloud" (Stripe subscriptions) or "on_premise" (license key)
    DEPLOYMENT_MODE: str = "cloud"
    LICENSE_KEY_SECRET: str = ""  # HMAC secret for signing/verifying license keys
    LICENSE_KEY: str = ""  # The license key for on-premise instances (optional, can also be in DB)

    # Credential Management Mode: Controls if credentials are managed at system level or by users
    # True = Managed/Cloud deployment (system-level credentials from .env, user vault disabled)
    # False = Self-hosted deployment (users manage their own credentials via vault)
    MANAGED_CREDENTIALS: bool = False

    # System-level API Keys (only used when MANAGED_CREDENTIALS=True)
    ANTHROPIC_API_KEY: str = ""
    # Note: OPENAI_API_KEY already defined at line 88 for LiveKit
    # GROQ_API_KEY already defined at line 11
    # GOOGLE_API_KEY already defined at line 10 (used for Gemini)
    GEMINI_API_KEY: str = ""  # Alternative name for Google API Key

    # Twilio SMS settings
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""
    PHONE_VERIFICATION_ENABLED: bool = False  # Enable when Twilio OTP is configured

    # MinIO/S3 settings
    minio_endpoint: str
    minio_secure: bool = False
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str = "heygenally"
    minio_strict: bool = True

    FAISS_INDEX_DIR: str = "./faiss_indexes"

    CHROMA_DB_HOST: Optional[str] = None
    CHROMA_DB_PORT: Optional[int] = None

    SECRET_KEY: str = "S48jcPB4nMH0gVLHb3Py7DBGp91Xv3bUaDzsn5zB3jg="
    ALGORITHM: str = "HS256"

    # System SMTP — used for transactional emails (signup verification, password reset)
    # Separate from per-company SMTP configured in Settings > Email
    SYSTEM_SMTP_HOST: str = ""
    SYSTEM_SMTP_PORT: int = 587
    SYSTEM_SMTP_USER: str = ""
    SYSTEM_SMTP_PASSWORD: str = ""
    SYSTEM_SMTP_FROM_EMAIL: str = ""
    SYSTEM_SMTP_FROM_NAME: str = "AgentConnect"
    SYSTEM_SMTP_USE_TLS: bool = True

    # Server configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGINS: str = "http://localhost:8080,http://localhost:5173,*"
    PUBLIC_HOST: Optional[str] = None  # Public hostname for WebSocket URLs (e.g., api.example.com)

    # WebSocket session cleanup settings
    WS_PING_INTERVAL: int = 30  # Send ping every 30 seconds
    WS_CLEANUP_INTERVAL: int = 60  # Run cleanup every 60 seconds
    WS_REGULAR_SESSION_TIMEOUT: int = 1800  # 30 minutes (1800 seconds)
    WS_PREVIEW_SESSION_TIMEOUT: int = 300  # 5 minutes (300 seconds)
    WS_ENABLE_HEARTBEAT: bool = True  # Feature flag to enable/disable heartbeat

    # Sentry error monitoring
    SENTRY_DSN: str = ""

    # Kill switches / rollback controls
    MAINTENANCE_MODE: bool = False   # When True → 503 for all non-exempt paths
    SIGNUP_PAUSED: bool = False      # When True → block new user registrations

    # Workflow Configuration
    MAX_SUBWORKFLOW_DEPTH: int = 5  # Maximum depth for nested subworkflows

    # LLM Streaming Configuration
    LLM_STREAMING_ENABLED: bool = False  # Disabled streaming responses by default
    LLM_STREAM_TOKEN_BUFFER: int = 1  # Number of tokens to buffer before sending (1 = real-time)
    LLM_REQUEST_TIMEOUT: int = 120  # Timeout for LLM API calls in seconds
    HTTP_REQUEST_TIMEOUT: int = 30  # Timeout for workflow HTTP requests in seconds

    # OpenAI Realtime API Configuration
    OPENAI_REALTIME_ENABLED: bool = True  # Use OpenAI Realtime API for voice calls
    OPENAI_REALTIME_MODEL: str = "gpt-4o-realtime-preview-2024-12-17"
    OPENAI_REALTIME_VOICE: str = "alloy"  # alloy, echo, shimmer, ash, ballad, coral, sage, verse

    # LiveKit AI Agents Configuration
    OPENAI_API_KEY: str = ""
    DEEPGRAM_API_KEY: str = ""
    AGENT_LLM_PROVIDER: str = "openai"
    AGENT_LLM_MODEL: str = "gpt-4o-mini"
    AGENT_STT_PROVIDER: str = "deepgram"
    AGENT_STT_LANGUAGE: str = "en"
    AGENT_TTS_PROVIDER: str = "openai"
    AGENT_TTS_VOICE: str = "alloy"
    AGENT_VAD_ENABLED: str = "true"
    AGENT_ALLOW_INTERRUPTIONS: str = "true"
    AGENT_GREETING: str = "Hello! I'm your AI voice assistant. How can I help you today?"
    AGENT_SYSTEM_PROMPT: str = "You are a helpful and friendly voice assistant. Keep your responses concise and natural for voice conversation."

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'
        extra = 'ignore'  # Ignore extra env vars not defined in Settings

settings = Settings()
