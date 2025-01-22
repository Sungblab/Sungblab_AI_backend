from sqlalchemy import Boolean, Column, String, DateTime, Enum as SQLEnum, Integer
from sqlalchemy.orm import relationship
from app.models.base import Base
from datetime import datetime
import enum
import uuid

def generate_uuid():
    return str(uuid.uuid4())

class AuthProvider(str, enum.Enum):
    LOCAL = "LOCAL"
    GOOGLE = "GOOGLE"
    KAKAO = "KAKAO"
    NAVER = "NAVER"

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=True)  # 소셜 로그인의 경우 비밀번호가 없을 수 있음
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    
    # 비밀번호 재설정 관련 필드
    reset_password_token = Column(String, unique=True, nullable=True)
    reset_password_token_expires = Column(DateTime, nullable=True)
    
    # 소셜 로그인 관련 필드
    auth_provider = Column(SQLEnum(AuthProvider), nullable=False, default=AuthProvider.LOCAL)
    social_id = Column(String, nullable=True)  # 소셜 서비스에서의 고유 ID
    profile_image = Column(String, nullable=True)  # 프로필 이미지 URL
    
    # 메시지 카운트 필드 추가
    message_count = Column(Integer, nullable=False, default=0)

    # Relationships
    projects = relationship("Project", back_populates="user", cascade="all, delete-orphan")
    subscription = relationship("Subscription", back_populates="user", uselist=False)

    def __repr__(self):
        return f"<User {self.email}>" 