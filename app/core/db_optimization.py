"""
데이터베이스 최적화 유틸리티
"""

from __future__ import annotations
from typing import Dict, Any, Optional
import logging
import time
import asyncio
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.config import settings
from app.db.session import engine, SessionLocal
from app.monitoring.metrics import MetricsCollector

logger = logging.getLogger(__name__)

class DatabaseOptimizer:
    """데이터베이스 최적화 관리자"""
    
    def __init__(self):
        self.connection_check_interval = 30  # 30초마다 체크
        self.slow_query_threshold = 0.5  # 0.5초 이상 느린 쿼리
        self.pool_warning_threshold = 0.8  # 80% 이상 사용시 경고
        
    def get_connection_pool_status(self) -> Dict[str, Any]:
        """연결 풀 상태 확인"""
        if not settings.ENABLE_PERFORMANCE_MONITORING:
            return {}
        try:
            pool = engine.pool
            return {
                "pool_size": pool.size(),
                "checked_in": pool.checkedin(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow(),
                "invalid": pool.invalid(),
                "total_connections": pool.checkedout() + pool.checkedin(),
                "usage_percentage": (pool.checkedout() / (pool.size() + pool.overflow())) * 100
            }
        except Exception as e:
            return {"error": str(e)}
    
    def check_pool_health(self) -> bool:
        """연결 풀 건강성 확인"""
        if not settings.ENABLE_PERFORMANCE_MONITORING:
            return True
        try:
            status = self.get_connection_pool_status()
            
            # 메트릭 업데이트
            if "total_connections" in status:
                MetricsCollector.update_db_connections(status["total_connections"])
            
            # 경고 체크
            if status.get("usage_percentage", 0) > self.pool_warning_threshold * 100:
                logger.warning(f"DB 연결 풀 사용률 높음: {status['usage_percentage']:.1f}%")
                return False
                
            return True
        except Exception as e:
            logger.error(f"연결 풀 건강성 확인 실패: {e}", exc_info=True)
            return False
    
    def execute_with_monitoring(self, db: Session, query: str, params: Optional[Dict] = None) -> Any:
        """쿼리 실행 모니터링"""
        if not settings.ENABLE_PERFORMANCE_MONITORING:
            if params:
                result = db.execute(text(query), params)
            else:
                result = db.execute(text(query))
            return result

        start_time = time.time()
        
        try:
            if params:
                result = db.execute(text(query), params)
            else:
                result = db.execute(text(query))
            
            execution_time = time.time() - start_time
            
            # 느린 쿼리 로깅
            if execution_time > self.slow_query_threshold:
                logger.warning(f"느린 쿼리 감지: {execution_time:.3f}초 - {query[:100]}...")
            
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"쿼리 실행 실패: {execution_time:.3f}초 - {str(e)}", exc_info=True)
            raise
    
    def get_active_connections(self) -> int:
        """활성 연결 수 확인"""
        if not settings.ENABLE_PERFORMANCE_MONITORING:
            return 0
        try:
            db = SessionLocal()
            try:
                result = db.execute(text(
                    "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"
                ))
                return result.scalar()
            finally:
                db.close()
        except Exception as e:
            logger.error(f"활성 연결 수 확인 실패: {e}", exc_info=True)
            return 0
    
    def kill_idle_connections(self, idle_minutes: int = 30) -> int:
        """유휴 연결 정리"""
        if not settings.ENABLE_PERFORMANCE_MONITORING:
            return 0
        try:
            db = SessionLocal()
            try:
                # 30분 이상 유휴 상태인 연결 종료
                result = db.execute(text("""
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE state = 'idle'
                    AND state_change < now() - interval '%s minutes'
                    AND pid <> pg_backend_pid()
                """), (idle_minutes,))
                
                terminated_count = len(result.fetchall())
                if terminated_count > 0:
                    logger.info(f"유휴 연결 {terminated_count}개 정리 완료")
                
                return terminated_count
            finally:
                db.close()
        except Exception as e:
            logger.error(f"유휴 연결 정리 실패: {e}", exc_info=True)
            return 0
    
    def optimize_database_settings(self) -> bool:
        """데이터베이스 설정 최적화"""
        if not settings.ENABLE_PERFORMANCE_MONITORING:
            return True
        try:
            db = SessionLocal()
            try:
                # 연결 관련 설정 조정
                optimizations = [
                    "SET statement_timeout = '30s'",  # 쿼리 타임아웃
                    "SET idle_in_transaction_session_timeout = '60s'",  # 트랜잭션 유휴 타임아웃
                    "SET tcp_keepalives_idle = 300",  # TCP keepalive
                    "SET tcp_keepalives_interval = 30",
                    "SET tcp_keepalives_count = 3"
                ]
                
                for optimization in optimizations:
                    db.execute(text(optimization))
                
                db.commit()
                logger.info("데이터베이스 설정 최적화 완료")
                return True
                
            finally:
                db.close()
        except Exception as e:
            logger.error(f"데이터베이스 설정 최적화 실패: {e}", exc_info=True)
            return False

# 전역 인스턴스
db_optimizer = DatabaseOptimizer()

def get_db_with_monitoring():
    """모니터링이 포함된 DB 세션 생성"""
    if not settings.ENABLE_PERFORMANCE_MONITORING:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
    else:
        db = SessionLocal()
        try:
            # 연결 풀 상태 확인
            db_optimizer.check_pool_health()
            yield db
        finally:
            db.close()

def execute_query_with_timeout(db: Session, query: str, timeout: int = 30):
    """타임아웃이 있는 쿼리 실행"""
    if not settings.ENABLE_PERFORMANCE_MONITORING:
        try:
            db.execute(text(f"SET statement_timeout = '{timeout}s'"))
            result = db.execute(text(query))
            return result
        except Exception as e:
            logger.error(f"쿼리 타임아웃 또는 실행 실패: {e}", exc_info=True)
            raise
        finally:
            db.execute(text("SET statement_timeout = DEFAULT"))
    else:
        try:
            db.execute(text(f"SET statement_timeout = '{timeout}s'"))
            result = db.execute(text(query))
            return result
        except Exception as e:
            logger.error(f"쿼리 타임아웃 또는 실행 실패: {e}", exc_info=True)
            raise
        finally:
            db.execute(text("SET statement_timeout = DEFAULT"))

# 비동기 백그라운드 모니터링
async def monitor_database_performance():
    """데이터베이스 성능 모니터링 백그라운드 작업"""
    if not settings.ENABLE_PERFORMANCE_MONITORING:
        return
    while True:
        try:
            # 연결 풀 상태 확인
            pool_status = db_optimizer.get_connection_pool_status()
            
            # 활성 연결 수 확인
            active_connections = db_optimizer.get_active_connections()
            
            logger.info(f"DB 상태: 풀 사용률 {pool_status.get('usage_percentage', 0):.1f}%, 활성 연결 {active_connections}개")
            
            # 연결 풀 사용률이 높으면 유휴 연결 정리
            if pool_status.get('usage_percentage', 0) > 80:
                db_optimizer.kill_idle_connections(10)  # 10분 이상 유휴 연결 정리
            
            await asyncio.sleep(60)  # 1분마다 체크
            
        except Exception as e:
            logger.error(f"DB 모니터링 오류: {e}", exc_info=True)
            await asyncio.sleep(30)  # 오류 시 30초 후 재시도 