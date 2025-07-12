from prometheus_client import Counter, Histogram, Gauge, generate_latest
from functools import wraps
import time
from typing import Dict, Any
from app.core.config import settings

# Prometheus 메트릭 정의
REQUESTS_TOTAL = Counter(
    'sungblab_requests_total',
    'Total number of requests',
    ['method', 'endpoint', 'status_code']
)

REQUEST_DURATION = Histogram(
    'sungblab_request_duration_seconds',
    'Request duration in seconds',
    ['method', 'endpoint']
)

AI_INTERACTIONS_TOTAL = Counter(
    'sungblab_ai_interactions_total',
    'Total AI model interactions',
    ['model', 'user_type']
)

AI_TOKEN_USAGE = Counter(
    'sungblab_ai_tokens_total',
    'Total AI tokens used',
    ['model', 'token_type']  # input/output
)

AI_RESPONSE_TIME = Histogram(
    'sungblab_ai_response_time_seconds',
    'AI response time in seconds',
    ['model']
)

ACTIVE_USERS = Gauge(
    'sungblab_active_users',
    'Number of active users'
)

DATABASE_CONNECTIONS = Gauge(
    'sungblab_db_connections',
    'Number of database connections'
)

CACHE_HITS = Counter(
    'sungblab_cache_hits_total',
    'Total cache hits',
    ['cache_type']
)

CACHE_MISSES = Counter(
    'sungblab_cache_misses_total',
    'Total cache misses',
    ['cache_type']
)

ERROR_RATE = Counter(
    'sungblab_errors_total',
    'Total errors',
    ['error_type', 'severity']
)

class MetricsCollector:
    """메트릭 수집기"""
    
    @staticmethod
    def record_request(method: str, endpoint: str, status_code: int, duration: float):
        """HTTP 요청 메트릭 기록"""
        if not settings.ENABLE_PERFORMANCE_MONITORING:
            return
        REQUESTS_TOTAL.labels(
            method=method,
            endpoint=endpoint,
            status_code=str(status_code)
        ).inc()
        
        REQUEST_DURATION.labels(
            method=method,
            endpoint=endpoint
        ).observe(duration)
    
    @staticmethod
    def record_ai_interaction(model: str, user_type: str, 
                            input_tokens: int, output_tokens: int, 
                            response_time: float):
        """AI 상호작용 메트릭 기록"""
        if not settings.ENABLE_PERFORMANCE_MONITORING:
            return
        AI_INTERACTIONS_TOTAL.labels(
            model=model,
            user_type=user_type
        ).inc()
        
        AI_TOKEN_USAGE.labels(
            model=model,
            token_type="input"
        ).inc(input_tokens)
        
        AI_TOKEN_USAGE.labels(
            model=model,
            token_type="output"
        ).inc(output_tokens)
        
        AI_RESPONSE_TIME.labels(model=model).observe(response_time)
    
    @staticmethod
    def record_cache_hit(cache_type: str):
        """캐시 히트 기록"""
        if not settings.ENABLE_PERFORMANCE_MONITORING:
            return
        CACHE_HITS.labels(cache_type=cache_type).inc()
    
    @staticmethod
    def record_cache_miss(cache_type: str):
        """캐시 미스 기록"""
        if not settings.ENABLE_PERFORMANCE_MONITORING:
            return
        CACHE_MISSES.labels(cache_type=cache_type).inc()
    
    @staticmethod
    def record_error(error_type: str, severity: str = "error"):
        """에러 기록"""
        if not settings.ENABLE_PERFORMANCE_MONITORING:
            return
        ERROR_RATE.labels(
            error_type=error_type,
            severity=severity
        ).inc()
    
    @staticmethod
    def update_active_users(count: int):
        """활성 사용자 수 업데이트"""
        if not settings.ENABLE_PERFORMANCE_MONITORING:
            return
        ACTIVE_USERS.set(count)
    
    @staticmethod
    def update_db_connections(count: int):
        """DB 연결 수 업데이트"""
        if not settings.ENABLE_PERFORMANCE_MONITORING:
            return
        DATABASE_CONNECTIONS.set(count)

# 데코레이터들
def monitor_ai_performance(model: str):
    """AI 성능 모니터링 데코레이터"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not settings.ENABLE_PERFORMANCE_MONITORING:
                return await func(*args, **kwargs)
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                response_time = time.time() - start_time
                
                # 결과에서 토큰 정보 추출 (결과 구조에 따라 조정)
                input_tokens = getattr(result, 'input_tokens', 0)
                output_tokens = getattr(result, 'output_tokens', 0)
                user_type = kwargs.get('user_type', 'authenticated')
                
                MetricsCollector.record_ai_interaction(
                    model, user_type, input_tokens, output_tokens, response_time
                )
                
                return result
            except Exception as e:
                MetricsCollector.record_error(type(e).__name__)
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not settings.ENABLE_PERFORMANCE_MONITORING:
                return func(*args, **kwargs)
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                response_time = time.time() - start_time
                
                input_tokens = getattr(result, 'input_tokens', 0)
                output_tokens = getattr(result, 'output_tokens', 0)
                user_type = kwargs.get('user_type', 'authenticated')
                
                MetricsCollector.record_ai_interaction(
                    model, user_type, input_tokens, output_tokens, response_time
                )
                
                return result
            except Exception as e:
                MetricsCollector.record_error(type(e).__name__)
                raise
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

def monitor_cache_performance(cache_type: str):
    """캐시 성능 모니터링 데코레이터"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not settings.ENABLE_PERFORMANCE_MONITORING:
                return func(*args, **kwargs)
            result = func(*args, **kwargs)
            
            # 캐시 히트/미스 판단 (함수 구현에 따라 조정)
            if result is not None:
                MetricsCollector.record_cache_hit(cache_type)
            else:
                MetricsCollector.record_cache_miss(cache_type)
            
            return result
        
        return wrapper
    return decorator

# Health Check 메트릭
class HealthChecker:
    """시스템 헬스 체크"""
    
    @staticmethod
    def check_database_health() -> bool:
        """데이터베이스 헬스 체크"""
        try:
            from app.db.session import SessionLocal
            db = SessionLocal()
            db.execute("SELECT 1")
            db.close()
            return True
        except Exception:
            return False
    
    @staticmethod
    def check_redis_health() -> bool:
        """Redis 헬스 체크"""
        try:
            from app.core.cache import cache_manager
            return cache_manager.redis_client.ping()
        except Exception:
            return False
    
    @staticmethod
    def check_ai_service_health() -> bool:
        """AI 서비스 헬스 체크"""
        try:
            from app.api.api_v1.endpoints.chat import get_gemini_client
            client = get_gemini_client()
            return client is not None
        except Exception:
            return False
    
    @staticmethod
    def get_system_health() -> Dict[str, Any]:
        """전체 시스템 헬스 상태"""
        return {
            "database": HealthChecker.check_database_health(),
            "redis": HealthChecker.check_redis_health(),
            "ai_service": HealthChecker.check_ai_service_health(),
            "timestamp": time.time()
        }

# 메트릭 엔드포인트용 함수
def get_prometheus_metrics():
    """Prometheus 포맷 메트릭 반환"""
    return generate_latest() 