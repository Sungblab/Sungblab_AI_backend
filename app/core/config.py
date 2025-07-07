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
    
    # 로깅 설정
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_FILE: Optional[str] = None
    
    @property
    def effective_log_level(self) -> str:
        """환경에 따른 실제 로깅 레벨 반환"""
        if self.ENVIRONMENT == "production":
            return "WARNING"  # 프로덕션에서는 WARNING 이상만 로그
        return self.LOG_LEVEL
    
    # JWT 설정
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    
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

    # Database (Supabase) - Optional since we're using PostgreSQL directly
    SUPABASE_URL: Optional[str] = None
    SUPABASE_KEY: Optional[str] = None
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None
    DATABASE_URL: str
    SQLALCHEMY_DATABASE_URL: Optional[str] = None

    # Google OAuth2 설정
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 프로덕션 환경이 아닐 때만 환경 정보 출력
        if self.ENVIRONMENT != "production":
            logger.debug(f"Environment: {self.ENVIRONMENT}")

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

settings = Settings() 