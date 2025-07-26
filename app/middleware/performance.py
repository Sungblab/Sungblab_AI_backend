import logging
import time
import os
import psutil
from datetime import datetime
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from typing import Callable

from app.core.config import settings

# 성능 로깅 설정
performance_logger = logging.getLogger("performance")
# 환경에 따라 로그 레벨 설정
if settings.ENVIRONMENT == "production":
    performance_logger.setLevel(logging.WARNING)
else:
    performance_logger.setLevel(logging.INFO)

class PerformanceMonitoringMiddleware(BaseHTTPMiddleware):
    """성능 모니터링 미들웨어"""
    
    def __init__(self, app, slow_request_threshold: float = 2.0):
        super().__init__(app)
        self.slow_request_threshold = slow_request_threshold
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not settings.ENABLE_PERFORMANCE_MONITORING:
            return await call_next(request)

        start_time = time.time()
        
        # 메모리 사용량 측정 (요청 시작 시점)
        process = psutil.Process(os.getpid())
        memory_before = process.memory_info().rss / 1024 / 1024  # MB
        cpu_before = process.cpu_percent()
        
        # 요청 처리
        response = await call_next(request)
        
        # 처리 시간 계산
        process_time = time.time() - start_time
        
        # 메모리 사용량 측정 (요청 완료 시점)
        memory_after = process.memory_info().rss / 1024 / 1024  # MB
        cpu_after = process.cpu_percent()
        
        # 응답 헤더에 성능 정보 추가
        response.headers["X-Process-Time"] = str(process_time)
        response.headers["X-Memory-Usage"] = f"{memory_after:.2f}MB"
        
        # 성능 로깅
        log_data = {
            "method": request.method,
            "url": str(request.url),
            "status_code": response.status_code,
            "process_time": round(process_time, 4),
            "memory_before": round(memory_before, 2),
            "memory_after": round(memory_after, 2),
            "memory_diff": round(memory_after - memory_before, 2),
            "cpu_before": round(cpu_before, 2),
            "cpu_after": round(cpu_after, 2),
            "timestamp": datetime.now().isoformat()
        }
        
        # 프로덕션 환경에서는 느린 요청만 로깅
        if settings.ENVIRONMENT == "production":
            if process_time > self.slow_request_threshold:
                performance_logger.warning(f"SLOW REQUEST: {log_data}")
        else:
            # 개발 환경에서만 모든 요청 로깅
            if process_time > self.slow_request_threshold:
                performance_logger.warning(f"SLOW REQUEST: {log_data}")
            else:
                performance_logger.info(f"REQUEST: {log_data}")
        
        return response

class DatabasePerformanceMonitor:
    """데이터베이스 성능 모니터링"""
    
    def __init__(self):
        self.query_count = 0
        self.total_query_time = 0
        self.slow_queries = []
        self.slow_query_threshold = 1.0  # 1초
    
    def log_query(self, query: str, execution_time: float):
        """쿼리 실행 로그"""
        if not settings.ENABLE_PERFORMANCE_MONITORING:
            return
        self.query_count += 1
        self.total_query_time += execution_time
        
        if execution_time > self.slow_query_threshold:
            self.slow_queries.append({
                "query": query[:200] + "..." if len(query) > 200 else query,
                "execution_time": round(execution_time, 4),
                "timestamp": datetime.now().isoformat()
            })
            
            # 느린 쿼리 로깅
            performance_logger.warning(f"SLOW QUERY: {query[:100]}... ({execution_time:.4f}s)")
    
    def get_stats(self) -> dict:
        """성능 통계 반환"""
        if not settings.ENABLE_PERFORMANCE_MONITORING:
            return {}
        return {
            "total_queries": self.query_count,
            "total_query_time": round(self.total_query_time, 4),
            "average_query_time": round(
                self.total_query_time / self.query_count if self.query_count > 0 else 0, 4
            ),
            "slow_queries_count": len(self.slow_queries),
            "slow_queries": self.slow_queries[-10:]  # 최근 10개
        }
    
    def reset_stats(self):
        """통계 초기화"""
        if not settings.ENABLE_PERFORMANCE_MONITORING:
            return
        self.query_count = 0
        self.total_query_time = 0
        self.slow_queries = []

# 전역 DB 성능 모니터
db_monitor = DatabasePerformanceMonitor()

def log_api_performance(func):
    """API 성능 로깅 데코레이터"""
    async def wrapper(*args, **kwargs):
        if not settings.ENABLE_PERFORMANCE_MONITORING:
            return await func(*args, **kwargs)

        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            execution_time = time.time() - start_time
            
            performance_logger.info(
                f"API {func.__name__} executed in {execution_time:.4f}s"
            )
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            performance_logger.error(
                f"API {func.__name__} failed after {execution_time:.4f}s: {str(e)}"
            )
            raise
    return wrapper 