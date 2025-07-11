from sqlalchemy.orm import Session
from app.models import knowledge_base as models_knowledge_base
from app.schemas import knowledge_base as schemas_knowledge_base
import requests
from bs4 import BeautifulSoup
import httpx
from app.services import credential_service

async def generate_qna_from_knowledge_base(db: Session, knowledge_base_id: int, company_id: int, prompt: str) -> str:
    kb = get_knowledge_base(db, knowledge_base_id, company_id)
    if not kb:
        raise ValueError("Knowledge Base not found")

    # Assuming a default credential for Groq API or fetching from agent's credential
    # For simplicity, let's assume we fetch the first available credential for Groq
    credentials = credential_service.get_credentials(db, company_id)
    api_key = None
    for cred in credentials:
        # You might want to have a more robust way to identify Groq credentials
        if "grok" in cred.platform.lower():
            api_key = cred.api_key
            break
    
    if not api_key:
        raise ValueError("Groq API key not configured. Please add a credential with 'Groq' in its name or platform.")

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": kb.content}
    ]

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama3-8b-8192", # Or another suitable Groq model
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 1024,
                },
                timeout=60.0
            )
            response.raise_for_status()
            grok_response = response.json()
            return grok_response["choices"][0]["message"]["content"]
    except httpx.RequestError as e:
        raise ValueError(f"Error communicating with Groq API: {e}")
    except httpx.HTTPStatusError as e:
        raise ValueError(f"Groq API returned an error: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        raise ValueError(f"An unexpected error occurred during Q&A generation: {e}")

def extract_text_from_url(url: str) -> str:
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # Raise an exception for HTTP errors
        soup = BeautifulSoup(response.text, 'html.parser')
        # Remove script and style elements
        for script_or_style in soup(['script', 'style']):
            script_or_style.extract()
        text = soup.get_text()
        # Break into lines and remove leading/trailing space on each
        lines = (line.strip() for line in text.splitlines())
        # Break multi-headlines into a line each
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        # Drop blank lines
        text = '\n'.join(chunk for chunk in chunks if chunk)
        return text
    except requests.exceptions.RequestException as e:
        raise ValueError(f"Error fetching URL: {e}")
    except Exception as e:
        raise ValueError(f"Error parsing content from URL: {e}")

def get_knowledge_base(db: Session, knowledge_base_id: int, company_id: int):
    return db.query(models_knowledge_base.KnowledgeBase).filter(
        models_knowledge_base.KnowledgeBase.id == knowledge_base_id,
        models_knowledge_base.KnowledgeBase.company_id == company_id
    ).first()

def get_knowledge_bases(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_knowledge_base.KnowledgeBase).filter(
        models_knowledge_base.KnowledgeBase.company_id == company_id
    ).offset(skip).limit(limit).all()

def create_knowledge_base(db: Session, knowledge_base: schemas_knowledge_base.KnowledgeBaseCreate, company_id: int):
    db_knowledge_base = models_knowledge_base.KnowledgeBase(**knowledge_base.dict(), company_id=company_id)
    db.add(db_knowledge_base)
    db.commit()
    db.refresh(db_knowledge_base)
    return db_knowledge_base

def update_knowledge_base(db: Session, knowledge_base_id: int, knowledge_base: schemas_knowledge_base.KnowledgeBaseUpdate, company_id: int):
    db_knowledge_base = get_knowledge_base(db, knowledge_base_id, company_id)
    if db_knowledge_base:
        for key, value in knowledge_base.dict(exclude_unset=True).items():
            setattr(db_knowledge_base, key, value)
        db.commit()
        db.refresh(db_knowledge_base)
    return db_knowledge_base

def delete_knowledge_base(db: Session, knowledge_base_id: int, company_id: int):
    db_knowledge_base = get_knowledge_base(db, knowledge_base_id, company_id)
    if db_knowledge_base:
        db.delete(db_knowledge_base)
        db.commit()
    return db_knowledge_base
