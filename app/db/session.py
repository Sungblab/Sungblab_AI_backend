from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from app.core.config import settings

# Supabase PostgreSQL 연결 설정
engine = create_engine(
    settings.SQLALCHEMY_DATABASE_URL,
    poolclass=NullPool,  # 연결 풀 비활성화
    pool_pre_ping=True,
    connect_args={
        "connect_timeout": 10,
        "sslmode": "require"  # Supabase는 SSL 연결 필요
    }
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close() 