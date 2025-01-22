from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from enum import Enum

class ProjectType(str, Enum):
    assignment = "assignment"
    record = "record"

class ProjectBase(BaseModel):
    name: str
    type: ProjectType
    description: Optional[str] = None
    system_instruction: Optional[str] = None
    settings: Optional[dict] = None

class ProjectCreate(ProjectBase):
    pass

class ProjectUpdate(ProjectBase):
    pass

class Project(ProjectBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ProjectChatBase(BaseModel):
    name: str

class ProjectChatCreate(ProjectChatBase):
    pass

class ProjectChat(ProjectChatBase):
    id: str
    project_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ProjectWithChats(Project):
    chats: List[ProjectChat] 