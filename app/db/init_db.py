from sqlalchemy.orm import Session
from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.crud import crud_user
from app.schemas.auth import UserCreate
from app.core.config import settings
from app.models.subscription import Subscription, SubscriptionPlan
from datetime import datetime, timedelta
from app.models.user import User
from app.core.utils import get_kr_time
import logging

logger = logging.getLogger("sungblab_api")

def init_db() -> None:
    # 데이터베이스 테이블 생성
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # 관리자 계정이 이미 존재하는지 확인
        existing_admin = crud_user.get_user_by_email(db, email=settings.ADMIN_EMAIL)
        
        if not existing_admin and settings.CREATE_INITIAL_ADMIN:
            admin_in = UserCreate(
                email=settings.ADMIN_EMAIL,
                full_name=settings.ADMIN_NAME,
                password=settings.ADMIN_INITIAL_PASSWORD,
                is_superuser=True
            )
            admin = crud_user.create_user(db, obj_in=admin_in)
            db.commit()
            logger.info("Admin user created")
        else:
            logger.info("Admin user already exists")
        
        # 모든 사용자에 대해 기본 구독 정보 생성
        users = db.query(User).all()
        for user in users:
            subscription = db.query(Subscription).filter(
                Subscription.user_id == str(user.id)
            ).first()
            
            if not subscription:
                # 초기 갱신일 설정 - timezone 정보 포함
                initial_renewal_date = get_kr_time() + timedelta(days=30)
                
                subscription = Subscription(
                    user_id=str(user.id),
                    plan=SubscriptionPlan.FREE,
                    status="active",
                    start_date=get_kr_time(),
                    renewal_date=initial_renewal_date,
                    message_limit=15
                )
                db.add(subscription)
        
        db.commit()
        
    except Exception as e:
        logger.error(f"Error during database initialization: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    init_db()
