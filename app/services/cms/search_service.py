from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_
import uuid
import json

from app.models.content_item import ContentItem
from app.models.content_type import ContentType
from app.models.knowledge_base import KnowledgeBase
from app.core.object_storage import get_company_chroma_client
from app.llm_providers.nvidia_api_provider import NVIDIAEmbeddings
from app.schemas.cms import ContentStatus, ContentVisibility, FieldType


def get_searchable_text(content_type: ContentType, data: Dict[str, Any]) -> str:
    """
    Extract searchable text from content item data based on field schema.
    Only includes fields marked as searchable.
    """
    if not content_type.field_schema:
        # Fallback: concatenate all string values
        texts = []
        for key, value in data.items():
            if isinstance(value, str):
                texts.append(f"{key}: {value}")
        return "\n".join(texts)

    searchable_texts = []

    for field_def in content_type.field_schema:
        if not field_def.get('searchable', False):
            continue

        slug = field_def['slug']
        field_type = field_def.get('type')
        value = data.get(slug)

        if value is None:
            continue

        # Extract text based on field type
        if field_type in [FieldType.TEXT.value, FieldType.RICH_TEXT.value]:
            if isinstance(value, str):
                # Strip HTML tags for rich text
                import re
                clean_text = re.sub(r'<[^>]+>', '', value)
                searchable_texts.append(f"{field_def.get('name', slug)}: {clean_text}")

        elif field_type == FieldType.TAGS.value:
            if isinstance(value, list):
                tags_text = ", ".join(str(t) for t in value)
                searchable_texts.append(f"Tags: {tags_text}")

        elif field_type == FieldType.SELECT.value:
            if isinstance(value, str):
                searchable_texts.append(f"{field_def.get('name', slug)}: {value}")

    return "\n".join(searchable_texts)


def get_embeddings(texts: List[str]) -> List[List[float]]:
    """Generate embeddings for a list of texts using NVIDIA embeddings."""
    try:
        embeddings_client = NVIDIAEmbeddings()
        embeddings = embeddings_client.embed_documents(texts)
        return embeddings
    except Exception as e:
        print(f"Error generating embeddings: {e}")
        raise ValueError(f"Failed to generate embeddings: {str(e)}")


def get_query_embedding(query: str) -> List[float]:
    """Generate embedding for a search query."""
    try:
        embeddings_client = NVIDIAEmbeddings()
        return embeddings_client.embed_query(query)
    except Exception as e:
        print(f"Error generating query embedding: {e}")
        raise ValueError(f"Failed to generate query embedding: {str(e)}")


def get_cms_collection_name(knowledge_base_id: Optional[int] = None) -> str:
    """Generate collection name for CMS-only content (not linked to KB)."""
    if knowledge_base_id:
        return f"cms_kb_{knowledge_base_id}"
    return "cms_content"


def get_kb_collection_name(db: Session, knowledge_base_id: int, company_id: int) -> Optional[str]:
    """
    Get the ChromaDB collection name for a knowledge base.
    Returns the existing KB collection name if it exists.
    """
    kb = db.query(KnowledgeBase).filter(
        and_(
            KnowledgeBase.id == knowledge_base_id,
            KnowledgeBase.company_id == company_id
        )
    ).first()

    if kb and kb.chroma_collection_name:
        return kb.chroma_collection_name
    return None


