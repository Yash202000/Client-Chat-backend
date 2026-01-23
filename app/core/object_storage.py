import boto3
from botocore.client import Config
import chromadb
from chromadb.api.client import Client as ChromaClient
from app.core.config import settings

scheme = 'https' if settings.minio_secure else 'http'
endpoint_url = f'{scheme}://{settings.minio_endpoint}'

s3_client = boto3.client(
    's3',
    endpoint_url=endpoint_url,
    aws_access_key_id=settings.minio_access_key,
    aws_secret_access_key=settings.minio_secret_key,
    config=Config(signature_version='s3v4'),
    use_ssl=settings.minio_secure
)

BUCKET_NAME = settings.minio_bucket

# Default ChromaDB client (for backwards compatibility during migration)
if settings.CHROMA_DB_HOST:
    print(f"Connecting to ChromaDB at {settings.CHROMA_DB_HOST}:{settings.CHROMA_DB_PORT}")
    chroma_client = chromadb.HttpClient(host=settings.CHROMA_DB_HOST, port=settings.CHROMA_DB_PORT)
else:
    chroma_client = ChromaClient()


# =============================================================================
# Multi-Tenant ChromaDB Support
# =============================================================================
# Each company gets its own tenant for complete data isolation.
# This prevents any accidental cross-company data access.
# =============================================================================

_company_chroma_clients = {}


def get_company_chroma_client(company_id: int):
    """
    Get a ChromaDB client for a specific company using multi-tenancy.
    Each company gets its own tenant for complete data isolation.

    Args:
        company_id: The company ID to get the client for

    Returns:
        A ChromaDB client scoped to the company's tenant
    """
    if company_id in _company_chroma_clients:
        return _company_chroma_clients[company_id]

    tenant_name = f"company_{company_id}"
    database_name = "knowledge_base"

    if settings.CHROMA_DB_HOST:
        # For remote ChromaDB server, use multi-tenancy
        try:
            # Create admin client to manage tenants
            admin_client = chromadb.AdminClient(
                chromadb.Settings(
                    chroma_server_host=settings.CHROMA_DB_HOST,
                    chroma_server_http_port=str(settings.CHROMA_DB_PORT),
                    anonymized_telemetry=False
                )
            )

            # Create tenant if not exists
            try:
                admin_client.get_tenant(tenant_name)
            except Exception:
                admin_client.create_tenant(tenant_name)
                print(f"Created ChromaDB tenant: {tenant_name}")

            # Create database if not exists
            try:
                admin_client.get_database(database_name, tenant=tenant_name)
            except Exception:
                admin_client.create_database(database_name, tenant=tenant_name)
                print(f"Created ChromaDB database: {database_name} for tenant: {tenant_name}")

            # Create tenant-specific client
            client = chromadb.HttpClient(
                host=settings.CHROMA_DB_HOST,
                port=settings.CHROMA_DB_PORT,
                tenant=tenant_name,
                database=database_name
            )
        except Exception as e:
            # Fallback to default client if multi-tenancy not supported
            print(f"Warning: ChromaDB multi-tenancy failed ({e}), using default client")
            client = chromadb.HttpClient(
                host=settings.CHROMA_DB_HOST,
                port=settings.CHROMA_DB_PORT
            )
    else:
        # Local ChromaDB (development) - no multi-tenancy, use default client
        client = chromadb.Client(
            chromadb.Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )

    _company_chroma_clients[company_id] = client
    return client


def delete_company_tenant(company_id: int):
    """
    Delete all collections for a company's ChromaDB tenant.
    Call this when a company is deleted.

    Args:
        company_id: The company ID whose tenant to clean up
    """
    tenant_name = f"company_{company_id}"

    try:
        client = get_company_chroma_client(company_id)
        collections = client.list_collections()
        for collection in collections:
            client.delete_collection(collection.name)
            print(f"Deleted collection: {collection.name} from tenant: {tenant_name}")
    except Exception as e:
        print(f"Error cleaning up tenant {tenant_name}: {e}")

    # Remove from cache
    if company_id in _company_chroma_clients:
        del _company_chroma_clients[company_id]


def clear_company_chroma_cache():
    """
    Clear the cached ChromaDB clients.
    Useful for testing or when connection settings change.
    """
    global _company_chroma_clients
    _company_chroma_clients = {}
