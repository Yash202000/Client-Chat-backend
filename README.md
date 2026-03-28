# HeyGenAlly Backend

FastAPI-based backend for HeyGenAlly platform with multi-tenant support, AI agents, workflows, and integrations.

## Quick Start

### Prerequisites

- Python 3.12+
- PostgreSQL 15+
- Redis
- MinIO (S3-compatible storage)
- ChromaDB (optional, for vector search)

### Setup

1. **Create virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment:**
   ```bash
   cp .env.example .env
   nano .env  # Edit configuration
   ```

4. **Run database migrations:**
   ```bash
   alembic upgrade head
   ```

5. **Start the server:**
   ```bash
   uvicorn app.main:app --reload
   ```

Server will be available at: http://localhost:8000

API documentation: http://localhost:8000/docs

---

## Environment Configuration

### Required Settings

```env
# Security (REQUIRED - Change in production!)
SECRET_KEY=your-super-secret-key-change-this
ALGORITHM=HS256

# Database
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/heygenally

# Frontend
FRONTEND_URL=http://localhost:5173

# Server
HOST=0.0.0.0
PORT=8000
CORS_ORIGINS=http://localhost:8080,http://localhost:5173,*
```

### Credential Management Mode

HeyGenAlly supports two deployment modes for AI provider credentials:

#### Self-Hosted Mode (Default)
Users manage their own API keys through the UI vault.

```env
MANAGED_CREDENTIALS=false
```

- Users can add/edit/delete AI provider credentials via Settings → Vault
- Each company manages their own encrypted credentials
- Multi-tenant credential isolation

#### Managed/Cloud Mode
System administrator manages all API keys centrally.

```env
MANAGED_CREDENTIALS=true

# System-level API keys (used for ALL operations)
ANTHROPIC_API_KEY=sk-ant-api03-...
OPENAI_API_KEY=sk-proj-...
GROQ_API_KEY=gsk_...
GEMINI_API_KEY=...
```

- Credential vault UI is read-only (users cannot add/edit/delete)
- All API calls use system-configured keys
- Centralized billing and access control
- Best for SaaS deployments

**See [CREDENTIAL_MANAGEMENT.md](../CREDENTIAL_MANAGEMENT.md) for detailed documentation.**

### AI Provider API Keys

When using **self-hosted mode**, users add these via UI.
When using **managed mode**, configure them here:

```env
# OpenAI (for GPT models and voice agents)
OPENAI_API_KEY=sk-proj-...

# Anthropic (for Claude models)
ANTHROPIC_API_KEY=sk-ant-api03-...

# Groq (for fast inference)
GROQ_API_KEY=gsk_...

# Google Gemini
GOOGLE_API_KEY=AIzaSy...
GEMINI_API_KEY=AIzaSy...  # Alternative

# NVIDIA (for embeddings)
NVIDIA_API_KEY=nvapi-...

# Deepgram (for speech-to-text)
DEEPGRAM_API_KEY=...
```

### Channel Integrations

```env
# WhatsApp
WHATSAPP_VERIFY_TOKEN=your-token

# Facebook Messenger
MESSENGER_VERIFY_TOKEN=your-token

# Instagram
INSTAGRAM_VERIFY_TOKEN=your-token

# Telegram
TELEGRAM_BOT_TOKEN=your-bot-token

# Gmail
GMAIL_CLIENT_ID=...
GMAIL_CLIENT_SECRET=...
GMAIL_REDIRECT_URI=http://localhost:8000/api/v1/google/callback

# LinkedIn
LINKEDIN_CLIENT_ID=...
LINKEDIN_CLIENT_SECRET=...
LINKEDIN_REDIRECT_URI=...
LINKEDIN_COMPANY_ID=...
```

### Voice Integration (LiveKit)

```env
# LiveKit Cloud
LIVEKIT_URL=wss://your-instance.livekit.cloud
LIVEKIT_API_KEY=APIxxxxx
LIVEKIT_API_SECRET=xxxxx

# OpenAI Realtime API
OPENAI_REALTIME_ENABLED=true
OPENAI_REALTIME_MODEL=gpt-4o-realtime-preview-2024-12-17
OPENAI_REALTIME_VOICE=alloy

# Voice Agent Settings
AGENT_LLM_PROVIDER=openai
AGENT_LLM_MODEL=gpt-4o-mini
AGENT_STT_PROVIDER=deepgram
AGENT_TTS_PROVIDER=openai
AGENT_TTS_VOICE=alloy
```

### Storage & Databases

```env
# MinIO/S3 Storage
MINIO_ENDPOINT=localhost:9000
MINIO_SECURE=false
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=heygenally

# ChromaDB (Vector Database)
CHROMA_DB_HOST=localhost
CHROMA_DB_PORT=8001

# FAISS Index Directory
FAISS_INDEX_DIR=./faiss_indexes
```

### Payment Integration

```env
# Razorpay (for subscriptions)
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
```

### Deployment Mode

```env
# "cloud" = Stripe subscriptions
# "on_premise" = License key validation
DEPLOYMENT_MODE=cloud

# License key for on-premise deployments
LICENSE_KEY_SECRET=...
LICENSE_KEY=...
```

### Performance & Monitoring