def index_content_item(
    db: Session,
    content_item: ContentItem,
    content_type: ContentType
) -> Optional[str]:
    """
    Index a content item in ChromaDB for semantic search.

    If the content item is linked to a Knowledge Base, it will be indexed
    in the same collection as the KB's documents, enabling unified RAG search.

    Returns the chroma_doc_id.
    """
    # Only index published content with searchable fields
    if content_item.status != ContentStatus.PUBLISHED.value:
        return None

    # Extract searchable text
    searchable_text = get_searchable_text(content_type, content_item.data)
    if not searchable_text.strip():
        return None

    try:
        # Get company-specific ChromaDB client
        chroma_client = get_company_chroma_client(content_item.company_id)

        # Determine which collection to use
        collection_name = None
        if content_item.knowledge_base_id:
            # Try to use the KB's existing collection for unified RAG search
            collection_name = get_kb_collection_name(
                db, content_item.knowledge_base_id, content_item.company_id
            )

        # Fall back to CMS-specific collection if no KB collection exists
        if not collection_name:
            collection_name = get_cms_collection_name(content_item.knowledge_base_id)

        # Get or create collection
        try:
            collection = chroma_client.get_collection(name=collection_name)
        except Exception:
            collection = chroma_client.create_collection(name=collection_name)

        # Generate document ID with cms_ prefix to distinguish from document chunks
        doc_id = content_item.chroma_doc_id or f"cms_{content_type.slug}_{content_item.id}"

        # Generate embedding
        embedding = get_query_embedding(searchable_text)

        # Prepare metadata with source_type for RAG retrieval
        # Serialize the full structured data for agent responses
        metadata = {
            "source_type": "cms",  # Distinguishes from "document" chunks
            "content_item_id": content_item.id,
            "content_type_id": content_type.id,
            "content_type_slug": content_type.slug,
            "content_type_name": content_type.name,
            "company_id": content_item.company_id,
            "visibility": content_item.visibility,
            "status": content_item.status,
            # Store structured data as JSON string for retrieval
            "structured_data": json.dumps(content_item.data, ensure_ascii=False)
        }
        if content_item.knowledge_base_id:
            metadata["knowledge_base_id"] = content_item.knowledge_base_id

        # Upsert to collection
        collection.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[searchable_text],
            metadatas=[metadata]
        )

        return doc_id

    except Exception as e:
        print(f"Error indexing content item {content_item.id}: {e}")
        return None


def remove_content_item_from_index(
    company_id: int,
    chroma_doc_id: str,
    knowledge_base_id: Optional[int] = None,
    db: Session = None
) -> bool:
    """
    Remove a content item from the ChromaDB index.

    Tries to remove from KB collection first (if kb_id provided and db session available),
    then falls back to CMS-specific collection.
    """
    if not chroma_doc_id:
        return False

    try:
        chroma_client = get_company_chroma_client(company_id)

        # Try KB collection first if knowledge_base_id and db are provided
        if knowledge_base_id and db:
            kb_collection_name = get_kb_collection_name(db, knowledge_base_id, company_id)
            if kb_collection_name:
                try:
                    collection = chroma_client.get_collection(name=kb_collection_name)
                    collection.delete(ids=[chroma_doc_id])
                    return True
                except Exception:
                    pass  # Try CMS collection as fallback

        # Try CMS-specific collection
        collection_name = get_cms_collection_name(knowledge_base_id)
        try:
            collection = chroma_client.get_collection(name=collection_name)
            collection.delete(ids=[chroma_doc_id])
            return True
        except Exception:
            return False

    except Exception as e:
        print(f"Error removing content from index: {e}")
        return False


