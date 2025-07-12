from typing import Optional
from sqlalchemy.orm import Session
from app.models.subscription import Subscription, SubscriptionPlan
from datetime import datetime, timedelta, timezone
import logging

logger = logging.getLogger(__name__)

def get_subscription(db: Session, user_id: str) -> Optional[Subscription]:
    """사용자의 구독 정보를 조회합니다."""
    return db.query(Subscription).filter(Subscription.user_id == user_id).first()

def get_all_subscriptions(db: Session, skip: int = 0, limit: int = 100):
    """모든 구독 정보를 조회합니다."""
    return db.query(Subscription).offset(skip).limit(limit).all()

def update_subscription_plan(db: Session, user_id: str, plan: SubscriptionPlan, update_limits: bool = True) -> Optional[Subscription]:
    """
    사용자의 구독 플랜을 업데이트합니다.
    update_limits가 True이면 사용량 제한도 함께 업데이트합니다.
    """
    subscription = get_subscription(db, user_id)
    if not subscription:
        return None
        
    subscription.plan = plan
    
    if update_limits:
        # 현재 시간 가져오기
        current_time = datetime.now(timezone.utc)
        
        # 구독이 만료되었는지 확인 (0일 이하로 남은 경우)
        is_expired = subscription.end_date and current_time >= subscription.end_date
        
        # 플랜에 맞는 제한량으로 업데이트하고 구독 기간 갱신
        if is_expired:
            # 만료된 경우 무조건 갱신
            subscription.start_date = current_time
            subscription.end_date = current_time + timedelta(days=30)
            subscription.renewal_date = subscription.end_date
            subscription.status = "active"
            from app.models.subscription import PLAN_LIMITS
            subscription.group_limits = PLAN_LIMITS[plan]
            subscription.reset_usage()
        else:
            # 만료되지 않은 경우 기존 로직 유지
            subscription.update_limits_for_plan()
    
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription

def reset_usage(db: Session, user_id: str) -> Optional[Subscription]:
    """사용자의 사용량을 초기화합니다."""
    try:
        subscription = db.query(Subscription).filter(
            Subscription.user_id == user_id
        ).with_for_update().first()
        
        if not subscription:
            return None
            
        subscription.reset_usage()
        db.commit()
        db.refresh(subscription)
        return subscription
    except Exception as e:
        db.rollback()
        raise e

def check_and_update_expiration(db: Session, user_id: str) -> Optional[Subscription]:
    """구독 만료 여부를 확인하고 필요한 경우 업데이트합니다."""
    try:
        subscription = db.query(Subscription).filter(
            Subscription.user_id == user_id
        ).with_for_update().first()
        
        if not subscription:
            return None
        
        current_time = datetime.now(timezone.utc)
        
        # 구독이 만료되었는지 확인
        if subscription.end_date and current_time >= subscription.end_date:
            # 만료된 경우 무조건 갱신
            subscription.start_date = current_time
            subscription.end_date = current_time + timedelta(days=30)
            subscription.renewal_date = subscription.end_date
            subscription.status = "active"
            
            # 무료 플랜으로 설정 (유료 플랜이었다면)
            if subscription.plan != SubscriptionPlan.FREE:
                subscription.plan = SubscriptionPlan.FREE
                from app.models.subscription import PLAN_LIMITS
                subscription.group_limits = PLAN_LIMITS[SubscriptionPlan.FREE]
            
            # 사용량 초기화
            subscription.reset_usage()
        else:
            # 기존 로직 유지
            subscription.check_expiration()
            
        db.commit()
        db.refresh(subscription)
        return subscription
    except Exception as e:
        db.rollback()
        raise e

def update_model_usage(db: Session, user_id: str, model_name: str) -> Optional[Subscription]:
    """모델 사용량을 원자적으로 업데이트합니다."""
    try:
        # 먼저 구독 정보를 조회하여 모델 그룹 확인
        subscription = db.query(Subscription).filter(
            Subscription.user_id == user_id
        ).first()

        if not subscription:
            return None

        group = subscription.get_model_group(model_name)
        if not group:
            return None

        # PostgreSQL JSON 함수를 사용한 원자적 업데이트
        from sqlalchemy import text, func
        
        # JSONB의 특정 키 값을 원자적으로 증가
        result = db.execute(
            text("""
                UPDATE subscriptions 
                SET group_usage = CASE 
                    WHEN group_usage::jsonb ? :group_key THEN
                        jsonb_set(
                            group_usage::jsonb, 
                            ARRAY[:group_key], 
                            to_jsonb((group_usage->>:group_key)::int + 1)
                        )::json
                    ELSE
                        jsonb_set(
                            COALESCE(group_usage::jsonb, '{}'::jsonb),
                            ARRAY[:group_key],
                            '1'::jsonb
                        )::json
                    END,
                    updated_at = :updated_at
                WHERE user_id = :user_id
                RETURNING *
            """),
            {
                'group_key': group,
                'user_id': user_id,
                'updated_at': datetime.now(timezone.utc)
            }
        )
        
        updated_row = result.fetchone()
        if not updated_row:
            return None
            
        db.commit()
        
        # 업데이트된 구독 정보를 다시 조회
        return db.query(Subscription).filter(
            Subscription.user_id == user_id
        ).first()

    except Exception as e:
        db.rollback()
        logger.error(f"사용량 업데이트 중 오류 발생: {str(e)}", exc_info=True)
        raise e 