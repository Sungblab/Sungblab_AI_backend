from datetime import datetime, timedelta
from sqlalchemy import Column, String, DateTime, Boolean
from app.db.base_class import Base
from app.core.utils import get_kr_time
import pytz

KST = pytz.timezone('Asia/Seoul')

class EmailVerification(Base):
    __tablename__ = "email_verifications"
    __abstract__ = False  # CustomBase의 기본 설정을 오버라이드

    email = Column(String, primary_key=True, index=True)
    verification_code = Column(String, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=get_kr_time)
    updated_at = Column(DateTime(timezone=True), default=get_kr_time, onupdate=get_kr_time)

    def is_expired(self) -> bool:
        # DB에서 가져온 시간이 timezone naive할 수 있으므로 KST timezone 정보를 추가
        if self.expires_at.tzinfo is None:
            expires_at = KST.localize(self.expires_at)
        else:
            expires_at = self.expires_at
        return get_kr_time() > expires_at 