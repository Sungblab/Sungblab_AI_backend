from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey, Enum as SQLEnum, JSON
from sqlalchemy.orm import relationship
from app.db.base_class import Base
from datetime import datetime, timedelta
from app.core.utils import get_kr_time
import enum
import uuid
import pytz

KST = pytz.timezone('Asia/Seoul')

def generate_uuid():
    return str(uuid.uuid4())

# 플랜별 제한량 정의
PLAN_LIMITS = {
    "FREE": {
        "basic_chat": 50,      
        "normal_analysis": 10,  
        "advanced_analysis": 5   
    },
    "BASIC": {
        "basic_chat": 200,       # 기본 대화 100회
        "normal_analysis": 70,   # 일반 분석 50회
        "advanced_analysis": 50  # 고급 분석 20회
    },
    "PREMIUM": {
        "basic_chat": 500,       # 기본 대화 300회
        "normal_analysis": 150,  # 일반 분석 150회
        "advanced_analysis": 100  # 고급 분석 50회
    }
}

class SubscriptionPlan(str, enum.Enum):
    FREE = "FREE"
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"

class ModelGroup(str, enum.Enum):
    BASIC_CHAT = "basic_chat"      
    NORMAL_ANALYSIS = "normal_analysis" 
    ADVANCED_ANALYSIS = "advanced_analysis"  
class AIModel(str, enum.Enum):
    CLAUDE_SONNET = "claude-3-5-sonnet-20241022"
    CLAUDE_HAIKU = "claude-3-5-haiku-20241022"
    SONAR_PRO = "sonar-pro"
    SONAR = "sonar"
    DEEPSEEK_REASONER = "deepseek-reasoner"
    GEMINI_FLASH = "gemini-2.0-flash"

# 모델 그룹 매핑
MODEL_GROUP_MAPPING = {
    "claude-3-5-haiku-20241022": ModelGroup.BASIC_CHAT,
    "sonar": ModelGroup.NORMAL_ANALYSIS,
    "sonar-reasoning": ModelGroup.NORMAL_ANALYSIS,  
    "deepseek-reasoner": ModelGroup.NORMAL_ANALYSIS,
    "claude-3-5-sonnet-20241022": ModelGroup.ADVANCED_ANALYSIS,
    "sonar-pro": ModelGroup.ADVANCED_ANALYSIS,
    "gemini-2.0-flash": ModelGroup.BASIC_CHAT,  
}

class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    plan = Column(SQLEnum(SubscriptionPlan), default=SubscriptionPlan.FREE)
    status = Column(String, default="active")  # active, cancelled, expired
    start_date = Column(DateTime(timezone=True), default=get_kr_time)
    end_date = Column(DateTime(timezone=True), default=lambda: get_kr_time() + timedelta(days=30))
    auto_renew = Column(Boolean, default=True)
    renewal_date = Column(DateTime(timezone=True), default=lambda: get_kr_time() + timedelta(days=30))
    
    # 그룹별 사용량 추적
    group_usage = Column(JSON, default={
        "basic_chat": 0,
        "normal_analysis": 0,
        "advanced_analysis": 0
    })
    
    # 그룹별 제한량 (플랜에 따라 다름)
    group_limits = Column(JSON, default=PLAN_LIMITS["FREE"])

    # Relationships
    user = relationship("User", back_populates="subscription")

    def update_limits_for_plan(self):
        """현재 플랜에 맞는 제한량으로 업데이트하고 구독 기간을 초기화합니다."""
        self.group_limits = PLAN_LIMITS[self.plan]
        current_time = get_kr_time()
        
        # 구독 기간을 현재 시점부터 30일로 초기화
        self.start_date = current_time
        self.end_date = current_time + timedelta(days=30)
        self.renewal_date = self.end_date
        
        # 상태 업데이트
        self.status = "active"
        
        # 사용량 초기화
        self.reset_usage()

    def check_expiration(self):
        """구독 만료 여부를 확인하고 상태를 업데이트합니다."""
        current_time = get_kr_time()
        if self.end_date and current_time > self.end_date:
            if self.auto_renew:
                self.renew_subscription()
            else:
                self.status = "expired"

    def renew_subscription(self):
        """구독을 갱신합니다."""
        current_time = get_kr_time()
        self.start_date = current_time
        self.end_date = current_time + timedelta(days=30)
        self.renewal_date = self.end_date
        self.status = "active"
        
        # 유료 플랜인 경우 무료 플랜으로 변경
        if self.plan != SubscriptionPlan.FREE:
            self.plan = SubscriptionPlan.FREE
            self.group_limits = PLAN_LIMITS["FREE"]
        
        self.reset_usage()

    def get_model_group(self, model_name: str) -> str:
        """모델 이름으로 해당 그룹을 반환합니다."""
        return MODEL_GROUP_MAPPING.get(model_name)

    def can_use_model(self, model_name: str) -> bool:
        """특정 모델 사용 가능 여부를 확인합니다."""
        group = self.get_model_group(model_name)
        if not group:
            return False
        return self.group_usage[group] < self.group_limits[group]

    def increment_usage(self, model_name: str) -> bool:
        """모델 사용량을 증가시킵니다."""
        group = self.get_model_group(model_name)

        
        if not group:
            return False
        
        if not self.can_use_model(model_name):
            return False
        
        # 기본 딕셔너리 확인 및 초기화
        if not isinstance(self.group_usage, dict):
            self.group_usage = {
                "basic_chat": 0,
                "normal_analysis": 0,
                "advanced_analysis": 0
            }
        
        # 안전하게 증가
        current_usage = self.group_usage.get(group, 0)
        if current_usage >= self.group_limits[group]:
            return False
        
        self.group_usage[group] = current_usage + 1
        return True

    def get_remaining_usage(self, model_name: str) -> int:
        """특정 모델의 남은 사용 가능 횟수를 반환합니다."""
        group = self.get_model_group(model_name)
        if not group:
            return 0
        return max(0, self.group_limits[group] - self.group_usage[group])

    def reset_usage(self):
        """사용량을 초기화합니다."""
        self.group_usage = {
            "basic_chat": 0,
            "normal_analysis": 0,
            "advanced_analysis": 0
        }

    def to_dict(self):
        base_dict = {
            "id": self.id,
            "user_id": self.user_id,
            "plan": self.plan,
            "status": self.status,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "auto_renew": self.auto_renew,
            "renewal_date": self.renewal_date.isoformat() if self.renewal_date else None,
            "user_email": self.user.email,
            "user_name": self.user.full_name,
            "group_usage": self.group_usage,
            "group_limits": self.group_limits,
            "days_remaining": (self.end_date - get_kr_time()).days if self.end_date else 0
        }
        
        # 각 그룹별 남은 사용량 추가
        base_dict["remaining_usage"] = {
            group: self.group_limits[group] - self.group_usage[group]
            for group in self.group_usage.keys()
        }
        
        return base_dict 