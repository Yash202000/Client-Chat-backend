from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, HttpUrl
from types import SimpleNamespace
import uuid
import PyPDF2
import io
import magic
import docx2txt
from RestrictedPython import compile_restricted, safe_builtins

from app.schemas import knowledge_base as schemas_knowledge_base
from app.schemas.temporary_document import TemporaryDocument
from app.services import knowledge_base_service, knowledge_base_processing_service
from app.core.dependencies import get_db, get_current_active_user, require_permission
from app.models import user as models_user
from app.crud import crud_temporary_document

router = APIRouter()

# Temporary in-memory cache for document processing
document_processing_cache = {}

class DocumentUploadResponse(BaseModel):
    document_id: str
    raw_text: str

class ProcessingCodeRequest(BaseModel):
    document_id: str
    code: str

class ProcessingCodeResponse(BaseModel):
    processed_text: str

@router.post("/upload-for-processing", response_model=TemporaryDocument)
def upload_for_processing(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    file: UploadFile = File(...)
):
    """
    Upload a document, extract its raw text, and cache it for processing.
    """
    try:
        raw_text = ""
        mime_type = magic.from_buffer(file.file.read(2048), mime=True)
        file.file.seek(0)

        if mime_type == "application/pdf":
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(file.file.read()))
            for page in pdf_reader.pages:
                raw_text += page.extract_text() or ""
        elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            raw_text = docx2txt.process(io.BytesIO(file.file.read()))
        elif mime_type.startswith("text/"):
            raw_text = file.file.read().decode("utf-8")
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {mime_type}")

        temp_doc = crud_temporary_document.create_temporary_document(db=db, text_content=raw_text)
        
        return temp_doc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")

@router.post("/run-processing-code", response_model=ProcessingCodeResponse)
def run_processing_code(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    request: ProcessingCodeRequest
):
    """
    Run Python code to process the cached raw text of a document.
    """
    temp_doc = crud_temporary_document.get_temporary_document(db=db, document_id=request.document_id)
    if not temp_doc:
        raise HTTPException(status_code=404, detail="Document not found or expired.")

    raw_text = temp_doc.text_content
    
    # WARNING: Using exec is a security risk. In a production environment,
    # this should be replaced with a properly sandboxed execution environment.
    local_scope = {"raw_text": raw_text, "processed_text": ""}
    try:
        byte_code = compile_restricted(request.code, '<string>', 'exec')
        exec(byte_code, {"__builtins__": safe_builtins}, local_scope)
        processed_text = local_scope.get("processed_text", "")
        return {"processed_text": processed_text}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error executing code: {str(e)}")

class KnowledgeBaseCreateFromURL(BaseModel):
    url: HttpUrl
    name: str
    description: str | None = None
    knowledge_base_id: Optional[int] = None # New field for appending

@router.post("/upload", response_model=schemas_knowledge_base.KnowledgeBase, dependencies=[Depends(require_permission("knowledgebase:create"))])
def upload_knowledge_base_file(
    *,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    file: UploadFile = File(...),
    name: str = Form(...),
    description: str = Form(None),
    embedding_model: str = Form("nvidia"), # Add embedding_model to the form
    vector_store_type: str = Form("chroma") # Add vector_store_type to the form
):
    """
    Upload a file to create a new knowledge base.
    """
    # Create a simple object that mimics the Agent model for the purpose of passing the embedding model
    agent = SimpleNamespace(embedding_model=embedding_model)
    
    knowledge_base = knowledge_base_processing_service.process_and_store_document(
        db=db, file=file, agent=agent, company_id=current_user.company_id, name=name, description=description, vector_store_type=vector_store_type
    )
    return knowledge_base

