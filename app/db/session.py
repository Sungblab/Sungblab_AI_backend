from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from app.core.config import settings


engine = create_engine(
    settings.SQLALCHEMY_DATABASE_URL,
    poolclass=QueuePool,
    pool_size=5,  # SSL 연결 안정성을 위해 줄임
    max_overflow=10,  # 총 15개로 제한
    pool_pre_ping=True,  # 연결 재사용 전 ping 테스트
    pool_recycle=300,  # 5분마다 연결 재활용 (SSL 타임아웃 방지)
    pool_reset_on_return='commit',
    pool_timeout=30,  # 연결 대기 시간 증가
    echo=False,
    connect_args={
        "connect_timeout": 30,  # 연결 타임아웃 증가
        "sslmode": "require",
        "sslcert": None,  # SSL 인증서 설정 명시
        "sslkey": None,
        "sslrootcert": None,
        "keepalives_idle": 60,  # 1분으로 단축 (더 자주 keepalive)
        "keepalives_interval": 10,  # 10초 간격
        "keepalives_count": 6,  # 재시도 횟수 증가
        "tcp_user_timeout": 30000,  # TCP 사용자 타임아웃 (30초)
        "application_name": "sungblab_api"
    }
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        # 연결 상태 확인 (SSL 연결 끊어짐 감지)
        db.execute(text("SELECT 1"))
        yield db
    except Exception as e:
        # 에러 발생 시 롤백
        db.rollback()
        # SSL 연결 오류인 경우 엔진 재시작
        if "SSL connection has been closed unexpectedly" in str(e):
            engine.dispose()
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