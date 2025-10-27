
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings


engine = create_engine(
    settings.DATABASE_URL,
    # connect_args={"check_same_thread": False}, # only for SQLite
    pool_size=50,  # 50 persistent connections in the pool
    max_overflow=30,  # 30 additional temporary connections (total: 80)
    pool_pre_ping=True,  # Test connections before using them to detect stale connections
    pool_recycle=3600,  # Recycle connections after 1 hour to prevent stale connections
    pool_timeout=60  # Wait up to 60 seconds for an available connection
    # Total max connections: 80 (leaves 20 of 100 for admin/monitoring/other apps)
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
