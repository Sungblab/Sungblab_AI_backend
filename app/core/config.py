from typing import Optional, List, Union
from pydantic_settings import BaseSettings
from pydantic import EmailStr, validator

class Settings(BaseSettings):
    PROJECT_NAME: str = "SungbLab AI"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # 환경 설정
    ENVIRONMENT: str = "development"  # development, production
    DEBUG: bool = False
    
    # 관리자 계정 설정
    ADMIN_EMAIL: str = "admin@sungblab.com"
    ADMIN_NAME: str = "관리자"
    ADMIN_INITIAL_PASSWORD: str = "admin123!"
    CREATE_INITIAL_ADMIN: bool = False  # 프로덕션에서는 False로 설정
    
    # 로깅 설정
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_FILE: Optional[str] = None  # 프로덕션에서는 파일 경로 설정
    
    # JWT 설정
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    
    # Claude API 설정
    ANTHROPIC_API_KEY: str
    
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
    BACKEND_CORS_ORIGINS: List[str] = [
        "https://sungblab.com",
        "https://www.sungblab.com",
        "http://localhost:3000"  # 개발 환경용
    ]

    # Database
    DATABASE_URL: str
    SQLALCHEMY_DATABASE_URL: str = None

    # Google OAuth2 설정
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str

    @validator("SQLALCHEMY_DATABASE_URL", pre=True)
    def assemble_db_url(cls, v: Optional[str], values: dict) -> str:
        if v:
            return v
        return values.get("DATABASE_URL")

    @validator("BACKEND_CORS_ORIGINS", pre=True)
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            if v == "*":
                return ["*"]
            return [i.strip() for i in v.split(",")]
        return v

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