```env
# LLM Configuration
LLM_STREAMING_ENABLED=true
LLM_STREAM_TOKEN_BUFFER=1
LLM_REQUEST_TIMEOUT=120
HTTP_REQUEST_TIMEOUT=30

# WebSocket Configuration
WS_PING_INTERVAL=30
WS_CLEANUP_INTERVAL=60
WS_REGULAR_SESSION_TIMEOUT=1800
WS_PREVIEW_SESSION_TIMEOUT=300
WS_ENABLE_HEARTBEAT=true

# Workflow Configuration
MAX_SUBWORKFLOW_DEPTH=5
```

---

## Database Migrations

### Create new migration

```bash
# Auto-generate migration from model changes
alembic revision --autogenerate -m "Description of changes"
```

### Apply migrations

```bash
# Upgrade to latest version
alembic upgrade head

# Upgrade to specific version
alembic upgrade <revision_id>

# Downgrade one version
alembic downgrade -1
```

### View migration history

```bash
# Show current version
alembic current

# Show migration history
alembic history
```

---

## Development

### Run development server

```bash
# With auto-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# With specific log level
uvicorn app.main:app --reload --log-level debug
```

### Code formatting

```bash
# Format code
black .

# Sort imports
isort .
```

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app tests/

# Run specific test file
pytest tests/test_agents.py
```

---

## API Documentation

### Interactive API Docs

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Main Endpoints

```
POST   /api/v1/auth/login              # User login
POST   /api/v1/auth/register           # User registration

GET    /api/v1/agents/                 # List agents
POST   /api/v1/agents/                 # Create agent
PUT    /api/v1/agents/{id}             # Update agent

GET    /api/v1/workflows/              # List workflows
POST   /api/v1/workflows/              # Create workflow
POST   /api/v1/workflows/{id}/execute  # Execute workflow

GET    /api/v1/conversations/          # List conversations
POST   /api/v1/conversations/          # Create conversation

GET    /api/v1/credentials/            # List credentials (vault)
POST   /api/v1/credentials/            # Add credential
PUT    /api/v1/credentials/{id}        # Update credential
DELETE /api/v1/credentials/{id}        # Delete credential

GET    /api/v1/system/config           # Get system configuration
```

### WebSocket Endpoints

```
WS     /api/v1/ws/conversations/{id}   # Real-time chat
WS     /api/v1/ws/voice                # Voice conversations
```

---

## MCP Server (FastMCP)

For Model Context Protocol integration:

```bash
# Install dependencies
pip install fastmcp pydantic google-api-python-client google-auth-httplib2 google-auth-oauthlib

# Run MCP server
fastmcp run main.py --transport http --port 8100
```

---

## Project Structure

```
backend/
├── app/
│   ├── api/
│   │   └── v1/
│   │       └── endpoints/       # API route handlers
│   ├── core/
│   │   ├── auth.py             # Authentication
│   │   ├── config.py           # Configuration
│   │   └── database.py         # Database setup
│   ├── models/                 # SQLAlchemy models
│   ├── schemas/                # Pydantic schemas
│   ├── services/               # Business logic
│   │   ├── agent_execution_service.py
│   │   ├── workflow_execution_service.py
│   │   ├── credential_service.py
│   │   └── system_config_service.py
│   ├── llm_providers/          # LLM integrations
│   └── main.py                 # FastAPI app
├── alembic/                    # Database migrations
├── tests/                      # Test files
├── requirements.txt
└── .env                        # Environment config
```

---

## Troubleshooting

### Database connection errors

```bash
# Check database is running
pg_isready -h localhost -p 5432

# Test connection
psql -U heygenally -d heygenally -h localhost
```

### Migration issues

```bash
# Reset database (⚠️ WARNING: deletes all data)
alembic downgrade base
alembic upgrade head

# Or recreate from scratch
dropdb heygenally
createdb heygenally
alembic upgrade head
```

### Import errors

```bash
# Reinstall dependencies
pip install -r requirements.txt --upgrade

# Clear Python cache
find . -type d -name __pycache__ -exec rm -r {} +
```

### Port already in use

```bash
# Find process using port 8000
lsof -i :8000

# Kill the process
kill -9 <PID>
```

---

## Production Deployment

### Security Checklist

- [ ] Change `SECRET_KEY` to a strong random value
- [ ] Set `MANAGED_CREDENTIALS=true` for centralized control (SaaS)
- [ ] Use strong database passwords
- [ ] Enable HTTPS/TLS
- [ ] Configure CORS_ORIGINS properly
- [ ] Set secure file permissions on `.env` (chmod 600)
- [ ] Use secrets management (Vault, AWS Secrets Manager)
- [ ] Enable rate limiting
- [ ] Configure firewall rules
- [ ] Set up database backups

### Environment Variables

```bash
# Generate secure SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Set production environment
export ENVIRONMENT=production
```

### Docker Deployment

See [README.docker.md](../README.docker.md) for containerized deployment.

---

## Additional Documentation

- **CREDENTIAL_MANAGEMENT.md** - Managed vs self-hosted credential modes
- **LIVEKIT_AGENTS_SETUP.md** - Voice agent configuration
- **SERVICE-SETUP.md** - Service setup guide
- **QUICKSTART.md** - Quick start guide (root directory)

---

## Support

- **API Docs**: http://localhost:8000/docs
- **Issues**: GitHub Issues
- **Logs**: `docker-compose logs -f backend` (if using Docker)

---

**Version**: 1.0.0
**Python**: 3.12+
**Framework**: FastAPI 0.115+
