from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.db.base_class import Base
from app.core.utils import generate_uuid
from datetime import datetime, timezone

class TokenUsage(Base):
    __tablename__ = "token_usage"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    room_id = Column(String, nullable=False)
    model = Column(String, nullable=False)
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)
    cache_write_tokens = Column(Integer, nullable=False, default=0)
    cache_hit_tokens = Column(Integer, nullable=False, default=0)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    chat_type = Column(String, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "room_id": self.room_id,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cache_hit_tokens": self.cache_hit_tokens,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "chat_type": self.chat_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        } 