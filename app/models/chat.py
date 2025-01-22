from sqlalchemy import Column, String, DateTime, Text, ForeignKey, JSON, func
from sqlalchemy.orm import relationship
from app.models.base import Base
import uuid

def generate_uuid():
    return str(uuid.uuid4())

# ChatMessage는 ProjectMessage로 대체됩니다.
# ChatMessage = ProjectMessage

class ChatMessage(Base):
    __tablename__ = "project_messages"

    id = Column(String, primary_key=True, default=generate_uuid)
    content = Column(Text, nullable=False)
    role = Column(String, nullable=False)
    room_id = Column(String, ForeignKey("projectchat.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=func.now())
    file = Column(JSON, nullable=True)

    chat = relationship("app.models.project.ProjectChat", back_populates="messages")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "content": self.content,
            "role": self.role,
            "room_id": self.room_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "file": self.file
        }

# 하위 호환성을 위해 ChatMessage 이름을 유지
__all__ = ['ChatMessage'] 