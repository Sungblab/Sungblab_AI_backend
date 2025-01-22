from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from app.models.base import Base
from datetime import datetime
import enum
import uuid

def generate_uuid():
    return str(uuid.uuid4())

class SubscriptionPlan(str, enum.Enum):
    FREE = "FREE"
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"

class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    plan = Column(SQLEnum(SubscriptionPlan), default=SubscriptionPlan.FREE)
    status = Column(String, default="active")  # active, cancelled, expired
    start_date = Column(DateTime, default=datetime.utcnow)
    end_date = Column(DateTime)
    auto_renew = Column(Boolean, default=True)
    message_count = Column(Integer, default=0)
    message_limit = Column(Integer, default=15)  # 기본 무료 플랜 제한
    renewal_date = Column(DateTime)

    # Relationships
    user = relationship("User", back_populates="subscription")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "plan": self.plan,
            "status": self.status,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "auto_renew": self.auto_renew,
            "message_count": self.message_count,
            "message_limit": self.message_limit,
            "renewal_date": self.renewal_date.isoformat() if self.renewal_date else None,
            "user_email": self.user.email,
            "user_name": self.user.full_name
        } 