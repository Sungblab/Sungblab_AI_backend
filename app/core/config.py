from typing import Optional, List, Union
from pydantic_settings import BaseSettings
from pydantic import EmailStr, validator
import logging

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    # API 설정
    PROJECT_NAME: str = "SungbLab AI API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # 환경 설정
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    
    # 관리자 계정 설정
    ADMIN_EMAIL: str
    ADMIN_NAME: str
    ADMIN_INITIAL_PASSWORD: str
    CREATE_INITIAL_ADMIN: bool = False
    
    # 로깅 설정 (최소화)
    LOG_LEVEL: str = "WARNING"
    LOG_FORMAT: str = "%(levelname)s - %(name)s - %(message)s"
    LOG_FILE: Optional[str] = None
    
    # 시스템 모니터링 설정 (메모리 사용량 최소화)
    ENABLE_MEMORY_MANAGER: bool = False
    ENABLE_HEALTH_MONITOR: bool = True  # health API 필요하므로 유지
    ENABLE_SCHEDULED_TASKS: bool = True
    ENABLE_PERFORMANCE_MONITORING: bool = True  # DB 모니터링 활성화
    
    # JWT 설정
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    
    # Gemini API 설정 (유일한 AI API)
    GEMINI_API_KEY: str
    
    # Email Settings
    SMTP_HOST: str
    SMTP_PORT: int
    SMTP_USER: str
    SMTP_PASSWORD: str
    SMTP_TLS: bool
    EMAILS_FROM_EMAIL: EmailStr
    EMAILS_FROM_NAME: str

    # Frontend URL
    FRONTEND_URL: str

    # CORS 설정
    BACKEND_CORS_ORIGINS_STR: Optional[str] = None

    # Database settings
    DATABASE_URL: str
    SQLALCHEMY_DATABASE_URL: Optional[str] = None
    REDIS_URL: str

    # Google OAuth2 설정
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        logger.info(f"Environment: {self.ENVIRONMENT}")

    @validator("SQLALCHEMY_DATABASE_URL", pre=True)
    def assemble_db_url(cls, v: Optional[str], values: dict) -> str:
        if v:
            return v
        return values.get("DATABASE_URL", "")

    @property
    def BACKEND_CORS_ORIGINS(self) -> List[str]:
        if self.BACKEND_CORS_ORIGINS_STR is None or self.BACKEND_CORS_ORIGINS_STR == "":
            return [
                "https://sungblab.com",
                "https://www.sungblab.com",
                "http://localhost:3000"
            ]
        if self.BACKEND_CORS_ORIGINS_STR == "*":
            return ["*"]
        return [i.strip() for i in self.BACKEND_CORS_ORIGINS_STR.split(",")]

    @validator("SMTP_TLS", pre=True)
    def parse_smtp_tls(cls, v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() == "true"
        return False

    class Config:
        case_sensitive = True
        env_file = ".env"

# Validation 설정
class ValidationConfig:
    """입력 검증 관련 설정"""
    
    # 파일 업로드 설정
    ALLOWED_FILE_EXTENSIONS = {
        '.txt', '.pdf', '.csv', '.md', '.docx', '.doc', 
        '.xlsx', '.xls', '.jpg', '.jpeg', '.png', '.gif', '.webp'
    }
    
    # 파일명에서 금지된 문자
    DANGEROUS_FILENAME_CHARS = ['<', '>', ':', '"', '|', '?', '*', '\0']
    
    # 약한 비밀번호 패턴
    COMMON_PASSWORD_PATTERNS = [
        'password', '123456', 'qwerty', 'admin', 'user',
        'test', 'guest', '000000', '111111'
    ]
    
    # 파일 확장자와 MIME 타입 매핑
    EXTENSION_MIME_MAP = {
        '.txt': 'text/plain',
        '.pdf': 'application/pdf',
        '.csv': 'text/csv',
        '.md': 'text/markdown',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.doc': 'application/msword',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.xls': 'application/vnd.ms-excel',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp'
    }
    
    # 텍스트 길이 제한
    MAX_CONTENT_LENGTH = 10000
    MAX_DESCRIPTION_LENGTH = 2000
    MAX_FILENAME_LENGTH = 255
    
    # 보안 관련 설정
    MIN_PASSWORD_LENGTH = 8
    MAX_PASSWORD_LENGTH = 128

settings = Settings()
validation_config = ValidationConfig() 