@router.post("/from-url", response_model=schemas_knowledge_base.KnowledgeBase, dependencies=[Depends(require_permission("knowledgebase:create"))])
def create_knowledge_base_from_url(
    kb_from_url: KnowledgeBaseCreateFromURL,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    try:
        content = knowledge_base_service.extract_text_from_url(str(kb_from_url.url))
        
        if kb_from_url.knowledge_base_id:
            # Append to existing knowledge base
            existing_kb = knowledge_base_service.get_knowledge_base(db, kb_from_url.knowledge_base_id, current_user.company_id)
            if not existing_kb:
                raise HTTPException(status_code=404, detail="Existing Knowledge Base not found")
            
            updated_content = existing_kb.content + "\n\n" + content # Append new content
            updated_kb = schemas_knowledge_base.KnowledgeBaseUpdate(
                name=existing_kb.name, # Keep existing name
                description=existing_kb.description, # Keep existing description
                content=updated_content
            )
            return knowledge_base_service.update_knowledge_base(db, existing_kb.id, updated_kb, current_user.company_id)
        else:
            # Create new knowledge base
            knowledge_base = schemas_knowledge_base.KnowledgeBaseCreate(
                name=kb_from_url.name,
                description=kb_from_url.description,
                content=content
            )
            return knowledge_base_service.create_knowledge_base(db, knowledge_base, current_user.company_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/", response_model=schemas_knowledge_base.KnowledgeBase, dependencies=[Depends(require_permission("knowledgebase:create"))])
def create_knowledge_base(
    knowledge_base: schemas_knowledge_base.KnowledgeBaseCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user),
    embedding_model: str = Form("nvidia"), # Add embedding_model to the form
    vector_store_type: str = Form("chroma") # Add vector_store_type to the form
):
    agent = SimpleNamespace(embedding_model=embedding_model)
    return knowledge_base_processing_service.process_and_store_text(
        db=db, text=knowledge_base.content, agent=agent, company_id=current_user.company_id, name=knowledge_base.name, description=knowledge_base.description, vector_store_type=vector_store_type
    )

@router.get("/{knowledge_base_id}", response_model=schemas_knowledge_base.KnowledgeBase, dependencies=[Depends(require_permission("knowledgebase:read"))])
def get_knowledge_base(
    knowledge_base_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_knowledge_base = knowledge_base_service.get_knowledge_base(db, knowledge_base_id, current_user.company_id)
    if db_knowledge_base is None:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    return db_knowledge_base

@router.get("/", response_model=List[schemas_knowledge_base.KnowledgeBase], dependencies=[Depends(require_permission("knowledgebase:read"))])
def get_knowledge_bases(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    return knowledge_base_service.get_knowledge_bases(db, current_user.company_id, skip=skip, limit=limit)

@router.put("/{knowledge_base_id}", response_model=schemas_knowledge_base.KnowledgeBase, dependencies=[Depends(require_permission("knowledgebase:update"))])
def update_knowledge_base(
    knowledge_base_id: int,
    knowledge_base: schemas_knowledge_base.KnowledgeBaseUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_knowledge_base = knowledge_base_service.update_knowledge_base(db, knowledge_base_id, knowledge_base, current_user.company_id)
    if db_knowledge_base is None:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    return db_knowledge_base

@router.delete("/{knowledge_base_id}", dependencies=[Depends(require_permission("knowledgebase:delete"))])
def delete_knowledge_base(
    knowledge_base_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    db_knowledge_base = knowledge_base_service.delete_knowledge_base(db, knowledge_base_id, current_user.company_id)
    if db_knowledge_base is None:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    return {"message": "Knowledge Base deleted successfully"}

@router.post("/{knowledge_base_id}/generate-qna", response_model=schemas_knowledge_base.KnowledgeBaseQnA, dependencies=[Depends(require_permission("knowledgebase:update"))])
async def generate_qna_for_knowledge_base(
    knowledge_base_id: int,
    qna_generate: schemas_knowledge_base.KnowledgeBaseQnAGenerate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    try:
        generated_content = await knowledge_base_service.generate_qna_from_knowledge_base(db, knowledge_base_id, current_user.company_id, qna_generate.prompt)
        
        # Update the knowledge base with the generated Q&A
        updated_kb_schema = schemas_knowledge_base.KnowledgeBaseUpdate(content=generated_content)
        updated_kb = knowledge_base_service.update_knowledge_base(db, knowledge_base_id, updated_kb_schema, current_user.company_id)
        
        if not updated_kb:
            raise HTTPException(status_code=404, detail="Knowledge Base not found after Q&A generation")

        return schemas_knowledge_base.KnowledgeBaseQnA(generated_content=generated_content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate Q&A: {e}")

class KnowledgeBaseContent(BaseModel):
    content: str

@router.get("/{knowledge_base_id}/content", response_model=KnowledgeBaseContent, dependencies=[Depends(require_permission("knowledgebase:read"))])
def get_knowledge_base_content(
    knowledge_base_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    content = knowledge_base_service.get_knowledge_base_content(db, knowledge_base_id, current_user.company_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Knowledge Base content not found")
    return KnowledgeBaseContent(content=content)

class KnowledgeBaseDownloadUrl(BaseModel):
    download_url: str

@router.get("/{knowledge_base_id}/download-url", response_model=KnowledgeBaseDownloadUrl, dependencies=[Depends(require_permission("knowledgebase:read"))])
def get_knowledge_base_download_url(
    knowledge_base_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    download_url = knowledge_base_service.get_knowledge_base_download_url(db, knowledge_base_id, current_user.company_id)
    if download_url is None:
        raise HTTPException(status_code=404, detail="Knowledge Base download url not found")
    return KnowledgeBaseDownloadUrl(download_url=download_url)
