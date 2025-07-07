"""
강화된 입력 검증 스키마
Pydantic 모델을 통한 종합적인 입력 검증 시스템
"""

import re
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, validator, Field, EmailStr
from datetime import datetime
from enum import Enum
import bleach

from app.core.security_enhanced import InputValidator, SecurityLevel

class ModelType(str, Enum):
    """지원되는 AI 모델 타입"""
    GEMINI_15_FLASH = "gemini-1.5-flash"
    GEMINI_15_PRO = "gemini-1.5-pro"
    GEMINI_20_FLASH = "gemini-2.0-flash"

class FileTypeEnum(str, Enum):
    """허용되는 파일 타입"""
    PDF = "application/pdf"
    TXT = "text/plain"
    CSV = "text/csv"
    MARKDOWN = "text/markdown"
    DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    DOC = "application/msword"
    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    XLS = "application/vnd.ms-excel"
    JPEG = "image/jpeg"
    PNG = "image/png"
    GIF = "image/gif"
    WEBP = "image/webp"

class SecureBaseModel(BaseModel):
    """보안 강화된 기본 모델"""
    
    class Config:
        # 추가 필드 허용하지 않음
        extra = "forbid"
        # 문자열 공백 제거
        str_strip_whitespace = True
        # 값 검증
        validate_assignment = True
        # 임의 타입 허용하지 않음
        arbitrary_types_allowed = False

class SecureTextInput(SecureBaseModel):
    """보안 강화된 텍스트 입력"""
    text: str = Field(..., min_length=1, max_length=50000)
    allow_html: bool = Field(default=False)
    
    @validator('text')
    def validate_secure_text(cls, v, values):
        """텍스트 보안 검증"""
        allow_html = values.get('allow_html', False)
        
        try:
            cleaned_text, violations = InputValidator.validate_text_input(
                text=v,
                max_length=50000,
                allow_html=allow_html,
                check_sql_injection=True,
                check_xss=True
            )
            
            # 위험한 위반사항이 있으면 예외 발생
            critical_violations = [
                violation for violation in violations 
                if violation.get("severity") in [SecurityLevel.HIGH, SecurityLevel.CRITICAL]
            ]
            
            if critical_violations:
                violation_messages = [v["message"] for v in critical_violations]
                raise ValueError(f"Security validation failed: {'; '.join(violation_messages)}")
            
            return cleaned_text
            
        except Exception as e:
            raise ValueError(f"Text validation failed: {str(e)}")

class ChatMessageCreate(SecureBaseModel):
    """채팅 메시지 생성 검증"""
    content: str = Field(..., min_length=1, max_length=10000, description="메시지 내용")
    model: ModelType = Field(..., description="사용할 AI 모델")
    system_prompt: Optional[str] = Field(None, max_length=5000, description="시스템 프롬프트")
    temperature: Optional[float] = Field(0.7, ge=0.0, le=2.0, description="응답 창의성 (0-2)")
    max_tokens: Optional[int] = Field(1024, ge=1, le=8192, description="최대 토큰 수")
    session_id: Optional[str] = Field(None, regex=r'^[a-zA-Z0-9\-_]+$', description="세션 ID")
    
    @validator('content')
    def validate_message_content(cls, v):
        """메시지 내용 검증"""
        # 빈 공백만 있는 메시지 차단
        if not v.strip():
            raise ValueError("메시지 내용이 비어있습니다.")
        
        # 보안 검증
        cleaned_text, violations = InputValidator.validate_text_input(
            text=v,
            max_length=10000,
            allow_html=False,
            check_sql_injection=True,
            check_xss=True
        )
        
        # 위험한 패턴 확인
        critical_violations = [
            violation for violation in violations 
            if violation.get("severity") in [SecurityLevel.HIGH, SecurityLevel.CRITICAL]
        ]
        
        if critical_violations:
            raise ValueError("메시지에 위험한 패턴이 감지되었습니다.")
        
        return cleaned_text
    
    @validator('system_prompt')
    def validate_system_prompt(cls, v):
        """시스템 프롬프트 검증"""
        if v is None:
            return v
        
        # 시스템 프롬프트는 더 엄격하게 검증
        cleaned_text, violations = InputValidator.validate_text_input(
            text=v,
            max_length=5000,
            allow_html=False,
            check_sql_injection=True,
            check_xss=True
        )
        
        return cleaned_text

class ProjectCreate(SecureBaseModel):
    """프로젝트 생성 검증"""
    name: str = Field(..., min_length=1, max_length=100, description="프로젝트 이름")
    description: Optional[str] = Field(None, max_length=1000, description="프로젝트 설명")
    
    @validator('name')
    def validate_project_name(cls, v):
        """프로젝트 이름 검증"""
        # 특수문자 제한 (일부만 허용)
        if not re.match(r'^[a-zA-Z0-9가-힣\s\-_\.]+$', v):
            raise ValueError("프로젝트 이름에 허용되지 않는 문자가 포함되어 있습니다.")
        
        # 연속된 특수문자 방지
        if re.search(r'[\-_\.]{2,}', v):
            raise ValueError("특수문자를 연속으로 사용할 수 없습니다.")
        
        return v.strip()
    
    @validator('description')
    def validate_description(cls, v):
        """설명 검증"""
        if v is None:
            return v
        
        cleaned_text, violations = InputValidator.validate_text_input(
            text=v,
            max_length=1000,
            allow_html=False,
            check_sql_injection=True,
            check_xss=True
        )
        
        return cleaned_text

