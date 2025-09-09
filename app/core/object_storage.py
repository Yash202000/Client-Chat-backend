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

if settings.CHROMA_DB_HOST:
    print(f"Connecting to ChromaDB at {settings.CHROMA_DB_HOST}:{settings.CHROMA_DB_PORT}")
    chroma_client = chromadb.HttpClient(host=settings.CHROMA_DB_HOST, port=settings.CHROMA_DB_PORT)
else:
    chroma_client = ChromaClient()
