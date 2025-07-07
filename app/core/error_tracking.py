import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from app.core.config import settings
from typing import Dict, Any, Optional
import traceback

def init_sentry():
    """Sentry 초기화"""
    if hasattr(settings, 'SENTRY_DSN') and settings.SENTRY_DSN:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            integrations=[
                FastApiIntegration(auto_enabling_integrations=False),
                SqlalchemyIntegration(),
                LoggingIntegration(level=None, event_level=None),
            ],
            traces_sample_rate=0.1,  # 10% 트레이싱
            profiles_sample_rate=0.1,  # 10% 프로파일링
            environment=settings.ENVIRONMENT,
            release=getattr(settings, 'VERSION', '1.0.0'),
        )

class ErrorTracker:
    """에러 추적 도우미"""
    
    @staticmethod
    def capture_exception(
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None
    ):
        """예외 캡처"""
        with sentry_sdk.push_scope() as scope:
            # 사용자 정보 설정
            if user_id:
                scope.user = {"id": user_id}
            
            # 컨텍스트 정보 추가
            if context:
                for key, value in context.items():
                    scope.set_context(key, value)
            
            # 추가 정보
            if extra:
                for key, value in extra.items():
                    scope.set_extra(key, value)
            
            # 태그 설정
            scope.set_tag("error_type", type(error).__name__)
            
            sentry_sdk.capture_exception(error)
    
    @staticmethod
    def capture_message(
        message: str,
        level: str = "info",
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None
    ):
        """메시지 캡처"""
        with sentry_sdk.push_scope() as scope:
            if user_id:
                scope.user = {"id": user_id}
            
            if context:
                for key, value in context.items():
                    scope.set_context(key, value)
            
            sentry_sdk.capture_message(message, level=level)
    
    @staticmethod
    def add_breadcrumb(
        message: str,
        category: str = "default",
        level: str = "info",
        data: Optional[Dict[str, Any]] = None
    ):
        """브레드크럼 추가"""
        sentry_sdk.add_breadcrumb(
            message=message,
            category=category,
            level=level,
            data=data or {}
        )

# 전역 에러 추적기
error_tracker = ErrorTracker()

# 데코레이터
def track_errors(operation_name: str = None):
    """에러 추적 데코레이터"""
    def decorator(func):
        from functools import wraps
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            operation = operation_name or f"{func.__module__}.{func.__name__}"
            
            try:
                # 브레드크럼 추가
                error_tracker.add_breadcrumb(
                    f"Starting {operation}",
                    category="function_call",
                    data={"operation": operation}
                )
                
                result = await func(*args, **kwargs)
                
                error_tracker.add_breadcrumb(
                    f"Completed {operation}",
                    category="function_call",
                    data={"operation": operation, "success": True}
                )
                
                return result
                
            except Exception as e:
                error_tracker.capture_exception(
                    e,
                    context={
                        "operation": operation,
                        "args": str(args),
                        "kwargs": str(kwargs)
                    }
                )
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            operation = operation_name or f"{func.__module__}.{func.__name__}"
            
            try:
                error_tracker.add_breadcrumb(
                    f"Starting {operation}",
                    category="function_call",
                    data={"operation": operation}
                )
                
                result = func(*args, **kwargs)
                
                error_tracker.add_breadcrumb(
                    f"Completed {operation}",
                    category="function_call",
                    data={"operation": operation, "success": True}
                )
                
                return result
                
            except Exception as e:
                error_tracker.capture_exception(
                    e,
                    context={
                        "operation": operation,
                        "args": str(args),
                        "kwargs": str(kwargs)
                    }
                )
                raise
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator 