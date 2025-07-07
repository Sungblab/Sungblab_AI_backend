from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import time
from typing import Dict, List
import logging
from app.core.config import settings
import hashlib
from datetime import datetime, timedelta

logger = logging.getLogger("sungblab_api")

class SecurityMiddleware(BaseHTTPMiddleware):
    """보안 강화 미들웨어"""
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.rate_limiter = RateLimiter()
    
    async def dispatch(self, request: Request, call_next):
        # 보안 헤더 추가
        response = await call_next(request)
        
        # 보안 헤더 설정
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # 프로덕션 환경에서는 Server 헤더 숨김
        if settings.ENVIRONMENT == "production":
            response.headers["Server"] = "SungbLab"
        
        return response

class RateLimiter:
    """API 레이트 리미팅"""
    
    def __init__(self):
        self.requests: Dict[str, List[float]] = {}
        self.limits = {
            "anonymous": {"requests": 10, "window": 60},  # 익명: 1분에 10회
            "authenticated": {"requests": 100, "window": 60},  # 인증: 1분에 100회
            "premium": {"requests": 300, "window": 60}  # 프리미엄: 1분에 300회
        }
    
    def get_client_id(self, request: Request) -> str:
        """클라이언트 식별자 생성"""
        # Authorization 헤더 확인
        auth_header = request.headers.get("authorization")
        if auth_header:
            # 토큰 기반 식별
            token_hash = hashlib.md5(auth_header.encode()).hexdigest()
            return f"auth_{token_hash}"
        else:
            # IP 기반 식별
            forwarded_for = request.headers.get("x-forwarded-for")
            if forwarded_for:
                ip = forwarded_for.split(",")[0].strip()
            else:
                ip = request.client.host if request.client else "unknown"
            return f"ip_{ip}"
    
    def is_allowed(self, request: Request, user_type: str = "anonymous") -> bool:
        """요청 허용 여부 확인"""
        client_id = self.get_client_id(request)
        now = time.time()
        
        # 해당 클라이언트의 요청 기록 가져오기
        if client_id not in self.requests:
            self.requests[client_id] = []
        
        client_requests = self.requests[client_id]
        
        # 윈도우 내의 요청만 필터링
        limit_config = self.limits.get(user_type, self.limits["anonymous"])
        window_start = now - limit_config["window"]
        client_requests[:] = [req_time for req_time in client_requests if req_time > window_start]
        
        # 요청 수 제한 확인
        if len(client_requests) >= limit_config["requests"]:
            return False
        
        # 새 요청 기록
        client_requests.append(now)
        return True

class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """에러 처리 미들웨어 - 프로덕션에서 민감한 정보 숨김"""
    
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            logger.error(f"Unhandled error: {exc}", exc_info=True)
            
            # 프로덕션에서는 일반적인 에러 메시지만 반환
            if settings.ENVIRONMENT == "production":
                return JSONResponse(
                    status_code=500,
                    content={
                        "detail": "서버 내부 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
                        "error_id": hashlib.md5(str(exc).encode()).hexdigest()[:8]
                    }
                )
            else:
                # 개발 환경에서는 상세한 에러 정보 제공
                return JSONResponse(
                    status_code=500,
                    content={
                        "detail": f"개발 모드 오류: {str(exc)}",
                        "type": type(exc).__name__
                    }
                )

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """요청 로깅 미들웨어"""
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # 요청 정보 로깅
        client_ip = self.get_client_ip(request)
        print(f"Request: {request.method} {request.url.path} from {client_ip}")
        
        response = await call_next(request)
        
        # 응답 정보 로깅
        process_time = time.time() - start_time
        print(
            f"Response: {response.status_code} in {process_time:.3f}s "
            f"for {request.method} {request.url.path}"
        )
        
        # 응답 시간 헤더 추가
        response.headers["X-Process-Time"] = str(process_time)
        
        return response
    
    def get_client_ip(self, request: Request) -> str:
        """클라이언트 IP 주소 추출"""
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

# 보안 유틸리티 함수들
def sanitize_error_message(error: Exception, is_production: bool = True) -> str:
    """에러 메시지 마스킹"""
    if is_production:
        # 프로덕션에서는 일반적인 메시지만 반환
        error_types = {
            "ValidationError": "입력 데이터가 올바르지 않습니다.",
            "DatabaseError": "데이터베이스 오류가 발생했습니다.",
            "ConnectionError": "외부 서비스 연결에 실패했습니다.",
            "TimeoutError": "요청 시간이 초과되었습니다.",
        }
        
        error_type = type(error).__name__
        return error_types.get(error_type, "서버 오류가 발생했습니다.")
    else:
        # 개발 환경에서는 상세한 정보 제공
        return str(error)

def mask_sensitive_data(data: dict) -> dict:
    """민감한 데이터 마스킹"""
    sensitive_keys = [
        "password", "token", "secret", "key", "api_key",
        "hashed_password", "verification_code"
    ]
    
    masked_data = data.copy()
    
    for key in sensitive_keys:
        if key in masked_data:
            masked_data[key] = "***MASKED***"
    
    return masked_data 