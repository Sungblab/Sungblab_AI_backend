from typing import Dict, Any, Optional, List
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from datetime import datetime
import uuid
from enum import Enum

class ErrorCode(str, Enum):
    """표준화된 에러 코드"""
    
    # 일반 에러
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    
    # 모델 관련 에러
    INVALID_MODEL = "INVALID_MODEL"
    MODEL_NOT_AVAILABLE = "MODEL_NOT_AVAILABLE"
    
    # 사용량 관련 에러
    USAGE_LIMIT_EXCEEDED = "USAGE_LIMIT_EXCEEDED"
    SUBSCRIPTION_REQUIRED = "SUBSCRIPTION_REQUIRED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    
    # 파일 관련 에러
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    INVALID_FILE_TYPE = "INVALID_FILE_TYPE"
    FILE_UPLOAD_FAILED = "FILE_UPLOAD_FAILED"
    
    # 입력 관련 에러
    INVALID_INPUT = "INVALID_INPUT"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_FORMAT = "INVALID_FORMAT"
    
    # 레이트 리미팅 에러
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    
    # AI 서비스 관련 에러
    AI_SERVICE_UNAVAILABLE = "AI_SERVICE_UNAVAILABLE"
    AI_SERVICE_ERROR = "AI_SERVICE_ERROR"
    TOKEN_CALCULATION_FAILED = "TOKEN_CALCULATION_FAILED"
    
    # 데이터베이스 관련 에러
    DATABASE_ERROR = "DATABASE_ERROR"
    RECORD_NOT_FOUND = "RECORD_NOT_FOUND"
    DUPLICATE_RECORD = "DUPLICATE_RECORD"
    
    # 프로젝트 관련 에러
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    PROJECT_ACCESS_DENIED = "PROJECT_ACCESS_DENIED"
    
    # 세션 관련 에러
    INVALID_SESSION = "INVALID_SESSION"
    SESSION_EXPIRED = "SESSION_EXPIRED"

class ErrorSeverity(str, Enum):
    """에러 심각도"""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class APIError(HTTPException):
    """표준화된 API 에러"""
    
    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        status_code: int = 500,
        user_message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM
    ):
        super().__init__(status_code=status_code, detail=message)
        self.error_code = error_code
        self.user_message = user_message or self._get_user_friendly_message(error_code)
        self.details = details or {}
        self.severity = severity
        self.error_id = str(uuid.uuid4())
        self.timestamp = datetime.utcnow().isoformat()
    
    def _get_user_friendly_message(self, error_code: ErrorCode) -> str:
        """사용자 친화적 에러 메시지"""
        messages = {
            ErrorCode.INTERNAL_SERVER_ERROR: "일시적인 서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
            ErrorCode.VALIDATION_ERROR: "입력 정보에 오류가 있습니다. 다시 확인해주세요.",
            ErrorCode.UNAUTHORIZED: "로그인이 필요합니다.",
            ErrorCode.FORBIDDEN: "접근 권한이 없습니다.",
            ErrorCode.NOT_FOUND: "요청한 정보를 찾을 수 없습니다.",
            
            ErrorCode.INVALID_MODEL: "지원하지 않는 AI 모델입니다.",
            ErrorCode.MODEL_NOT_AVAILABLE: "현재 사용할 수 없는 모델입니다.",
            
            ErrorCode.USAGE_LIMIT_EXCEEDED: "사용 한도를 초과했습니다. 요금제를 확인해주세요.",
            ErrorCode.SUBSCRIPTION_REQUIRED: "구독이 필요한 서비스입니다.",
            ErrorCode.QUOTA_EXCEEDED: "월간 사용량을 초과했습니다.",
            
            ErrorCode.FILE_TOO_LARGE: "파일 크기가 너무 큽니다. (최대 32MB)",
            ErrorCode.INVALID_FILE_TYPE: "지원하지 않는 파일 형식입니다.",
            ErrorCode.FILE_UPLOAD_FAILED: "파일 업로드에 실패했습니다.",
            
            ErrorCode.INVALID_INPUT: "입력 형식이 올바르지 않습니다.",
            ErrorCode.MISSING_REQUIRED_FIELD: "필수 정보가 누락되었습니다.",
            ErrorCode.INVALID_FORMAT: "올바른 형식으로 입력해주세요.",
            
            ErrorCode.RATE_LIMIT_EXCEEDED: "요청이 너무 빠릅니다. 잠시 후 다시 시도해주세요.",
            
            ErrorCode.AI_SERVICE_UNAVAILABLE: "AI 서비스가 일시적으로 사용할 수 없습니다.",
            ErrorCode.AI_SERVICE_ERROR: "AI 서비스 처리 중 오류가 발생했습니다.",
            ErrorCode.TOKEN_CALCULATION_FAILED: "토큰 계산에 실패했습니다.",
            
            ErrorCode.DATABASE_ERROR: "데이터베이스 오류가 발생했습니다.",
            ErrorCode.RECORD_NOT_FOUND: "요청한 데이터를 찾을 수 없습니다.",
            ErrorCode.DUPLICATE_RECORD: "이미 존재하는 데이터입니다.",
            
            ErrorCode.PROJECT_NOT_FOUND: "프로젝트를 찾을 수 없습니다.",
            ErrorCode.PROJECT_ACCESS_DENIED: "프로젝트에 대한 접근 권한이 없습니다.",
            
            ErrorCode.INVALID_SESSION: "세션이 유효하지 않습니다.",
            ErrorCode.SESSION_EXPIRED: "세션이 만료되었습니다. 다시 로그인해주세요.",
        }
        return messages.get(error_code, "알 수 없는 오류가 발생했습니다.")

