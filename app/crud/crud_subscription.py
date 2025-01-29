from typing import Optional
from sqlalchemy.orm import Session
from app.models.subscription import Subscription, SubscriptionPlan
from app.core.utils import get_kr_time
from sqlalchemy import update

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
        # 플랜에 맞는 제한량으로 업데이트하고 구독 기간 갱신
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
            
        subscription.check_expiration()
        db.commit()
        db.refresh(subscription)
        return subscription
    except Exception as e:
        db.rollback()
        raise e

def update_model_usage(db: Session, user_id: str, model_name: str) -> Optional[Subscription]:
    """모델 사용량을 업데이트합니다."""
    try:
        # SELECT FOR UPDATE로 락 획득
        subscription = db.query(Subscription).filter(
            Subscription.user_id == user_id
        ).with_for_update().first()
        
        if not subscription:
            return None
            
        # 사용량 증가 시도
        if subscription.increment_usage(model_name):
            # 변경사항 즉시 저장
            db.execute(
                update(Subscription).
                where(Subscription.user_id == user_id).
                values(group_usage=subscription.group_usage)
            )
            db.commit()
            db.refresh(subscription)
            return subscription
            
        return None
    except Exception as e:
        db.rollback()
        raise e 