class FileUploadValidation(SecureBaseModel):
    """파일 업로드 검증"""
    filename: str = Field(..., min_length=1, max_length=255)
    content_type: FileTypeEnum = Field(...)
    size: int = Field(..., gt=0, le=32*1024*1024)  # 최대 32MB
    
    @validator('filename')
    def validate_filename(cls, v):
        """파일명 검증"""
        # 위험한 문자 제거
        dangerous_chars = ['<', '>', ':', '"', '|', '?', '*', '\0']
        for char in dangerous_chars:
            if char in v:
                raise ValueError(f"파일명에 허용되지 않는 문자가 포함되어 있습니다: {char}")
        
        # 상대 경로 패턴 차단
        if '..' in v or v.startswith('/') or v.startswith('\\'):
            raise ValueError("잘못된 파일 경로입니다.")
        
        # 파일 확장자 검증
        allowed_extensions = {
            '.txt', '.pdf', '.csv', '.md', '.docx', '.doc', 
            '.xlsx', '.xls', '.jpg', '.jpeg', '.png', '.gif', '.webp'
        }
        
        file_ext = '.' + v.split('.')[-1].lower() if '.' in v else ''
        if file_ext not in allowed_extensions:
            raise ValueError(f"지원되지 않는 파일 형식입니다: {file_ext}")
        
        return v
    
    @validator('content_type')
    def validate_content_type(cls, v, values):
        """MIME 타입과 파일 확장자 일치 확인"""
        filename = values.get('filename', '')
        if not filename:
            return v
        
        # 확장자와 MIME 타입 매핑
        extension_mime_map = {
            '.txt': FileTypeEnum.TXT,
            '.pdf': FileTypeEnum.PDF,
            '.csv': FileTypeEnum.CSV,
            '.md': FileTypeEnum.MARKDOWN,
            '.docx': FileTypeEnum.DOCX,
            '.doc': FileTypeEnum.DOC,
            '.xlsx': FileTypeEnum.XLSX,
            '.xls': FileTypeEnum.XLS,
            '.jpg': FileTypeEnum.JPEG,
            '.jpeg': FileTypeEnum.JPEG,
            '.png': FileTypeEnum.PNG,
            '.gif': FileTypeEnum.GIF,
            '.webp': FileTypeEnum.WEBP,
        }
        
        file_ext = '.' + filename.split('.')[-1].lower() if '.' in filename else ''
        expected_mime = extension_mime_map.get(file_ext)
        
        if expected_mime and v != expected_mime:
            raise ValueError(f"파일 확장자({file_ext})와 MIME 타입({v})이 일치하지 않습니다.")
        
        return v

class UserRegistration(SecureBaseModel):
    """사용자 등록 검증"""
    email: EmailStr = Field(..., description="이메일 주소")
    password: str = Field(..., min_length=8, max_length=128, description="비밀번호")
    full_name: str = Field(..., min_length=1, max_length=100, description="이름")
    terms_accepted: bool = Field(..., description="약관 동의")
    
    @validator('password')
    def validate_password_strength(cls, v):
        """비밀번호 강도 검증"""
        if len(v) < 8:
            raise ValueError("비밀번호는 최소 8자 이상이어야 합니다.")
        
        # 복잡도 검사
        has_upper = any(c.isupper() for c in v)
        has_lower = any(c.islower() for c in v)
        has_digit = any(c.isdigit() for c in v)
        has_special = any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in v)
        
        strength_score = sum([has_upper, has_lower, has_digit, has_special])
        
        if strength_score < 3:
            raise ValueError("비밀번호는 대문자, 소문자, 숫자, 특수문자 중 최소 3가지를 포함해야 합니다.")
        
        # 일반적인 패턴 차단
        common_patterns = [
            'password', '123456', 'qwerty', 'admin', 'user',
            'test', 'guest', '000000', '111111'
        ]
        
        if any(pattern in v.lower() for pattern in common_patterns):
            raise ValueError("일반적인 패턴의 비밀번호는 사용할 수 없습니다.")
        
        return v
    
    @validator('full_name')
    def validate_full_name(cls, v):
        """이름 검증"""
        # HTML 태그 제거
        cleaned_name = bleach.clean(v, tags=[], strip=True)
        
        # 특수문자 제한
        if not re.match(r'^[a-zA-Z가-힣\s\-\.]+$', cleaned_name):
            raise ValueError("이름에 허용되지 않는 문자가 포함되어 있습니다.")
        
        return cleaned_name.strip()
    
    @validator('terms_accepted')
    def validate_terms(cls, v):
        """약관 동의 검증"""
        if not v:
            raise ValueError("서비스 이용약관에 동의해야 합니다.")
        return v

