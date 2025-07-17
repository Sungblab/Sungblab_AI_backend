from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool  # NullPool 대신 QueuePool 사용
from app.core.config import settings


engine = create_engine(
    settings.SQLALCHEMY_DATABASE_URL,
    poolclass=QueuePool,
    pool_size=20,  # 큰 서비스용 연결 풀 크기 증가
    max_overflow=30,  # 총 50개 연결 허용
    pool_pre_ping=True,
    pool_recycle=1800,  # 30분마다 연결 재활용 (장기간 안정성)
    pool_reset_on_return='commit',
    pool_timeout=30,  # 타임아웃 충분히 설정
    echo=False,
    connect_args={
        "connect_timeout": 15,  # 연결 타임아웃 여유있게 설정
        "sslmode": "require",
        "keepalives_idle": 120,  # 2분으로 설정 (더 자주 체크)
        "keepalives_interval": 10,  # 10초마다 keepalive
        "keepalives_count": 5,  # 더 많은 재시도
        "application_name": "sungblab_api"
    }
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

def get_db_connection():
    """데이터베이스 연결 컨텍스트 매니저"""
    db = SessionLocal()
    try:
        return db
    except Exception as e:
        db.close()
        raise e

class DatabaseManager:
    """데이터베이스 연결 관리자"""
    
    @staticmethod
    def get_connection_info():
        """연결 풀 정보 반환"""
        return {
            "pool_size": engine.pool.size(),
            "checked_in": engine.pool.checkedin(),
            "checked_out": engine.pool.checkedout(),
            "overflow": engine.pool.overflow(),
            "invalid": engine.pool.invalid()
        }
    
    @staticmethod
    def dispose_connections():
        """모든 연결 정리"""
        engine.dispose()
    
    @staticmethod
    def test_connection():
        """연결 테스트"""
        try:
            connection = engine.connect()
            connection.close()
            return True
        except Exception as e:
            return False 