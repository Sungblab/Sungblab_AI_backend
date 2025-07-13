from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from sqlalchemy import text
from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.crud import crud_user
from app.schemas.auth import UserCreate
from app.core.config import settings
from app.models.subscription import Subscription, SubscriptionPlan, PLAN_LIMITS
from datetime import datetime, timedelta, timezone
from app.models.user import User
import logging
import time

logger = logging.getLogger(__name__)

def init_db() -> None:
    # 데이터베이스 연결 재시도 로직
    max_retries = 5
    for attempt in range(max_retries):
        try:
            # 데이터베이스 테이블 생성
            Base.metadata.create_all(bind=engine)
            
            # 기존 테이블에 누락된 컬럼 추가
            with engine.connect() as conn:
                # similarity_threshold 컬럼이 없으면 추가
                try:
                    result = conn.execute(text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'project_embeddings' AND column_name = 'similarity_threshold'"
                    ))
                    if not result.fetchone():
                        conn.execute(text(
                            "ALTER TABLE project_embeddings ADD COLUMN similarity_threshold FLOAT DEFAULT NULL"
                        ))
                        conn.commit()
                        logger.info("Added similarity_threshold column to project_embeddings table")
                except Exception as e:
                    logger.warning(f"Could not check/add similarity_threshold column: {e}")
                
                # email_verifications 테이블에 id 컬럼이 없으면 추가
                try:
                    result = conn.execute(text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'email_verifications' AND column_name = 'id'"
                    ))
                    if not result.fetchone():
                        # id 컬럼 추가
                        conn.execute(text(
                            "ALTER TABLE email_verifications ADD COLUMN id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()"
                        ))
                        conn.commit()
                        logger.info("Added id column to email_verifications table")
                        
                        # 기존 데이터에 UUID 할당
                        conn.execute(text(
                            "UPDATE email_verifications SET id = gen_random_uuid() WHERE id IS NULL"
                        ))
                        conn.commit()
                        logger.info("Updated existing records with UUID values")
                    else:
                        logger.info("id column already exists in email_verifications table")
                except Exception as e:
                    logger.warning(f"Could not check/add id column to email_verifications: {e}")
            
            break
        except OperationalError as e:
            if "too many clients already" in str(e):
                logger.warning(f"Database connection failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(5 * (attempt + 1))  # 지수 백오프
                    continue
                else:
                    logger.error("Failed to create database tables after all retries")
                    return
            else:
                raise e

    # 데이터베이스 세션 생성 및 데이터 초기화
    db = None
    for attempt in range(max_retries):
        try:
            db = SessionLocal()
            # 관리자 계정이 이미 존재하는지 확인
            try:
                existing_admin = crud_user.get_user_by_email(db, email=settings.ADMIN_EMAIL)
            except Exception as e:
                logger.warning(f"Error checking for existing admin: {e}. Assuming no admin exists yet.")
                existing_admin = None
            
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
                    initial_renewal_date = datetime.now(timezone.utc) + timedelta(days=30)
                    
                    subscription = Subscription(
                        user_id=str(user.id),
                        plan=SubscriptionPlan.FREE,
                        status="active",
                        start_date=datetime.now(timezone.utc),
                        renewal_date=initial_renewal_date
                    )
                    db.add(subscription)
            
            db.commit()
            logger.info("Database initialization completed successfully")
            break
            
        except OperationalError as e:
            if "too many clients already" in str(e):
                logger.warning(f"Database initialization failed (attempt {attempt + 1}/{max_retries}): {e}")
                if db:
                    db.rollback()
                    db.close()
                    db = None
                if attempt < max_retries - 1:
                    time.sleep(5 * (attempt + 1))  # 지수 백오프
                    continue
                else:
                    logger.error("Failed to initialize database after all retries")
                    return
            else:
                logger.error(f"Database error during initialization: {e}")
                if db:
                    db.rollback()
                break
        except Exception as e:
            logger.error(f"Unexpected error during database initialization: {e}")
            if db:
                db.rollback()
            break
        finally:
            if db:
                db.close()

if __name__ == "__main__":
    init_db()
