from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class FileInfo(BaseModel):
    type: str
    name: str
    data: str

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
    file: Optional[FileInfo] = None

class ChatMessageCreate(ChatMessageBase):
    room_id: Optional[str] = None

class ChatMessage(ChatMessageBase):
    id: str
    room_id: str
    created_at: datetime

    class Config:
        from_attributes = True

class ChatMessageList(BaseModel):
    messages: List[ChatMessage]

# AI 채팅 요청을 위한 새로운 스키마
class ChatMessageRequest(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessageRequest]
    model: str = "claude-3-5-sonnet-20241022"

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