import logging
import json
import time
import traceback
from datetime import datetime
from typing import Dict, Any, Optional
from functools import wraps
from app.core.config import settings
import uuid

class StructuredLogger:
    """구조화된 로그 시스템"""
    
    def __init__(self, name: str = "sungblab_api"):
        self.logger = logging.getLogger(name)
        self.setup_logger()
        
    def setup_logger(self):
        """로거 설정"""
        handler = logging.StreamHandler()
        formatter = JsonFormatter()
        handler.setFormatter(formatter)
        
        self.logger.handlers.clear()
        self.logger.addHandler(handler)
        self.logger.setLevel(getattr(logging, settings.LOG_LEVEL))
    
    def log_api_request(self, 
                       method: str, 
                       path: str, 
                       user_id: Optional[str] = None,
                       ip_address: Optional[str] = None,
                       request_id: Optional[str] = None,
                       **kwargs):
        """API 요청 로그"""
        self.info("api_request", {
            "method": method,
            "path": path,
            "user_id": user_id,
            "ip_address": ip_address,
            "request_id": request_id,
            **kwargs
        })
    
    def log_api_response(self,
                        method: str,
                        path: str,
                        status_code: int,
                        response_time: float,
                        user_id: Optional[str] = None,
                        request_id: Optional[str] = None,
                        **kwargs):
        """API 응답 로그"""
        self.info("api_response", {
            "method": method,
            "path": path,
            "status_code": status_code,
            "response_time": response_time,
            "user_id": user_id,
            "request_id": request_id,
            **kwargs
        })
    
    def log_ai_interaction(self,
                          model: str,
                          input_tokens: int,
                          output_tokens: int,
                          user_id: str,
                          session_id: Optional[str] = None,
                          project_id: Optional[str] = None,
                          **kwargs):
        """AI 모델 상호작용 로그"""
        self.info("ai_interaction", {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "user_id": user_id,
            "session_id": session_id,
            "project_id": project_id,
            **kwargs
        })
    
    def log_error(self,
                  error: Exception,
                  context: Dict[str, Any] = None,
                  user_id: Optional[str] = None,
                  request_id: Optional[str] = None):
        """에러 로그"""
        error_data = {
            "error_type": type(error).__name__,
            "error_message": str(error),
            "traceback": traceback.format_exc(),
            "user_id": user_id,
            "request_id": request_id,
            "context": context or {}
        }
        self.error("error_occurred", error_data)
    
    def log_performance_metric(self,
                              operation: str,
                              duration: float,
                              success: bool = True,
                              **kwargs):
        """성능 메트릭 로그"""
        self.info("performance_metric", {
            "operation": operation,
            "duration": duration,
            "success": success,
            **kwargs
        })
    
    def info(self, event: str, data: Optional[Dict[str, Any]] = None):
        """정보 로그"""
        self.print(json.dumps({
            "timestamp": datetime.utcnow().isoformat(),
            "level": "INFO",
            "event": event,
            "data": data or {}
        }))
    
    def warning(self, event: str, data: Optional[Dict[str, Any]] = None):
        """경고 로그"""
        self.logger.warning(json.dumps({
            "timestamp": datetime.utcnow().isoformat(),
            "level": "WARNING",
            "event": event,
            "data": data or {}
        }))
    
    def error(self, event: str, data: Optional[Dict[str, Any]] = None):
        """에러 로그"""
        self.logger.error(json.dumps({
            "timestamp": datetime.utcnow().isoformat(),
            "level": "ERROR",
            "event": event,
            "data": data or {}
        }))

class JsonFormatter(logging.Formatter):
    """JSON 포맷터"""
    
    def format(self, record):
        # 이미 JSON 형태인 경우 그대로 반환
        try:
            json.loads(record.getMessage())
            return record.getMessage()
        except (json.JSONDecodeError, ValueError):
            # 일반 메시지인 경우 JSON으로 변환
            return json.dumps({
                "timestamp": datetime.utcnow().isoformat(),
                "level": record.levelname,
                "event": "general_log",
                "data": {
                    "message": record.getMessage(),
                    "module": record.module,
                    "function": record.funcName,
                    "line": record.lineno
                }
            })

# 성능 모니터링 데코레이터
def monitor_performance(operation_name: str = None):
    """성능 모니터링 데코레이터"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            operation = operation_name or f"{func.__module__}.{func.__name__}"
            
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                
                structured_logger.log_performance_metric(
                    operation=operation,
                    duration=duration,
                    success=True
                )
                
                return result
                
            except Exception as e:
                duration = time.time() - start_time
                
                structured_logger.log_performance_metric(
                    operation=operation,
                    duration=duration,
                    success=False
                )
                
                structured_logger.log_error(e, {
                    "operation": operation,
                    "duration": duration
                })
                
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            operation = operation_name or f"{func.__module__}.{func.__name__}"
            
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                
                structured_logger.log_performance_metric(
                    operation=operation,
                    duration=duration,
                    success=True
                )
                
                return result
                
            except Exception as e:
                duration = time.time() - start_time
                
                structured_logger.log_performance_metric(
                    operation=operation,
                    duration=duration,
                    success=False
                )
                
                structured_logger.log_error(e, {
                    "operation": operation,
                    "duration": duration
                })
                
                raise
        
        # 비동기 함수인지 확인
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

# 전역 로거 인스턴스
structured_logger = StructuredLogger()

# 사용 예시:
# @monitor_performance("chat_message_generation")
# async def generate_chat_response(...):
#     pass

# structured_logger.log_ai_interaction(
#     model="gemini-2.5-flash",
#     input_tokens=150,
#     output_tokens=300,
#     user_id="user123"
# ) 