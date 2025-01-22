from typing import Optional
from pydantic import BaseModel
from datetime import datetime

class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    is_active: bool
    is_superuser: bool
    created_at: datetime
    auth_provider: str
    profile_image: Optional[str] = None

    class Config:
        from_attributes = True

class UserUpdate(BaseModel):
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None 