class APIKeyRequest(SecureBaseModel):
    """API 키 요청 검증"""
    name: str = Field(..., min_length=1, max_length=50, description="API 키 이름")
    description: Optional[str] = Field(None, max_length=200, description="설명")
    permissions: List[str] = Field(default=[], description="권한 목록")
    
    @validator('name')
    def validate_api_key_name(cls, v):
        """API 키 이름 검증"""
        if not re.match(r'^[a-zA-Z0-9\s\-_]+$', v):
            raise ValueError("API 키 이름에 허용되지 않는 문자가 포함되어 있습니다.")
        return v.strip()
    
    @validator('permissions')
    def validate_permissions(cls, v):
        """권한 목록 검증"""
        allowed_permissions = {
            'chat:read', 'chat:write', 'project:read', 'project:write',
            'file:upload', 'file:read', 'admin:read', 'admin:write'
        }
        
        for permission in v:
            if permission not in allowed_permissions:
                raise ValueError(f"허용되지 않는 권한입니다: {permission}")
        
        return v

class SearchQuery(SecureBaseModel):
    """검색 쿼리 검증"""
    query: str = Field(..., min_length=1, max_length=1000, description="검색어")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="필터")
    limit: int = Field(default=10, ge=1, le=100, description="결과 수")
    offset: int = Field(default=0, ge=0, description="오프셋")
    
    @validator('query')
    def validate_search_query(cls, v):
        """검색어 검증"""
        # 검색어 보안 검증
        cleaned_text, violations = InputValidator.validate_text_input(
            text=v,
            max_length=1000,
            allow_html=False,
            check_sql_injection=True,
            check_xss=True
        )
        
        # 너무 짧은 검색어 차단 (스팸 방지)
        if len(cleaned_text.strip()) < 2:
            raise ValueError("검색어는 최소 2자 이상이어야 합니다.")
        
        return cleaned_text
    
    @validator('filters')
    def validate_filters(cls, v):
        """필터 검증"""
        if v is None:
            return v
        
        # 허용되는 필터 키만 허용
        allowed_filter_keys = {
            'date_from', 'date_to', 'file_type', 'project_id', 
            'user_id', 'status', 'category'
        }
        
        for key in v.keys():
            if key not in allowed_filter_keys:
                raise ValueError(f"허용되지 않는 필터입니다: {key}")
        
        return v

class AdminUserUpdate(SecureBaseModel):
    """관리자 사용자 업데이트 검증"""
    is_active: Optional[bool] = Field(None, description="활성 상태")
    is_admin: Optional[bool] = Field(None, description="관리자 권한")
    subscription_tier: Optional[str] = Field(None, description="구독 등급")
    
    @validator('subscription_tier')
    def validate_subscription_tier(cls, v):
        """구독 등급 검증"""
        if v is None:
            return v
        
        allowed_tiers = {'free', 'basic', 'premium', 'enterprise'}
        if v not in allowed_tiers:
            raise ValueError(f"허용되지 않는 구독 등급입니다: {v}")
        
        return v

# 종합 검증 함수들
class ValidationHelper:
    """검증 헬퍼 함수들"""
    
    @staticmethod
    def validate_pagination(limit: int, offset: int) -> tuple[int, int]:
        """페이지네이션 검증"""
        if limit < 1 or limit > 100:
            raise ValueError("limit은 1-100 사이여야 합니다.")
        
        if offset < 0:
            raise ValueError("offset은 0 이상이어야 합니다.")
        
        return limit, offset
    
    @staticmethod
    def validate_uuid_format(uuid_str: str) -> str:
        """UUID 형식 검증"""
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        if not re.match(uuid_pattern, uuid_str.lower()):
            raise ValueError("잘못된 UUID 형식입니다.")
        return uuid_str.lower()
    
    @staticmethod
    def validate_date_range(date_from: Optional[datetime], date_to: Optional[datetime]) -> tuple:
        """날짜 범위 검증"""
        if date_from and date_to:
            if date_from > date_to:
                raise ValueError("시작 날짜가 종료 날짜보다 늦을 수 없습니다.")
        
        return date_from, date_to
    
    @staticmethod
    def sanitize_html_content(content: str, allowed_tags: List[str] = None) -> str:
        """HTML 내용 정화"""
        if allowed_tags is None:
            allowed_tags = ['p', 'br', 'strong', 'em', 'u', 'ol', 'ul', 'li']
        
        cleaned = bleach.clean(
            content,
            tags=allowed_tags,
            attributes={},
            strip=True
        )
        
        return cleaned
    
    @staticmethod
    def validate_json_structure(data: Dict[str, Any], required_keys: List[str]) -> bool:
        """JSON 구조 검증"""
        for key in required_keys:
            if key not in data:
                raise ValueError(f"필수 키가 누락되었습니다: {key}")
        
        return True

# 보안 강화 데코레이터
def validate_input(schema_class):
    """입력 검증 데코레이터"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # request body 검증
            for arg in args:
                if isinstance(arg, dict):
                    try:
                        schema_class(**arg)
                    except Exception as e:
                        raise ValueError(f"Input validation failed: {str(e)}")
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator 