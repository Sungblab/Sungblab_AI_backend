from pydantic import BaseModel, Field
from typing import Optional, List, Literal, Dict, Any
from datetime import datetime, timezone
from pydantic import validator
from app.core.models import ALLOWED_MODELS

class FileInfo(BaseModel):
    type: str
    name: str
    data: str

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class ChatUpdate(BaseModel):
    name: str = ""
    type: Optional[str] = None

class ChatRoomBase(BaseModel):
    name: str = ""

class ChatRoomCreate(ChatRoomBase):
    pass

class ChatCreate(BaseModel):
    name: str = ""
    type: Optional[str] = None

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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

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
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(str(value))

class ChatMessageList(BaseModel):
    messages: List[ChatMessage]

# AI 채팅 요청을 위한 새로운 스키마
class ChatMessageRequest(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessageRequest]
    # 동적으로 허용된 모델 리스트 사용
    model: str
    
    @validator('model')
    def validate_model(cls, v):
        if v not in ALLOWED_MODELS:
            raise ValueError(f'Invalid model. Allowed models: {ALLOWED_MODELS}')
        return v

class TokenUsage(BaseModel):
    id: str
    user_id: Optional[str]
    room_id: str
    model: str
    input_tokens: int
    output_tokens: int
    timestamp: datetime
    chat_type: Optional[str] = None
    cache_write_tokens: Optional[int] = 0
    cache_hit_tokens: Optional[int] = 0

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