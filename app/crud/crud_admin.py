from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from datetime import datetime, timedelta
from typing import List, Dict
from app.models.user import User
from app.models.subscription import Subscription, SubscriptionPlan
from app.models.chat import ChatMessage
from app.models.chat_room import ChatRoom
from app.models.stats import TokenUsage
from app.core.utils import get_kr_time

def get_user_stats(db: Session) -> Dict:
    """사용자 통계를 조회합니다."""
    now = get_kr_time()
    month_ago = now - timedelta(days=30)
    two_months_ago = now - timedelta(days=60)

    # 전체 사용자 수
    total_users = db.query(func.count(User.id)).scalar()

    # 활성 사용자 수
    active_users = db.query(func.count(User.id)).filter(User.is_active == True).scalar()

    # 월간 활성 사용자 수 (최근 30일 내 채팅 기록이 있는 사용자)
    monthly_active = db.query(func.count(func.distinct(ChatRoom.user_id))).join(
        ChatMessage, ChatMessage.room_id == ChatRoom.id
    ).filter(
        ChatMessage.created_at >= month_ago
    ).scalar()

    # 지난달 신규 가입자 수
    new_users_last_month = db.query(func.count(User.id)).filter(
        User.created_at >= month_ago
    ).scalar()

    # 지난달 대비 성장률
    new_users_previous_month = db.query(func.count(User.id)).filter(
        and_(
            User.created_at >= two_months_ago,
            User.created_at < month_ago
        )
    ).scalar()

    # 활성 사용자 성장률
    previous_active = db.query(func.count(func.distinct(ChatRoom.user_id))).join(
        ChatMessage, ChatMessage.room_id == ChatRoom.id
    ).filter(
        ChatMessage.created_at >= two_months_ago,
        ChatMessage.created_at < month_ago
    ).scalar()

    # 성장률 계산
    growth_rate = 0
    active_growth_rate = 0
    if new_users_previous_month > 0:
        growth_rate = ((new_users_last_month - new_users_previous_month) / new_users_previous_month) * 100
    if previous_active > 0:
        active_growth_rate = ((monthly_active - previous_active) / previous_active) * 100

    # 관리자 수
    admin_count = db.query(func.count(User.id)).filter(User.is_superuser == True).scalar()

    return {
        "total": total_users,
        "active": active_users,
        "monthly_active": monthly_active,
        "growth_rate": round(growth_rate, 2),
        "active_growth_rate": round(active_growth_rate, 2),
        "new_users_last_month": new_users_last_month,
        "admin_count": admin_count
    }

def get_subscription_stats(db: Session) -> Dict:
    """구독 통계를 조회합니다."""
    now = get_kr_time()

    # 전체 구독자 수 (무료 플랜 제외)
    total_subs = db.query(func.count(Subscription.id)).filter(
        Subscription.plan != SubscriptionPlan.FREE
    ).scalar()

    # 활성 구독자 수 (무료 플랜 제외)
    active_subs = db.query(func.count(Subscription.id)).filter(
        and_(
            Subscription.end_date > now,
            Subscription.status == "active",
            Subscription.plan != SubscriptionPlan.FREE
        )
    ).scalar()

    # 만료된 구독자 수 (무료 플랜 제외)
    expired_subs = db.query(func.count(Subscription.id)).filter(
        and_(
            Subscription.status == "expired",
            Subscription.plan != SubscriptionPlan.FREE
        )
    ).scalar()

    # 플랜별 구독자 수
    plan_stats = {}
    for plan in SubscriptionPlan:
        count = db.query(func.count(Subscription.id)).filter(
            and_(
                Subscription.plan == plan,
                Subscription.status == "active"  # 활성 상태인 구독만 카운트
            )
        ).scalar()
        plan_stats[plan.value] = count

    # 수익 통계 (현재는 0으로 설정)
    revenue_stats = {
        "monthly": {
            "BASIC": 0,
            "PREMIUM": 0,
            "total": 0
        }
    }

    return {
        "total": total_subs,
        "active": active_subs,
        "expired": expired_subs,
        "by_plan": plan_stats,
        "revenue": revenue_stats
    }

def get_recent_users(db: Session, limit: int = 3) -> List[User]:
    """최근 가입한 사용자 목록을 조회합니다."""
    return db.query(User).order_by(User.created_at.desc()).limit(limit).all()

def get_model_usage_stats(db: Session) -> List[Dict]:
    """AI 모델별 사용량 통계를 조회합니다."""
    # 전체 토큰 수
    total_tokens = db.query(
        func.sum(TokenUsage.input_tokens + TokenUsage.output_tokens)
    ).scalar() or 0

    # 모델별 사용량
    model_stats = db.query(
        TokenUsage.model,
        func.sum(TokenUsage.input_tokens + TokenUsage.output_tokens).label('total_tokens')
    ).group_by(TokenUsage.model).all()

    result = []
    for model, tokens in model_stats:
        usage_percentage = (tokens / total_tokens * 100) if total_tokens > 0 else 0
        result.append({
            "model_name": model,
            "usage_percentage": round(usage_percentage, 2),
            "total_tokens": tokens
        })

    return result 