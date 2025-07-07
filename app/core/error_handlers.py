from fastapi import Request, FastAPI
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError, HTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import SQLAlchemyError
from typing import Union
import traceback
from datetime import datetime

from app.core.exceptions import (
    APIError, ErrorCode, ErrorSeverity, 
    ValidationError, AuthenticationError, 
    create_error_response
)
from app.core.error_tracking import error_tracker
from app.core.structured_logging import StructuredLogger
from app.core.config import settings

# 구조화된 로거 초기화
logger = StructuredLogger("error_handler")

def setup_error_handlers(app: FastAPI) -> None:
    """글로벌 에러 핸들러 설정"""
    
    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        """표준화된 API 에러 핸들러"""
        
        # 에러 추적 및 로깅
        await _log_and_track_error(request, exc, exc.severity)
        
        # 표준화된 에러 응답 반환
        return create_error_response(exc)
    
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """기본 HTTP 에러를 APIError로 변환"""
        
        # 기존 HTTPException을 APIError로 변환
        api_error = _convert_http_exception_to_api_error(exc)
        
        # 에러 추적 및 로깅
        await _log_and_track_error(request, api_error, api_error.severity)
        
        return create_error_response(api_error)
    
    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Starlette HTTP 에러 핸들러"""
        
        # HTTPException으로 변환 후 처리
        http_exc = HTTPException(status_code=exc.status_code, detail=str(exc.detail))
        return await http_exception_handler(request, http_exc)
    
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Pydantic 검증 에러 핸들러"""
        
        # 필드별 에러 정보 추출
        field_errors = []
        for error in exc.errors():
            field_errors.append({
                "field": " -> ".join(str(x) for x in error["loc"]),
                "message": error["msg"],
                "type": error["type"]
            })
        
        # ValidationError로 변환
        api_error = ValidationError(
            message="Request validation failed",
            field_errors=field_errors
        )
        
        # 에러 추적 및 로깅
        await _log_and_track_error(request, api_error, ErrorSeverity.LOW)
        
        return create_error_response(api_error)
    
    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        """데이터베이스 에러 핸들러"""
        
        # 데이터베이스 에러를 APIError로 변환
        api_error = APIError(
            error_code=ErrorCode.DATABASE_ERROR,
            message=f"Database error: {str(exc)}",
            status_code=500,
            severity=ErrorSeverity.HIGH
        )
        
        # 에러 추적 및 로깅
        await _log_and_track_error(request, api_error, ErrorSeverity.HIGH)
        
        return create_error_response(api_error)
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """일반 예외 핸들러 (마지막 안전장치)"""
        
        # 예상치 못한 에러를 APIError로 변환
        api_error = APIError(
            error_code=ErrorCode.INTERNAL_SERVER_ERROR,
            message=f"Unexpected error: {str(exc)}" if settings.DEBUG else "Internal server error",
            status_code=500,
            severity=ErrorSeverity.CRITICAL
        )
        
        # 에러 추적 및 로깅
        await _log_and_track_error(request, api_error, ErrorSeverity.CRITICAL, original_exception=exc)
        
        return create_error_response(api_error)

async def _log_and_track_error(
    request: Request, 
    error: APIError, 
    severity: ErrorSeverity,
    original_exception: Union[Exception, None] = None
) -> None:
    """에러 로깅 및 추적"""
    
    # 요청 정보 추출
    request_info = await _extract_request_info(request)
    
    # 구조화된 로깅
    logger.log_error(
        error=original_exception or error,
        context={
            "error_id": error.error_id,
            "error_code": error.error_code,
            "status_code": error.status_code,
            "severity": severity,
            "request_info": request_info,
            "traceback": traceback.format_exc() if original_exception else None
        },
        user_id=request_info.get("user_id"),
        request_id=request_info.get("request_id")
    )
    
    # Sentry 에러 추적 (심각도에 따라)
    if severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]:
        error_tracker.capture_exception(
            error=original_exception or error,
            context={
                "error_id": error.error_id,
                "error_code": error.error_code,
                "request_info": request_info
            },
            user_id=request_info.get("user_id"),
            extra={
                "severity": severity,
                "status_code": error.status_code
            }
        )
    elif severity == ErrorSeverity.MEDIUM:
        error_tracker.capture_message(
            message=f"API Error: {error.error_code} - {error.detail}",
            level="warning",
            context={
                "error_id": error.error_id,
                "request_info": request_info
            },
            user_id=request_info.get("user_id")
        )

async def _extract_request_info(request: Request) -> dict:
    """요청 정보 추출"""
    
    # 헤더에서 사용자 정보 추출 (인증 미들웨어에서 설정)
    user_id = request.headers.get("X-User-ID")
    request_id = request.headers.get("X-Request-ID")
    
    # 클라이언트 IP 추출
    client_ip = request.client.host if request.client else "unknown"
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    
    return {
        "method": request.method,
        "url": str(request.url),
        "path": request.url.path,
        "query_params": dict(request.query_params),
        "headers": dict(request.headers),
        "client_ip": client_ip,
        "user_agent": request.headers.get("User-Agent", "unknown"),
        "user_id": user_id,
        "request_id": request_id,
        "timestamp": datetime.utcnow().isoformat()
    }

def _convert_http_exception_to_api_error(exc: HTTPException) -> APIError:
    """HTTPException을 APIError로 변환"""
    
    # 상태 코드에 따른 에러 코드 매핑
    status_code_mapping = {
        400: ErrorCode.VALIDATION_ERROR,
        401: ErrorCode.UNAUTHORIZED,
        403: ErrorCode.FORBIDDEN,
        404: ErrorCode.NOT_FOUND,
        429: ErrorCode.RATE_LIMIT_EXCEEDED,
        500: ErrorCode.INTERNAL_SERVER_ERROR,
    }
    
    error_code = status_code_mapping.get(exc.status_code, ErrorCode.INTERNAL_SERVER_ERROR)
    
    # 심각도 결정
    if exc.status_code >= 500:
        severity = ErrorSeverity.HIGH
    elif exc.status_code >= 400:
        severity = ErrorSeverity.MEDIUM
    else:
        severity = ErrorSeverity.LOW
    
    return APIError(
        error_code=error_code,
        message=str(exc.detail),
        status_code=exc.status_code,
        severity=severity
    )

# 에러 응답 모니터링을 위한 미들웨어
class ErrorMonitoringMiddleware:
    """에러 모니터링 미들웨어"""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        # 응답 모니터링을 위한 래퍼
        response_started = False
        status_code = 200
        
        async def send_wrapper(message):
            nonlocal response_started, status_code
            
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                
                # 에러 응답 모니터링
                if status_code >= 400:
                    error_tracker.add_breadcrumb(
                        message=f"Error response: {status_code}",
                        category="http_error",
                        level="warning",
                        data={
                            "status_code": status_code,
                            "path": scope["path"],
                            "method": scope["method"]
                        }
                    )
            
            await send(message)
        
        await self.app(scope, receive, send_wrapper) 