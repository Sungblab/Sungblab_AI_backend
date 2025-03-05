import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.subscription import Subscription, SubscriptionPlan
from app.crud import crud_subscription
from app.core.utils import get_kr_time

logger = logging.getLogger(__name__)

def reset_expired_subscriptions():
    """
    만료된 구독을 무료 플랜으로 자동 초기화하는 스케줄러 작업
    매일 자정에 실행됩니다.
    """
    db = SessionLocal()
    try:
        current_time = get_kr_time()
        logger.info(f"만료된 구독 자동 초기화 작업 시작 - 현재 시간: {current_time}")
        
        # 만료된 구독 찾기 (end_date가 현재 시간보다 이전인 경우)
        expired_subscriptions = db.query(Subscription).filter(
            Subscription.end_date < current_time,
            Subscription.plan != SubscriptionPlan.FREE,
            Subscription.user_id.isnot(None)  # 사용자가 있는 구독만
        ).all()
        
        updated_count = 0
        
        # 각 만료된 구독을 무료 플랜으로 변경
        for subscription in expired_subscriptions:
            subscription.plan = SubscriptionPlan.FREE
            # 무료 플랜의 기본 한도로 초기화
            subscription.monthly_token_limit = crud_subscription.get_plan_token_limit(SubscriptionPlan.FREE)
            subscription.remaining_tokens = subscription.monthly_token_limit
            updated_count += 1
        
        db.commit()
        logger.info(f"자동 초기화 완료: {updated_count}개의 만료된 구독이 무료 플랜으로 변경되었습니다.")
        
    except Exception as e:
        db.rollback()
        logger.error(f"자동 구독 초기화 중 오류 발생: {str(e)}", exc_info=True)
    finally:
        db.close()

def init_scheduler():
    """
    스케줄러 초기화 및 작업 등록
    """
    scheduler = BackgroundScheduler()
    
    # 매일 자정(KST)에 만료된 구독 초기화 작업 실행
    scheduler.add_job(
        reset_expired_subscriptions,
        CronTrigger(hour=0, minute=0, timezone="Asia/Seoul"),
        id="reset_expired_subscriptions",
        replace_existing=True
    )
    
    # 추가 스케줄 작업이 필요하면 여기에 추가
    
    return scheduler 