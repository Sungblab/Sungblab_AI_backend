from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from app.db.base_class import Base
from app.core.utils import generate_uuid

class ChatRoom(Base):
    __tablename__ = "chatroom"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    messages = relationship("ChatMessage", back_populates="chat", cascade="all, delete-orphan")