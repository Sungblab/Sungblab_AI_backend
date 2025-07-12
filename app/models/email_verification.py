from datetime import datetime, timedelta, timezone
from sqlalchemy import Column, String, DateTime, Boolean
from app.db.base_class import Base
from app.core.utils import generate_uuid

class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, index=True, nullable=False)
    verification_code = Column(String, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_verified = Column(Boolean, default=False)

    def is_expired(self) -> bool:
        # 모든 시간은 UTC로 저장된다고 가정
        return datetime.now(timezone.utc) > self.expires_at 