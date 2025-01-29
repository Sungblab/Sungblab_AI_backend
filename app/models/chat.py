from sqlalchemy import Column, String, DateTime, Text, ForeignKey, JSON, func, Float, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base_class import Base
import uuid

def generate_uuid():
    return str(uuid.uuid4())

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, default=generate_uuid)
    room_id = Column(String, ForeignKey("chatroom.id", ondelete="CASCADE"), nullable=False)
    content = Column(String, nullable=False)
    role = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    files = Column(JSON)  # 여러 파일 정보를 저장하기 위한 JSON 필드
    citations = Column(JSON)
    reasoning_content = Column(String)
    thought_time = Column(Float)

    chat = relationship("ChatRoom", back_populates="messages")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "room_id": self.room_id,
            "content": self.content,
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "files": self.files,
            "citations": self.citations,  # JSON 배열이 자동으로 Python 리스트로 변환됨
            "reasoning_content": self.reasoning_content,
            "thought_time": self.thought_time
        }

# 하위 호환성을 위해 ChatMessage 이름을 유지
__all__ = ['ChatMessage'] 