"""
데이터베이스 연결 재시도 로직
SSL 연결 끊어짐 문제 해결을 위한 강화된 세션 관리
"""

import time
import logging
from typing import Generator, Any
from functools import wraps
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DisconnectionError
from sqlalchemy import text
from app.db.session import SessionLocal, engine

logger = logging.getLogger(__name__)

class DatabaseConnectionError(Exception):
    """데이터베이스 연결 관련 오류"""
    pass

def is_connection_error(error: Exception) -> bool:
    """연결 관련 오류인지 확인"""
    error_msg = str(error).lower()
    connection_errors = [
        "ssl connection has been closed unexpectedly",
        "connection already closed",
        "server closed the connection unexpectedly",
        "connection timed out",
        "connection refused",
        "lost connection",
        "broken pipe",
        "network unreachable"
    ]
    return any(err in error_msg for err in connection_errors)

def retry_db_operation(max_retries: int = 3, delay: float = 1.0):
    """데이터베이스 작업 재시도 데코레이터"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (OperationalError, DisconnectionError) as e:
                    last_error = e
                    
                    if not is_connection_error(e):
                        # 연결 오류가 아닌 경우 즉시 재발생
                        raise
                    
                    if attempt < max_retries:
                        logger.warning(
                            f"DB 연결 오류 (시도 {attempt + 1}/{max_retries + 1}): {e}"
                        )
                        
                        # 연결 풀 정리
                        try:
                            engine.dispose()
                        except Exception as dispose_error:
                            logger.error(f"엔진 정리 실패: {dispose_error}")
                        
                        # 재시도 전 대기
                        time.sleep(delay * (attempt + 1))
                    else:
                        logger.error(f"DB 연결 재시도 최대 횟수 초과: {e}")
                        raise DatabaseConnectionError(
                            f"데이터베이스 연결 실패 (최대 {max_retries}회 재시도): {e}"
                        ) from e
                except Exception as e:
                    # 다른 종류의 오류는 즉시 재발생
                    raise
            
            # 이 지점에 도달하면 안 됨
            raise last_error
        
        return wrapper
    return decorator

class RobustSession:
    """강화된 데이터베이스 세션"""
    
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self._session: Session = None
    
    def __enter__(self):
        self._session = self._get_session_with_retry()
        return self._session
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            try:
                if exc_type:
                    self._session.rollback()
                else:
                    self._session.commit()
            except Exception as e:
                logger.error(f"세션 종료 중 오류: {e}")
                self._session.rollback()
            finally:
                self._session.close()
    
    @retry_db_operation(max_retries=3, delay=1.0)
    def _get_session_with_retry(self) -> Session:
        """재시도 로직이 포함된 세션 생성"""
        session = SessionLocal()
        
        # 연결 상태 확인
        try:
            session.execute(text("SELECT 1"))
            return session
        except Exception as e:
            session.close()
            raise

@retry_db_operation(max_retries=3, delay=1.0)
def get_robust_db() -> Generator[Session, None, None]:
    """강화된 데이터베이스 세션 생성기"""
    session = SessionLocal()
    try:
        # 연결 상태 사전 확인
        session.execute(text("SELECT 1"))
        yield session
    except Exception as e:
        session.rollback()
        
        # SSL 연결 오류인 경우 엔진 재시작
        if is_connection_error(e):
            logger.warning(f"연결 오류 감지, 엔진 재시작: {e}")
            engine.dispose()
        
        raise
    finally:
        session.close()

def execute_with_retry(query: str, params: dict = None, max_retries: int = 3):
    """재시도 로직이 포함된 쿼리 실행"""
    @retry_db_operation(max_retries=max_retries, delay=1.0)
    def _execute():
        with RobustSession() as session:
            if params:
                return session.execute(text(query), params).fetchall()
            else:
                return session.execute(text(query)).fetchall()
    
    return _execute()

def test_connection_health() -> bool:
    """연결 상태 테스트"""
    try:
        with RobustSession() as session:
            session.execute(text("SELECT 1"))
            return True
    except Exception as e:
        logger.error(f"연결 상태 테스트 실패: {e}")
        return False

# 백그라운드 연결 상태 모니터링
import asyncio

async def monitor_connection_health(check_interval: int = 60):
    """연결 상태 모니터링 백그라운드 작업"""
    consecutive_failures = 0
    max_consecutive_failures = 3
    
    while True:
        try:
            is_healthy = test_connection_health()
            
            if is_healthy:
                if consecutive_failures > 0:
                    logger.info("데이터베이스 연결 복구됨")
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                logger.warning(f"연결 상태 불량 ({consecutive_failures}회 연속)")
                
                if consecutive_failures >= max_consecutive_failures:
                    logger.error("연결 상태 심각, 엔진 재시작")
                    engine.dispose()
                    consecutive_failures = 0
            
            await asyncio.sleep(check_interval)
            
        except Exception as e:
            logger.error(f"연결 상태 모니터링 오류: {e}")
            await asyncio.sleep(check_interval // 2)