from pydantic import BaseModel, Field
from typing import Optional, List, Literal, Dict, Any
from datetime import datetime
from pydantic import validator

class FileInfo(BaseModel):
    type: str
    name: str
    data: str

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class ChatBase(BaseModel):
    name: str = ""
    type: Optional[str] = None

class ChatCreate(ChatBase):
    pass

class ChatUpdate(ChatBase):
    pass

class ChatRoomBase(BaseModel):
    name: str = ""

class ChatRoomCreate(ChatRoomBase):
    pass

class ChatRoom(ChatRoomBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ChatRoomList(BaseModel):
    rooms: List[ChatRoom]

class ChatMessageBase(BaseModel):
    content: str
    role: str
    files: Optional[List[Dict[str, str]]] = None
    citations: Optional[List[Dict[str, str]]] = None
    reasoning_content: Optional[str] = None
    thought_time: Optional[float] = None

class ChatMessageCreate(ChatMessageBase):
    room_id: Optional[str] = None

class ChatMessage(ChatMessageBase):
    id: str
    room_id: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

    @validator('created_at', 'updated_at', pre=True)
    def parse_datetime(cls, value):
        if isinstance(value, datetime):
            return value
        if value is None:
            return datetime.now()
        return datetime.fromisoformat(str(value))

class ChatMessageList(BaseModel):
    messages: List[ChatMessage]

# AI 채팅 요청을 위한 새로운 스키마
class ChatMessageRequest(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessageRequest]
    model: Literal[
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "sonar-pro",
        "sonar",
        "deepseek-reasoner",
        "deepseek-chat"
    ] = "claude-3-5-haiku-20241022"

class TokenUsage(BaseModel):
    id: str
    user_id: Optional[str]
    room_id: str
    model: str
    input_tokens: int
    output_tokens: int
    timestamp: datetime

    class Config:
        from_attributes = True

class PromptGenerateRequest(BaseModel):
    """프롬프트 생성 요청 스키마"""
    task: str

    class Config:
        json_schema_extra = {
            "example": {
                "task": "과학 실험 보고서 작성 방법 설명"
            }
        } 