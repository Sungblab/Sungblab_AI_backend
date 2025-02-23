from typing import Optional, List
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

class RecentUserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    profile_image: Optional[str] = None
    created_at: datetime

class UserStats(BaseModel):
    total: int
    active: int
    monthly_active: int
    growth_rate: float
    active_growth_rate: float
    new_users_last_month: int
    admin_count: int

class SubscriptionStats(BaseModel):
    total: int
    active: int
    expired: int
    by_plan: dict
    revenue: dict

class ModelUsageStats(BaseModel):
    model_name: str
    usage_percentage: float
    total_tokens: int

class AdminOverviewResponse(BaseModel):
    user_stats: UserStats
    subscription_stats: SubscriptionStats
    recent_users: List[RecentUserResponse]
    model_usage_stats: List[ModelUsageStats] 