from typing import Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.core.utils import get_kr_time

from app.core.security import get_password_hash, verify_password
from app.models.user import User, AuthProvider
from app.models.subscription import Subscription, SubscriptionPlan
from app.schemas.auth import UserCreate
from app.schemas.admin import UserUpdate

def get_user(db: Session, id: str) -> Optional[User]:
    return db.query(User).filter(User.id == id).first()

def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()

def get_user_by_name(db: Session, full_name: str) -> Optional[User]:
    return db.query(User).filter(User.full_name == full_name).first()

def get_user_by_reset_token(db: Session, token: str) -> Optional[User]:
    return db.query(User).filter(
        User.reset_password_token == token,
        User.reset_password_token_expires > get_kr_time()
    ).first()

def create_user(db: Session, *, obj_in: UserCreate) -> User:
    hashed_password = get_password_hash(obj_in.password)
    db_user = User(
        email=obj_in.email,
        full_name=obj_in.full_name,
        hashed_password=hashed_password,
        auth_provider=AuthProvider.LOCAL,
        is_active=True
    )
    db.add(db_user)
    db.flush()  # 사용자 ID를 얻기 위해 flush

    # 기본 구독 정보 생성 (새로운 그룹 기반 시스템)
    subscription = Subscription(
        user_id=db_user.id,
        plan=SubscriptionPlan.FREE,
        status="active",
        start_date=get_kr_time(),
        end_date=get_kr_time() + timedelta(days=30),
        auto_renew=True,
        renewal_date=get_kr_time() + timedelta(days=30),
        group_usage={
            "basic_chat": 0,
            "normal_analysis": 0,
            "advanced_analysis": 0
        }
    )
    db.add(subscription)
    
    db.commit()
    db.refresh(db_user)
    return db_user

def update_password_reset_token(db: Session, user: User, token: str) -> User:
    user.reset_password_token = token
    user.reset_password_token_expires = get_kr_time() + timedelta(hours=24)
    db.commit()
    db.refresh(user)
    return user

def reset_password(db: Session, user: User, new_password: str) -> User:
    user.hashed_password = get_password_hash(new_password)
    user.reset_password_token = None
    user.reset_password_token_expires = None
    db.commit()
    db.refresh(user)
    return user

def authenticate(db: Session, email: str, password: str) -> Optional[User]:
    user = get_user_by_email(db, email=email)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user

def create_social_user(
    db: Session,
    *,
    email: str,
    full_name: str,
    auth_provider: AuthProvider,
    social_id: str,
    profile_image: Optional[str] = None
) -> User:
    """
    소셜 로그인 사용자 생성
    """
    db_user = User(
        email=email,
        full_name=full_name,
        auth_provider=auth_provider,
        social_id=social_id,
        profile_image=profile_image,
        is_active=True
    )
    db.add(db_user)
    db.flush()  # 사용자 ID를 얻기 위해 flush

    # 기본 구독 정보 생성 (새로운 그룹 기반 시스템)
    subscription = Subscription(
        user_id=db_user.id,
        plan=SubscriptionPlan.FREE,
        status="active",
        start_date=get_kr_time(),
        end_date=get_kr_time() + timedelta(days=30),
        auto_renew=True,
        renewal_date=get_kr_time() + timedelta(days=30),
        group_usage={
            "basic_chat": 0,
            "normal_analysis": 0,
            "advanced_analysis": 0
        }
    )
    db.add(subscription)
    
    db.commit()
    db.refresh(db_user)
    return db_user

def get_users(db: Session, skip: int = 0, limit: int = 100):
    """
    모든 사용자 목록을 조회합니다.
    """
    return db.query(User).offset(skip).limit(limit).all()

def update_user(db: Session, *, user: User, obj_in: UserUpdate) -> User:
    """
    사용자 정보를 업데이트합니다.
    """
    update_data = obj_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user 