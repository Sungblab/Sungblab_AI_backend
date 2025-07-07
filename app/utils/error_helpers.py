"""
기존 HTTPException을 새로운 APIError 시스템으로 교체하기 위한 헬퍼 함수들
"""

from typing import Optional, Dict, Any, List
from app.core.exceptions import (
    APIError, ErrorCode, ErrorSeverity,
    ValidationError, AuthenticationError, AuthorizationError,
    NotFoundError, RateLimitError, AIServiceError, UsageLimitError, FileError
)

def raise_validation_error(message: str, field_errors: Optional[List[Dict[str, str]]] = None):
    """입력 검증 에러 발생"""
    raise ValidationError(message=message, field_errors=field_errors)

def raise_authentication_error(message: str = "Authentication required"):
    """인증 에러 발생"""
    raise AuthenticationError(message=message)

def raise_authorization_error(message: str = "Access denied"):
    """인가 에러 발생"""
    raise AuthorizationError(message=message)

def raise_not_found_error(resource: str, identifier: Optional[str] = None):
    """리소스 찾기 실패 에러 발생"""
    raise NotFoundError(resource=resource, identifier=identifier)

def raise_model_error(model: str, message: Optional[str] = None):
    """AI 모델 관련 에러 발생"""
    if not message:
        message = f"Invalid or unavailable model: {model}"
    raise APIError(
        error_code=ErrorCode.INVALID_MODEL,
        message=message,
        status_code=400,
        details={"model": model},
        severity=ErrorSeverity.LOW
    )

def raise_usage_limit_error(current_usage: Optional[int] = None, limit: Optional[int] = None):
    """사용량 제한 에러 발생"""
    message = "Usage limit exceeded"
    if current_usage is not None and limit is not None:
        message = f"Usage limit exceeded: {current_usage}/{limit}"
    raise UsageLimitError(
        message=message,
        current_usage=current_usage,
        limit=limit
    )

def raise_ai_service_error(message: str, model: Optional[str] = None, operation: Optional[str] = None):
    """AI 서비스 에러 발생"""
    raise AIServiceError(message=message, model=model, operation=operation)

def raise_file_error(message: str, filename: Optional[str] = None, error_type: str = "upload"):
    """파일 관련 에러 발생"""
    error_code_mapping = {
        "upload": ErrorCode.FILE_UPLOAD_FAILED,
        "size": ErrorCode.FILE_TOO_LARGE,
        "type": ErrorCode.INVALID_FILE_TYPE
    }
    error_code = error_code_mapping.get(error_type, ErrorCode.FILE_UPLOAD_FAILED)
    raise FileError(message=message, filename=filename, error_code=error_code)

def raise_rate_limit_error(message: str = "Rate limit exceeded", retry_after: Optional[int] = None):
    """레이트 리미팅 에러 발생"""
    raise RateLimitError(message=message, retry_after=retry_after)

def raise_database_error(message: str, operation: Optional[str] = None):
    """데이터베이스 에러 발생"""
    details = {}
    if operation:
        details["operation"] = operation
    raise APIError(
        error_code=ErrorCode.DATABASE_ERROR,
        message=message,
        status_code=500,
        details=details,
        severity=ErrorSeverity.HIGH
    )

def raise_project_error(project_id: str, error_type: str = "not_found"):
    """프로젝트 관련 에러 발생"""
    if error_type == "not_found":
        raise NotFoundError(resource="Project", identifier=project_id)
    elif error_type == "access_denied":
        raise APIError(
            error_code=ErrorCode.PROJECT_ACCESS_DENIED,
            message=f"Access denied to project: {project_id}",
            status_code=403,
            details={"project_id": project_id},
            severity=ErrorSeverity.MEDIUM
        )

def raise_session_error(session_id: Optional[str] = None, error_type: str = "invalid"):
    """세션 관련 에러 발생"""
    error_codes = {
        "invalid": ErrorCode.INVALID_SESSION,
        "expired": ErrorCode.SESSION_EXPIRED
    }
    
    error_code = error_codes.get(error_type, ErrorCode.INVALID_SESSION)
    message = "Invalid session" if error_type == "invalid" else "Session expired"
    
    details = {}
    if session_id:
        details["session_id"] = session_id
    
    raise APIError(
        error_code=error_code,
        message=message,
        status_code=401,
        details=details,
        severity=ErrorSeverity.MEDIUM
    )

# 기존 코드 마이그레이션을 위한 매핑 함수들
def convert_http_exception_usage():
    """
    기존 HTTPException 사용 패턴을 새로운 시스템으로 변환하는 예시
    
    Before:
        raise HTTPException(status_code=404, detail="Chat room not found")
    
    After:
        raise_not_found_error("Chat room")
    
    Before:
        raise HTTPException(status_code=403, detail="Usage limit exceeded")
    
    After:
        raise_usage_limit_error(current_usage=10, limit=10)
    
    Before:
        raise HTTPException(status_code=400, detail="Invalid model specified")
    
    After:
        raise_model_error("invalid-model", "Model not supported")
    """
    pass

# 컨텍스트 매니저를 통한 에러 처리
class ErrorContext:
    """에러 컨텍스트 매니저"""
    
    def __init__(self, operation: str, **context):
        self.operation = operation
        self.context = context
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type and not issubclass(exc_type, APIError):
            # 예상치 못한 에러를 APIError로 변환
            raise APIError(
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
                message=f"Error in {self.operation}: {str(exc_val)}",
                status_code=500,
                details={"operation": self.operation, **self.context},
                severity=ErrorSeverity.HIGH
            ) from exc_val
        return False

# 사용 예시
"""
# 기존 방식
try:
    result = some_operation()
    if not result:
        raise HTTPException(status_code=404, detail="Resource not found")
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))

# 새로운 방식
with ErrorContext("some_operation", user_id="123"):
    result = some_operation()
    if not result:
        raise_not_found_error("Resource")
""" 