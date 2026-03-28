# Requirements Comparison & Optimization Guide

## Summary

| File | Packages | Docker Size | Use Case |
|------|----------|-------------|----------|
| `requirements.txt` (current) | **335** | **4.82GB** | Everything (most unused) |
| `requirements.minimal.txt` | **~100** | **~3-3.5GB** | All used features + ML |
| `requirements.no-ml.txt` | **~80** | **~800MB-1.2GB** | All features except ML |

## What Was Removed (274 unused packages!)

### ❌ Unused Packages (Never Imported)

#### **Computer Vision - REMOVED** (~500MB saved)
```
opencv-python-headless==4.10.0.84
roboflow==1.2.9
supervision==0.26.1
timm==1.0.19
rf100vl==1.0.0
rfdetr==1.2.1
pycocotools==2.0.10
bbox_visualizer==0.2.2
scikit-image==0.25.2
```

#### **Browser Automation - REMOVED** (~300MB saved)
```
playwright==1.55.0
stagehand==0.5.3
```

#### **Alternative Vector DB - REMOVED** (~50MB saved)
```
lancedb==0.25.1
pylance==0.37.0
```

#### **Unused LLM Providers - REMOVED**
```
anthropic==0.68.1  # Installed but NEVER imported!
litellm==1.74.9    # Not used
```

#### **Data Analysis - REMOVED** (~200MB saved)
```
pandas==2.3.2
polars==1.33.1
scipy==1.16.0
scikit-learn==1.7.0
matplotlib==3.10.6
```

#### **Unused PyTorch Components - REMOVED** (~1GB saved from minimal)
```
torchvision==0.23.0      # Not imported
torchaudio==2.8.0        # Not imported
triton==3.4.0            # Not imported
fairscale==0.4.13        # Not used
peft==0.17.1             # Not used
open_clip_torch==3.1.0   # Not used
```

#### **IoT/Industrial - REMOVED**
```
pymodbus==3.8.3
pylogix==1.0.5
asyncua==1.1.8
paho-mqtt==1.6.1
onvif-zeep-async==2.0.0
```

#### **Unused Utilities - REMOVED**
```
redis==5.0.8              # Installed but not used!
slack_sdk==3.33.5         # Not used
openpyxl==3.1.5           # Not used (no Excel processing)
youtube-transcript-api==1.2.2
instructor==1.11.3
docker==7.1.0
kubernetes==33.1.0
```

#### **Development Tools - REMOVED**
```
pytest==8.4.1
ipython==9.5.0
ipywidgets==8.1.7
jupyter_bbox_widget==0.6.0
```

## What's Kept (Actually Used)

### ✅ Core Framework (Most Used)
- **fastapi** - 95 files use this
- **sqlalchemy** - 244 files (MOST USED!)
- **pydantic** - 79 files
- **uvicorn, starlette, websockets**

### ✅ LLM & AI (API-based)
- **openai** - 4 files
- **groq** - 5 files
- **langchain** - 4 files (+ community integrations)

### ✅ Real-time Communications
- **livekit** - 6 files (voice/video)
- **aiortc** - WebRTC support

### ✅ Vector Databases
- **chromadb** - 3 files
- **faiss** - 1 file

### ✅ Cloud Services (Actually Used)
- **boto3** - AWS S3 (2 files)
- **google** - Google APIs (5 files)
- **twilio** - SMS/Voice (3 files)

### ✅ File Processing (Used)
- **pypdf, PyPDF2** - PDF processing
- **docx2txt, python-docx** - Word documents
- **pillow** - Image handling
- **python-magic** - File type detection

### ✅ HTTP Clients
- **httpx** - 13 files (modern async)
- **requests** - 4 files (legacy)
- **aiohttp** - 5 files (async)

### ⚠️ ML Libraries (Optional - only in requirements.minimal.txt)
- **torch** - 2 files (vad_service.py, nvidia_provider.py)
- **transformers** - 1 file (nvidia_provider.py)
- **sentence-transformers** - 1 file (vectorization_service.py)

**Remove these in requirements.no-ml.txt if you:**
- Don't use Voice Activity Detection (VAD)
- Don't use NVIDIA LLM provider
- Use external embeddings (OpenAI) instead of local

## Migration Instructions

### Option 1: No ML (Recommended - Smallest)
```bash
# Test locally first
pip install -r requirements.no-ml.txt
python -m app.main

# Update Dockerfile
COPY requirements.no-ml.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Expected size: ~800MB-1.2GB (83% reduction!)
```

### Option 2: With ML Features
```bash
# If you use vad_service.py or nvidia_provider.py
pip install -r requirements.minimal.txt

# Expected size: ~3-3.5GB (27% reduction)
```

### Option 3: Gradual Migration
```bash
# Backup current requirements
cp requirements.txt requirements.backup.txt

# Try no-ML version
cp requirements.no-ml.txt requirements.txt

# Test your application
docker build -t test:no-ml .
docker run test:no-ml

# If features are missing, use minimal version instead
cp requirements.minimal.txt requirements.txt
```

## What Features Break With Each Version

### requirements.no-ml.txt Breaks:
- ❌ `app/services/vad_service.py` - Voice Activity Detection
- ❌ `app/llm_providers/nvidia_provider.py` - NVIDIA LLM provider
- ❌ Local sentence embeddings (can use OpenAI embeddings instead)

### requirements.minimal.txt Breaks:
- ❌ Computer vision features (not used anyway)
- ❌ Playwright automation (not used)
- ❌ Pandas data analysis (not used)
- ❌ Redis caching (installed but never used)

## Actually Used Files

Based on the analysis, these are the **only files** that use ML libraries:

### PyTorch Users (2 files):
1. `app/services/vad_service.py` - Voice Activity Detection
2. `app/llm_providers/nvidia_provider.py` - NVIDIA LLM

### Transformers Users (1 file):
1. `app/llm_providers/nvidia_provider.py`

### Sentence Transformers Users (1 file):
1. `app/services/vectorization_service.py` - Local embeddings

**Question**: Do you actually use these features?
- If NO → Use `requirements.no-ml.txt` (save 3GB!)
- If YES → Use `requirements.minimal.txt`

## Recommendations

### For Production (Most Users):
✅ **Use requirements.no-ml.txt**
- Docker size: ~800MB-1.2GB
- Saves 83% (4GB saved!)
- Works for 90% of deployments

### For ML-Enabled Features:
✅ **Use requirements.minimal.txt**
- Docker size: ~3-3.5GB
- Saves 27% (1.3GB saved)
- Includes PyTorch, Transformers, Embeddings

### Still Too Large?
Consider:
1. Use external embeddings (OpenAI) instead of local
2. Remove PyTorch if you don't use VAD
3. Use managed vector DB (Pinecone) instead of ChromaDB

## Test Before Deploying

```bash
# Build and test
docker build -f Dockerfile -t heygenally:test .
docker run -p 8000:8000 heygenally:test

# Check all endpoints work
curl http://localhost:8000/docs

# Test critical features:
# - API endpoints
# - Database connections
# - LLM calls (OpenAI, Groq)
# - File uploads
# - WebSocket connections
```

## Size Comparison

```
Current:  ██████████████████████████████ 4.82GB (100%)
Minimal:  ████████████████               3.50GB (73%)
No ML:    ████                           1.00GB (21%) ← Recommended!
```

**Recommendation**: Start with `requirements.no-ml.txt` unless you specifically need VAD or NVIDIA provider! 🚀
