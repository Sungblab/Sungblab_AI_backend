from sqlalchemy import Column, String, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.db.base_class import Base
from datetime import datetime
from app.core.utils import get_kr_time
import uuid

def generate_uuid():
    return str(uuid.uuid4())

class ChatRoom(Base):
    __tablename__ = "chatroom"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=get_kr_time)
    updated_at = Column(DateTime, default=get_kr_time)

    messages = relationship("ChatMessage", back_populates="chat", cascade="all, delete-orphan")