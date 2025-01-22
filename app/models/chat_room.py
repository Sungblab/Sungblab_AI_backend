from sqlalchemy import Column, String, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.models.base import Base
from datetime import datetime
import uuid

def generate_uuid():
    return str(uuid.uuid4())

class ChatRoom(Base):
    __tablename__ = "chatroom"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, default=generate_uuid)
    room_id = Column(String, ForeignKey("chatroom.id"), nullable=False)
    content = Column(Text, nullable=False)
    role = Column(String, nullable=False)  # 'user' or 'assistant'
    created_at = Column(DateTime, default=datetime.utcnow)
    file = Column(JSON, nullable=True)  # 파일 정보를 JSON으로 저장 