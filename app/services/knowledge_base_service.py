from typing import List
from sqlalchemy.orm import Session
from app.models import knowledge_base as models_knowledge_base
from app.schemas import knowledge_base as schemas_knowledge_base
import requests
from bs4 import BeautifulSoup
import httpx
from app.services import credential_service, vectorization_service
from app.services.vault_service import vault_service
from app.core.object_storage import s3_client, BUCKET_NAME, get_company_chroma_client
import numpy as np
import os
import shutil
import os
from io import BytesIO
from pypdf import PdfReader

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
        update_data = knowledge_base.model_dump(exclude_unset=True)
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
                # Use company-specific client for multi-tenant isolation
                company_chroma_client = get_company_chroma_client(company_id)
                company_chroma_client.delete_collection(name=db_knowledge_base.chroma_collection_name)
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

def find_relevant_chunks(
    db: Session,
    knowledge_base_id: int,
    company_id: int,
    query: str,
    top_k: int = 3,
    agent=None,
    include_metadata: bool = False
):
    """
    Find relevant chunks from a knowledge base using Chroma or FAISS vector stores.
    Uses NVIDIA embeddings by default to match how knowledge bases are indexed.

    The knowledge base may contain:
    - Document chunks (from uploaded PDFs, DOCX, TXT files)
    - CMS content items (structured data indexed for RAG)

    Args:
        db: Database session
        knowledge_base_id: ID of the knowledge base
        company_id: Company ID for multi-tenant isolation
        query: Search query
        top_k: Number of results to return
        agent: Optional agent for embedding model
        include_metadata: If True, returns enriched results with source type and metadata

    Returns:
        If include_metadata=False: List[str] - Just the text chunks (backward compatible)
        If include_metadata=True: List[Dict] - Enriched results with metadata:
            {
                "text": "chunk text...",
                "source_type": "document" | "cms",
                "score": 0.92,
                "metadata": {
                    # For CMS items:
                    "content_type_slug": "shloka",
                    "content_type_name": "Shloka",
                    "content_item_id": 47,
                    "structured_data": {...}  # Full CMS item data
                }
            }
    """
    from app.core.config import settings
    from app.services.faiss_vector_database import VectorDatabase
    from app.llm_providers.nvidia_api_provider import NVIDIAEmbeddings
    import chromadb
    import json

    kb = get_knowledge_base(db, knowledge_base_id, company_id)
    if not kb:
        return []

    retrieved_results = []

    # Use NVIDIA embeddings (same as knowledge base indexing) or agent's embedding model
    def get_query_embedding(text: str):
        if agent and hasattr(agent, 'embedding_model'):
            from app.services.agent_execution_service import _get_embeddings
            embeddings = _get_embeddings(agent, [text])
            return embeddings[0].tolist()
        else:
            # Default to NVIDIA embeddings (matches knowledge_base_processing_service)
            nvidia_embeddings = NVIDIAEmbeddings()
            return nvidia_embeddings.embed_query(text)

    def process_chroma_results(results):
        """Process ChromaDB results into enriched format."""
        processed = []
        if not results or not results.get('documents') or not results['documents'][0]:
            return processed

        documents = results['documents'][0]
        metadatas = results.get('metadatas', [[]])[0] if results.get('metadatas') else [{}] * len(documents)
        distances = results.get('distances', [[]])[0] if results.get('distances') else [0] * len(documents)

        for i, doc in enumerate(documents):
            metadata = metadatas[i] if i < len(metadatas) else {}
            distance = distances[i] if i < len(distances) else 0

            # Convert distance to similarity score (ChromaDB uses L2 distance)
            similarity_score = 1 / (1 + distance) if distance >= 0 else 0

            # Determine source type from metadata
            source_type = metadata.get('source_type', 'document')

            result = {
                "text": doc,
                "source_type": source_type,
                "score": similarity_score,
                "metadata": {}
            }

            if source_type == "cms":
                # Extract CMS-specific metadata
                result["metadata"] = {
                    "content_type_slug": metadata.get("content_type_slug"),
                    "content_type_name": metadata.get("content_type_name"),
                    "content_item_id": metadata.get("content_item_id"),
                }
                # Parse structured data if available
                structured_data_str = metadata.get("structured_data")
                if structured_data_str:
                    try:
                        result["metadata"]["structured_data"] = json.loads(structured_data_str)
                    except (json.JSONDecodeError, TypeError):
                        pass

            processed.append(result)

        return processed

    try:
        if kb.type == "local" and kb.chroma_collection_name:
            # Query the local ChromaDB collection using company-specific client
            query_embedding = get_query_embedding(query)
            company_chroma_client = get_company_chroma_client(company_id)
            collection = company_chroma_client.get_collection(name=kb.chroma_collection_name)
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                include=["documents", "metadatas", "distances"]
            )

            if include_metadata:
                retrieved_results = process_chroma_results(results)
            else:
                # Backward compatible: return just the text
                if results and results.get('documents') and results['documents'][0]:
                    retrieved_results = results['documents'][0]

        elif kb.type == "local" and kb.faiss_index_id:
            # Query the local FAISS index (documents only, no CMS support)
            embeddings_instance = NVIDIAEmbeddings()
            faiss_db_path = os.path.join(settings.FAISS_INDEX_DIR, str(company_id), kb.faiss_index_id)
            faiss_db = VectorDatabase(embeddings=embeddings_instance, db_path=faiss_db_path, index_name=kb.faiss_index_id)
            if faiss_db.load_index():
                results = faiss_db.similarity_search(query, k=top_k)
                if include_metadata:
                    retrieved_results = [
                        {
                            "text": doc.page_content,
                            "source_type": "document",
                            "score": 0.0,  # FAISS doesn't return scores in this implementation
                            "metadata": {}
                        }
                        for doc in results
                    ]
                else:
                    retrieved_results = [doc.page_content for doc in results]

        elif kb.type == "remote" and kb.provider == "chroma" and kb.connection_details:
            # Query a remote ChromaDB instance
            query_embedding = get_query_embedding(query)
            client = chromadb.HttpClient(
                host=kb.connection_details.get("host"),
                port=kb.connection_details.get("port")
            )
            collection = client.get_collection(name=kb.connection_details.get("collection_name"))
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                include=["documents", "metadatas", "distances"]
            )

            if include_metadata:
                retrieved_results = process_chroma_results(results)
            else:
                if results and results.get('documents') and results['documents'][0]:
                    retrieved_results = results['documents'][0]

    except Exception as e:
        print(f"Error querying knowledge base {kb.name} (ID: {kb.id}): {e}")
        return []

    return retrieved_results

