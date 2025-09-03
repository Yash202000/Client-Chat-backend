from typing import List
from sqlalchemy.orm import Session
from app.models import knowledge_base as models_knowledge_base
from app.schemas import knowledge_base as schemas_knowledge_base
import requests
from bs4 import BeautifulSoup
import httpx
from app.services import credential_service, vectorization_service
from app.services.vault_service import vault_service
from app.core.object_storage import s3_client, BUCKET_NAME, chroma_client
import numpy as np
import os
import shutil

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
        if "groq" in cred.service.lower():
            api_key = vault_service.decrypt(cred.encrypted_credentials)
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
                    "model": "llama-3.1-8b-instant", # Or another suitable Groq model
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 1024,
                },
                timeout=60.0
            )
            response.raise_for_status()
            groq_response = response.json()
            return groq_response["choices"][0]["message"]["content"]
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

def _chunk_content(content: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[str]:
    # A simple chunking strategy for now. Can be replaced with more sophisticated methods.
    words = content.split()
    chunks = []
    for i in range(0, len(words), chunk_size - chunk_overlap):
        chunk = " ".join(words[i:i + chunk_size])
        chunks.append(chunk)
    return chunks

def create_knowledge_base(db: Session, knowledge_base: schemas_knowledge_base.KnowledgeBaseCreate, company_id: int):
    chunks = _chunk_content(knowledge_base.content)
    chunk_embeddings = [vectorization_service.get_embedding(chunk).tolist() for chunk in chunks]
    db_knowledge_base = models_knowledge_base.KnowledgeBase(**knowledge_base.dict(), company_id=company_id, embeddings=chunk_embeddings)
    db.add(db_knowledge_base)
    db.commit()
    db.refresh(db_knowledge_base)
    return db_knowledge_base

def update_knowledge_base(db: Session, knowledge_base_id: int, knowledge_base: schemas_knowledge_base.KnowledgeBaseUpdate, company_id: int):
    db_knowledge_base = get_knowledge_base(db, knowledge_base_id, company_id)
    if db_knowledge_base:
        update_data = knowledge_base.dict(exclude_unset=True)
        if 'content' in update_data:
            chunks = _chunk_content(update_data['content'])
            db_knowledge_base.embeddings = [vectorization_service.get_embedding(chunk).tolist() for chunk in chunks]
        for key, value in update_data.items():
            setattr(db_knowledge_base, key, value)
        db.commit()
        db.refresh(db_knowledge_base)
    return db_knowledge_base

def delete_knowledge_base(db: Session, knowledge_base_id: int, company_id: int):
    db_knowledge_base = get_knowledge_base(db, knowledge_base_id, company_id)
    if db_knowledge_base:
        if db_knowledge_base.storage_type == 's3' and db_knowledge_base.storage_details:
            try:
                s3_client.delete_object(
                    Bucket=db_knowledge_base.storage_details.get('bucket'), 
                    Key=db_knowledge_base.storage_details.get('key')
                )
            except Exception as e:
                print(f"Error deleting file from S3: {e}")
                # Decide if you want to raise an exception or just log the error

        if db_knowledge_base.chroma_collection_name:
            try:
                chroma_client.delete_collection(name=db_knowledge_base.chroma_collection_name)
            except Exception as e:
                print(f"Error deleting chroma collection: {e}")

        if db_knowledge_base.faiss_index_id:
            try:
                if os.path.exists(db_knowledge_base.faiss_index_id):
                    shutil.rmtree(db_knowledge_base.faiss_index_id)
                    print(f"FAISS index deleted from: {db_knowledge_base.faiss_index_id}")
            except Exception as e:
                print(f"Error deleting FAISS index: {e}")

        db.delete(db_knowledge_base)
        db.commit()
    return db_knowledge_base

def find_relevant_chunks(db: Session, knowledge_base_id: int, company_id: int, query: str, top_k: int = 3):
    kb = get_knowledge_base(db, knowledge_base_id, company_id)
    if not kb or not kb.embeddings:
        return []

    query_embedding = vectorization_service.get_embedding(query)
    content_chunks = _chunk_content(kb.content)
    
    # Ensure embeddings are treated as a list of 1D arrays
    if not kb.embeddings or not isinstance(kb.embeddings[0], list):
        # If embeddings are missing or stored as a single list of floats, re-embed chunks
        chunk_embeddings = [vectorization_service.get_embedding(chunk) for chunk in content_chunks]
        # Optionally, update the KB with these new embeddings for future use
        # kb.embeddings = [e.tolist() for e in chunk_embeddings]
        # db.add(kb); db.commit(); db.refresh(kb)
    else:
        chunk_embeddings = [np.array(e) for e in kb.embeddings]

    similarities = [vectorization_service.cosine_similarity(query_embedding, chunk_embedding) for chunk_embedding in chunk_embeddings]
    
    # Get the indices of the top-k most similar chunks
    top_k_indices = np.argsort(similarities)[-top_k:][::-1]
    
    return [content_chunks[i] for i in top_k_indices]