class ValidationError(APIError):
    """입력 검증 에러"""
    
    def __init__(self, message: str, field_errors: Optional[List[Dict[str, str]]] = None):
        super().__init__(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=message,
            status_code=400,
            details={"field_errors": field_errors or []},
            severity=ErrorSeverity.LOW
        )

class AuthenticationError(APIError):
    """인증 에러"""
    
    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            error_code=ErrorCode.UNAUTHORIZED,
            message=message,
            status_code=401,
            severity=ErrorSeverity.MEDIUM
        )

class AuthorizationError(APIError):
    """인가 에러"""
    
    def __init__(self, message: str = "Access denied"):
        super().__init__(
            error_code=ErrorCode.FORBIDDEN,
            message=message,
            status_code=403,
            severity=ErrorSeverity.MEDIUM
        )

class NotFoundError(APIError):
    """리소스 찾기 실패 에러"""
    
    def __init__(self, resource: str, identifier: Optional[str] = None):
        message = f"{resource} not found"
        if identifier:
            message += f": {identifier}"
        super().__init__(
            error_code=ErrorCode.NOT_FOUND,
            message=message,
            status_code=404,
            severity=ErrorSeverity.LOW
        )

class RateLimitError(APIError):
    """레이트 리미팅 에러"""
    
    def __init__(self, message: str = "Rate limit exceeded", retry_after: Optional[int] = None):
        details = {}
        if retry_after:
            details["retry_after"] = retry_after
        super().__init__(
            error_code=ErrorCode.RATE_LIMIT_EXCEEDED,
            message=message,
            status_code=429,
            details=details,
            severity=ErrorSeverity.LOW
        )

class AIServiceError(APIError):
    """AI 서비스 에러"""
    
    def __init__(self, message: str, model: Optional[str] = None, operation: Optional[str] = None):
        details = {}
        if model:
            details["model"] = model
        if operation:
            details["operation"] = operation
        super().__init__(
            error_code=ErrorCode.AI_SERVICE_ERROR,
            message=message,
            status_code=500,
            details=details,
            severity=ErrorSeverity.HIGH
        )

class UsageLimitError(APIError):
    """사용량 제한 에러"""
    
    def __init__(self, message: str, current_usage: Optional[int] = None, limit: Optional[int] = None):
        details = {}
        if current_usage is not None:
            details["current_usage"] = current_usage
        if limit is not None:
            details["limit"] = limit
        super().__init__(
            error_code=ErrorCode.USAGE_LIMIT_EXCEEDED,
            message=message,
            status_code=403,
            details=details,
            severity=ErrorSeverity.MEDIUM
        )

class FileError(APIError):
    """파일 관련 에러"""
    
    def __init__(self, message: str, filename: Optional[str] = None, error_code: ErrorCode = ErrorCode.FILE_UPLOAD_FAILED):
        details = {}
        if filename:
            details["filename"] = filename
        super().__init__(
            error_code=error_code,
            message=message,
            status_code=400,
            details=details,
            severity=ErrorSeverity.LOW
        )

def create_error_response(error: APIError) -> JSONResponse:
    """표준화된 에러 응답 생성"""
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.error_code,
                "message": error.user_message,
                "details": error.details,
                "error_id": error.error_id,
                "timestamp": error.timestamp,
                "severity": error.severity
            }
        }
    ) 