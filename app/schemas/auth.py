from typing import Optional
from pydantic import BaseModel, EmailStr, constr
from app.models.user import AuthProvider

class UserBase(BaseModel):
    email: EmailStr
    full_name: str

class UserCreate(UserBase):
    password: constr(min_length=8)  # 최소 8자 이상

class User(UserBase):
    id: str
    is_active: bool = True
    is_superuser: bool = False
    auth_provider: AuthProvider = AuthProvider.LOCAL
    profile_image: Optional[str] = None

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class SocialLogin(BaseModel):
    provider: AuthProvider
    access_token: str
    remember_me: bool = False

class GoogleUser(BaseModel):
    email: str
    name: str
    picture: Optional[str] = None
    sub: str  # Google의 고유 ID 