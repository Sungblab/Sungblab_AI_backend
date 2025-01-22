from sqlalchemy.orm import Session
from app.models.base import Base
from app.db.session import engine, SessionLocal
from app.crud import crud_user
from app.schemas.auth import UserCreate
from app.core.config import settings
from app.models.subscription import Subscription, SubscriptionPlan
from datetime import datetime, timedelta
from app.models.user import User

def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    
    # 초기 관리자 계정 생성
    db = SessionLocal()
    try:
        # 관리자 계정이 이미 있는지 확인
        admin_email = settings.ADMIN_EMAIL  # 환경 변수에서 가져오기
        admin = crud_user.get_user_by_email(db, email=admin_email)
        
        if not admin and settings.CREATE_INITIAL_ADMIN:  # 환경 변수로 초기 관리자 생성 제어
            admin_in = UserCreate(
                email=admin_email,
                full_name=settings.ADMIN_NAME,  # 환경 변수에서 가져오기
                password=settings.ADMIN_INITIAL_PASSWORD  # 환경 변수에서 가져오기
            )
            admin = crud_user.create_user(db, obj_in=admin_in)
            # 관리자 권한 부여
            admin.is_superuser = True
            db.commit()
            print("관리자 계정이 생성되었습니다.")
        
        # 모든 사용자에 대해 기본 구독 정보 생성
        users = db.query(User).all()
        for user in users:
            subscription = db.query(Subscription).filter(
                Subscription.user_id == str(user.id)
            ).first()
            
            if not subscription:
                subscription = Subscription(
                    user_id=str(user.id),
                    plan=SubscriptionPlan.FREE,
                    status="active",
                    start_date=datetime.utcnow(),
                    renewal_date=datetime.utcnow() + timedelta(days=30),
                    message_limit=15
                )
                db.add(subscription)
        
        db.commit()
        
    finally:
        db.close()

if __name__ == "__main__":
    print("데이터베이스 초기화를 시작합니다...")
    init_db()
    print("데이터베이스 초기화가 완료되었습니다.") 