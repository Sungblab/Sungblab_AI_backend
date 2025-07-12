from sqlalchemy import Column, String, Text, ForeignKey, JSON, Float, Integer
from sqlalchemy.orm import relationship
from app.db.base_class import Base
from app.core.utils import generate_uuid

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, default=generate_uuid)
    room_id = Column(String, ForeignKey("chatroom.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    role = Column(String, nullable=False)
    files = Column(JSON)  # 여러 파일 정보를 저장하기 위한 JSON 필드
    citations = Column(JSON)
    reasoning_content = Column(Text)
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