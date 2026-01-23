from pydantic import BaseModel
from typing import Optional, Dict, Any

class KnowledgeBaseBase(BaseModel):
    name: str
    description: Optional[str] = None
    type: str = "local"
    provider: Optional[str] = None
    connection_details: Optional[Dict[str, Any]] = None
    company_id: Optional[int] = None
    type: str = "local" # 'local' or 'remote'
    storage_type: Optional[str] = None # e.g., 's3'
    storage_details: Optional[Dict[str, Any]] = None # e.g., {"bucket": "my-bucket", "key": "my-file.txt"}
    chroma_collection_name: Optional[str] = None
    faiss_index_id: Optional[str] = None

class KnowledgeBaseCreate(KnowledgeBaseBase):
    content: str

class KnowledgeBaseCreateEmpty(BaseModel):
    """Schema for creating an empty knowledge base without initial content."""
    name: str
    description: Optional[str] = None
    embedding_model: str = "nvidia"
    vector_store_type: str = "chroma"

class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    provider: Optional[str] = None
    connection_details: Optional[Dict[str, Any]] = None
    content: Optional[str] = None

class KnowledgeBase(KnowledgeBaseBase):
    id: int
    content: Optional[str] = None

    class Config:
        orm_mode = True

class KnowledgeBaseQnAGenerate(BaseModel):
    knowledge_base_id: int
    prompt: Optional[str] = "Generate a list of 10 questions and answers based on the following content. Format as Q: ...\nA: ..."

class KnowledgeBaseQnA(BaseModel):
    generated_content: str
