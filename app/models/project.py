from sqlalchemy import Column, String, DateTime, Text, ForeignKey, JSON, Enum, Boolean, func, Float
from sqlalchemy.orm import relationship
import enum
from datetime import datetime
import uuid
from app.db.base_class import Base

def generate_uuid():
    return str(uuid.uuid4())

class ProjectType(str, enum.Enum):
    assignment = "assignment"
    record = "record"

class Project(Base):
    __tablename__ = "projects"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    description = Column(Text)
    system_instruction = Column(Text, nullable=True)
    settings = Column(JSON, nullable=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="projects")
    chats = relationship("ProjectChat", back_populates="project", cascade="all, delete-orphan")

    def to_dict(self, include_chats: bool = True):
        result = {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "system_instruction": self.system_instruction,
            "settings": self.settings,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_chats:
            result["chats"] = [chat.to_dict(include_messages=False) for chat in self.chats]
        return result

class ProjectChat(Base):
    __tablename__ = "projectchat"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type = Column(Enum(ProjectType), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    project = relationship("Project", back_populates="chats")
    messages = relationship("ProjectMessage", back_populates="chat", cascade="all, delete-orphan")

    def to_dict(self, include_messages: bool = False):
        result = {
            "id": self.id,
            "name": self.name,
            "project_id": self.project_id,
            "type": self.type.value if isinstance(self.type, ProjectType) else self.type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_messages:
            result["messages"] = [message.to_dict() for message in self.messages]
        return result 

class ProjectMessage(Base):
    __tablename__ = "project_messages"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=generate_uuid)
    content = Column(Text, nullable=False)
    role = Column(String, nullable=False)  # user, assistant
    room_id = Column(String, ForeignKey("projectchat.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    files = Column(JSON, nullable=True)
    citations = Column(JSON, nullable=True)
    reasoning_content = Column(String, nullable=True)
    thought_time = Column(Float, nullable=True)

    chat = relationship("ProjectChat", back_populates="messages")

    def to_dict(self):
        return {
            "id": self.id,
            "content": self.content,
            "role": self.role,
            "room_id": self.room_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "files": self.files,
            "citations": self.citations,
            "reasoning_content": self.reasoning_content,
            "thought_time": self.thought_time
        } 