def search_content(
    db: Session,
    company_id: int,
    query: str,
    content_type_slug: Optional[str] = None,
    knowledge_base_id: Optional[int] = None,
    visibility_filter: Optional[List[str]] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Perform semantic search on CMS content.
    Returns list of search results with scores.
    """
    try:
        # Get company-specific ChromaDB client
        chroma_client = get_company_chroma_client(company_id)

        # Get collection
        collection_name = get_cms_collection_name(knowledge_base_id)
        try:
            collection = chroma_client.get_collection(name=collection_name)
        except Exception:
            # Collection doesn't exist, return empty results
            return []

        # Generate query embedding
        query_embedding = get_query_embedding(query)

        # Build where filter
        where_filter = {}
        if content_type_slug:
            where_filter["content_type_slug"] = content_type_slug
        if visibility_filter:
            where_filter["visibility"] = {"$in": visibility_filter}

        # Perform search
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            where=where_filter if where_filter else None,
            include=["documents", "metadatas", "distances"]
        )

        # Process results
        search_results = []
        if results and results.get('ids') and results['ids'][0]:
            for i, doc_id in enumerate(results['ids'][0]):
                metadata = results['metadatas'][0][i] if results.get('metadatas') else {}
                document = results['documents'][0][i] if results.get('documents') else ""
                distance = results['distances'][0][i] if results.get('distances') else 0

                # Convert distance to similarity score (ChromaDB uses L2 distance)
                # Lower distance = more similar, so we invert it
                similarity_score = 1 / (1 + distance)

                # Get the actual content item from database
                content_item_id = metadata.get('content_item_id')
                if content_item_id:
                    content_item = db.query(ContentItem).filter(
                        ContentItem.id == content_item_id
                    ).first()

                    if content_item:
                        search_results.append({
                            "id": content_item.id,
                            "content_type_slug": metadata.get('content_type_slug', ''),
                            "data": content_item.data,
                            "score": similarity_score,
                            "highlights": {
                                "matched_text": document[:500] if document else ""
                            }
                        })

        return search_results

    except Exception as e:
        print(f"Error performing search: {e}")
        raise ValueError(f"Search failed: {str(e)}")


def search_marketplace(
    db: Session,
    query: str,
    content_type_slug: Optional[str] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Search marketplace content across all companies.
    Only searches content with visibility='marketplace'.
    """
    # For marketplace search, we need to search across all company tenants
    # This is a simplified implementation - in production, you might want
    # a dedicated marketplace index

    all_results = []

    # Get all unique company IDs with marketplace content
    company_ids = db.query(ContentItem.company_id).filter(
        ContentItem.visibility == ContentVisibility.MARKETPLACE.value,
        ContentItem.status == ContentStatus.PUBLISHED.value
    ).distinct().all()

    for (company_id,) in company_ids:
        try:
            results = search_content(
                db=db,
                company_id=company_id,
                query=query,
                content_type_slug=content_type_slug,
                visibility_filter=[ContentVisibility.MARKETPLACE.value],
                limit=limit
            )
            all_results.extend(results)
        except Exception as e:
            print(f"Error searching company {company_id}: {e}")
            continue

    # Sort by score and limit
    all_results.sort(key=lambda x: x['score'], reverse=True)
    return all_results[:limit]


def reindex_content_type(
    db: Session,
    content_type_id: int,
    company_id: int
) -> Tuple[int, int]:
    """
    Reindex all content items of a specific content type.
    Returns (success_count, error_count).
    """
    content_type = db.query(ContentType).filter(
        and_(
            ContentType.id == content_type_id,
            ContentType.company_id == company_id
        )
    ).first()

    if not content_type:
        raise ValueError("Content type not found")

    content_items = db.query(ContentItem).filter(
        and_(
            ContentItem.content_type_id == content_type_id,
            ContentItem.company_id == company_id,
            ContentItem.status == ContentStatus.PUBLISHED.value
        )
    ).all()

    success_count = 0
    error_count = 0

    for item in content_items:
        try:
            doc_id = index_content_item(db, item, content_type)
            if doc_id:
                item.chroma_doc_id = doc_id
                success_count += 1
            else:
                error_count += 1
        except Exception as e:
            print(f"Error indexing item {item.id}: {e}")
            error_count += 1

    db.commit()
    return success_count, error_count


def reindex_all_content(
    db: Session,
    company_id: int,
    knowledge_base_id: Optional[int] = None
) -> Tuple[int, int]:
    """
    Reindex all published content for a company.
    Returns (success_count, error_count).
    """
    query = db.query(ContentItem).filter(
        and_(
            ContentItem.company_id == company_id,
            ContentItem.status == ContentStatus.PUBLISHED.value
        )
    )

    if knowledge_base_id:
        query = query.filter(ContentItem.knowledge_base_id == knowledge_base_id)

    content_items = query.all()

    success_count = 0
    error_count = 0

    # Cache content types
    content_types_cache = {}

    for item in content_items:
        try:
            # Get content type (with caching)
            if item.content_type_id not in content_types_cache:
                content_type = db.query(ContentType).filter(
                    ContentType.id == item.content_type_id
                ).first()
                content_types_cache[item.content_type_id] = content_type

            content_type = content_types_cache[item.content_type_id]
            if not content_type:
                error_count += 1
                continue

            doc_id = index_content_item(db, item, content_type)
            if doc_id:
                item.chroma_doc_id = doc_id
                success_count += 1
            else:
                error_count += 1
        except Exception as e:
            print(f"Error indexing item {item.id}: {e}")
            error_count += 1

    db.commit()
    return success_count, error_count
