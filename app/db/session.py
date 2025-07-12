from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool  # NullPool 대신 QueuePool 사용
from app.core.config import settings


engine = create_engine(
    settings.SQLALCHEMY_DATABASE_URL,
    poolclass=QueuePool,  # 연결 풀 활성화
    pool_size=10,  # 기본 연결 풀 크기 증가 (동시 요청 대응)
    max_overflow=20,  # 최대 추가 연결 수 증가 (총 30개)
    pool_pre_ping=True,
    pool_recycle=1800,  # 30분마다 연결 재활용 (더 자주)
    pool_reset_on_return='commit',  # 연결 반환 시 커밋
    pool_timeout=15,  # 연결 대기 시간 제한 (단축)
    echo=False,  # SQL 로깅 비활성화 (성능 향상)
    connect_args={
        "connect_timeout": 10,  # 연결 타임아웃
        "sslmode": "require",
        "keepalives_idle": 300,  # keepalive 설정 (더 자주)
        "keepalives_interval": 15,
        "keepalives_count": 3,
        "application_name": "sungblab_api"  # 애플리케이션 식별
    }
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        # 에러 발생 시 롤백
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