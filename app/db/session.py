from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool  # NullPool 대신 QueuePool 사용
from app.core.config import settings

# Supabase PostgreSQL 연결 설정 최적화
engine = create_engine(
    settings.SQLALCHEMY_DATABASE_URL,
    poolclass=QueuePool,  # 연결 풀 활성화
    pool_size=5,  # 기본 연결 풀 크기
    max_overflow=10,  # 최대 추가 연결 수
    pool_pre_ping=True,
    pool_recycle=300,  # 5분마다 연결 재활용
    pool_reset_on_return='commit',  # 연결 반환 시 커밋
    connect_args={
        "connect_timeout": 5,  # 연결 시간 단축
        "sslmode": "require",
        "keepalives_idle": 600,  # keepalive 설정
        "keepalives_interval": 30,
        "keepalives_count": 3
    }
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close() 