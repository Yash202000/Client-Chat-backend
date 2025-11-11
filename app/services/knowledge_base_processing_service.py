from sqlalchemy.orm import Session
from app.models.knowledge_base import KnowledgeBase
from app.services.agent_execution_service import _get_embeddings
from app.core.object_storage import s3_client, BUCKET_NAME, chroma_client
import uuid
from app.core.config import settings
import tempfile
import os
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from app.services.faiss_vector_database import VectorDatabase
from app.llm_providers.nvidia_api_provider import NVIDIAEmbeddings
from app.services.docx_loader import DOCXLoader

def process_and_store_text(db: Session, text: str, agent: dict, company_id: int, name: str, description: str, vector_store_type: str = "chroma"):
    """
    Orchestrates the text processing pipeline:
    1. Chunks the text.
    2. Generates embeddings for each chunk.
    3. Creates a new, unique collection in ChromaDB or a FAISS index.
    4. Adds the chunks and their embeddings to the new vector store.
    5. Saves a new entry in the knowledge_bases table.
    """
    # 1. Chunk Text
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len,
        separators=["\n\n", "\n", " ", ""]
    )
    text_chunks = text_splitter.split_text(text)

    # 2. Generate Embeddings
    embeddings_instance = NVIDIAEmbeddings() # Assuming NVIDIAEmbeddings is the chosen embedding model
    embeddings = _get_embeddings(agent, text_chunks)

    chroma_collection_name = None
    faiss_index_id = None

    if vector_store_type == "chroma":
        print("Creating ChromaDB collection")
        # Create ChromaDB Collection
        collection_name = f"kb_{company_id}_{uuid.uuid4()}"
        collection = chroma_client.create_collection(name=collection_name)
        collection.add(
            embeddings=embeddings.tolist(),
            documents=text_chunks,
            ids=[f"id_{i}" for i in range(len(text_chunks))]
        )
        chroma_collection_name = collection_name
    elif vector_store_type == "faiss":
        # Create FAISS index
        faiss_index_id = str(uuid.uuid4())
        # For FAISS, we need a directory to store the index
        faiss_db_path = os.path.join(settings.FAISS_INDEX_DIR, str(company_id), faiss_index_id)
        
        faiss_db = VectorDatabase(
            embeddings=embeddings_instance, 
            db_path=faiss_db_path, 
            index_name=faiss_index_id # Use the ID as the index name within the path
        )
        faiss_db.create_index_from_texts(text_chunks) # Pass langchain Document objects
        faiss_db.save_index()
    else:
        raise ValueError(f"Unsupported vector store type: {vector_store_type}")

    # 3. Save KnowledgeBase Entry
    kb_entry = KnowledgeBase(
        name=name,
        description=description,
        company_id=company_id,
        type='local',
        storage_type=None,
        storage_details=None,
        chroma_collection_name=chroma_collection_name,
        faiss_index_id=faiss_index_id,
        content=text
    )
    db.add(kb_entry)
    db.commit()
    db.refresh(kb_entry)

    return kb_entry

def process_and_store_document(db: Session, file, agent: dict, company_id: int, name: str, description: str, vector_store_type: str = "chroma"):
    """
    Orchestrates the document processing pipeline:
    1. Uploads the source document to S3/MinIO.
    2. Parses the document based on file type (PDF or TXT).
    3. Chunks the text.
    4. Generates embeddings for each chunk.
    5. Creates a new, unique collection in ChromaDB or a FAISS index.
    6. Adds the chunks and their embeddings to the new vector store.
    7. Saves a new entry in the knowledge_bases table.
    """
    # 1. Read file content once
    file_content = file.file.read()

    # 2. Upload to S3
    file_key = f"{company_id}/{uuid.uuid4()}-{file.filename}"
    try:
        s3_client.put_object(Body=file_content, Bucket=BUCKET_NAME, Key=file_key)
    except Exception as e:
        print(f"Error uploading to S3: {e}")
        raise

    # 3. Parse Document based on file type
    file_extension = os.path.splitext(file.filename)[1].lower()
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
        tmp_file.write(file_content)
        tmp_file_path = tmp_file.name

    try:
        if file_extension == '.pdf':
            loader = PyPDFLoader(tmp_file_path)
        elif file_extension == '.txt':
            loader = TextLoader(tmp_file_path)
        elif file_extension == '.docx':
            loader = DOCXLoader(tmp_file_path)
        else:
            # Provide helpful error message
            supported_types = ['.pdf', '.txt', '.docx']
            raise ValueError(
                f"Unsupported file type: {file_extension}. "
                f"Supported formats: {', '.join(supported_types)}. "
                f"Note: Legacy .doc files must be converted to .docx or .pdf first."
            )

        documents = loader.load()
    finally:
        os.remove(tmp_file_path)

    # 4. Chunk Text
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len,
        separators=["\n\n", "\n", " ", ""]
    )
    split_docs = text_splitter.split_documents(documents)
    text_chunks = [doc.page_content for doc in split_docs]

    # 5. Generate Embeddings
    embeddings_instance = NVIDIAEmbeddings() # Assuming NVIDIAEmbeddings is the chosen embedding model
    embeddings = _get_embeddings(agent, text_chunks)

    chroma_collection_name = None
    faiss_index_id = None

    if vector_store_type == "chroma":
        print("Creating ChromaDB collection")
        # Create ChromaDB Collection
        collection_name = f"kb_{company_id}_{uuid.uuid4()}"
        collection = chroma_client.create_collection(name=collection_name)
        collection.add(
            embeddings=embeddings.tolist(),
            documents=text_chunks,
            ids=[f"id_{i}" for i in range(len(text_chunks))]
        )
        chroma_collection_name = collection_name
    elif vector_store_type == "faiss":
        # Create FAISS index
        faiss_index_id = str(uuid.uuid4())
        # For FAISS, we need a directory to store the index
        faiss_db_path = os.path.join(settings.FAISS_INDEX_DIR, str(company_id), faiss_index_id)
        
        faiss_db = VectorDatabase(
            embeddings=embeddings_instance, 
            db_path=faiss_db_path, 
            index_name=faiss_index_id # Use the ID as the index name within the path
        )
        faiss_db.create_index(split_docs) # Pass langchain Document objects
        faiss_db.save_index()
    else:
        raise ValueError(f"Unsupported vector store type: {vector_store_type}")

    # 7. Save KnowledgeBase Entry
    kb_entry = KnowledgeBase(
        name=name,
        description=description,
        company_id=company_id,
        type='local',
        storage_type='s3',
        storage_details={"bucket": BUCKET_NAME, "key": file_key},
        chroma_collection_name=chroma_collection_name,
        faiss_index_id=faiss_index_id
    )
    db.add(kb_entry)
    db.commit()
    db.refresh(kb_entry)

    return kb_entry