import os
from io import BytesIO
from pypdf import PdfReader

def get_knowledge_base_content(db: Session, knowledge_base_id: int, company_id: int):
    db_knowledge_base = get_knowledge_base(db, knowledge_base_id, company_id)
    if not db_knowledge_base:
        return None

    if db_knowledge_base.storage_type == 's3' and db_knowledge_base.storage_details:
        try:
            key = db_knowledge_base.storage_details.get('key')
            response = s3_client.get_object(
                Bucket=db_knowledge_base.storage_details.get('bucket'),
                Key=key
            )
            file_content_bytes = response['Body'].read()

            file_extension = os.path.splitext(key)[1].lower()

            if file_extension == '.pdf':
                try:
                    pdf_file = BytesIO(file_content_bytes)
                    reader = PdfReader(pdf_file)
                    text = ""
                    for page in reader.pages:
                        text += page.extract_text() or ""
                    return text
                except Exception as e:
                    print(f"Error parsing PDF file from S3: {e}")
                    return "Could not extract text from PDF file."
            else: # Assume text file for others
                try:
                    return file_content_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    return "File content could not be displayed (not valid UTF-8 text)."

        except Exception as e:
            print(f"Error fetching file from S3: {e}")
            return None
    
    return db_knowledge_base.content

def get_knowledge_base_download_url(db: Session, knowledge_base_id: int, company_id: int):
    db_knowledge_base = get_knowledge_base(db, knowledge_base_id, company_id)
    if not db_knowledge_base:
        return None

    if db_knowledge_base.storage_type == 's3' and db_knowledge_base.storage_details:
        try:
            return s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': db_knowledge_base.storage_details.get('bucket'),
                    'Key': db_knowledge_base.storage_details.get('key')
                },
                ExpiresIn=3600  # URL expires in 1 hour
            )
        except Exception as e:
            print(f"Error generating presigned URL: {e}")
            return None
    
    return None
