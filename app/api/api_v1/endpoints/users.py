from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import logging

from app.core.security import get_current_user, get_password_hash, verify_password
from app.db.session import get_db
from app.schemas.auth import User
from app.api import deps
from app.models.subscription import Subscription, SubscriptionPlan
from app.models.user import User as UserModel
from app.crud import crud_user
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/me", response_model=User)
def read_current_user(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    현재 로그인한 사용자의 정보를 반환합니다.
    """
    return current_user 

@router.get("/me/subscription", response_model=dict)
def get_my_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(deps.get_db)
):
    """현재 사용자의 구독 정보를 조회합니다."""
    subscription = db.query(Subscription).filter(
        Subscription.user_id == str(current_user.id)
    ).first()
    
    # 구독 정보가 없으면 기본 구독 정보 생성
    if not subscription:
        subscription = Subscription(
            user_id=str(current_user.id),
            plan=SubscriptionPlan.FREE,
            status="active",
            start_date=datetime.now(timezone.utc),
            end_date=datetime.now(timezone.utc) + timedelta(days=30),
            auto_renew=True,
            renewal_date=datetime.now(timezone.utc) + timedelta(days=30),
            group_usage={
                "basic_chat": 0,
                "normal_analysis": 0,
                "advanced_analysis": 0
            }
        )
        db.add(subscription)
        db.commit()
        db.refresh(subscription)
    
    return subscription.to_dict() 

@router.delete("/me", response_model=dict)
def delete_current_user(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(deps.get_db)
):
    """
    현재 로그인한 사용자의 계정을 삭제합니다. 토큰 사용량 데이터는 보존됩니다.
    """
    try:
        # crud_user를 통해 사용자 조회
        user = crud_user.get_user(db, id=current_user.id)
        if not user:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

        # 구독 정보에서 user_id만 None으로 설정하고 토큰 사용량은 보존
        subscription = db.query(Subscription).filter(
            Subscription.user_id == str(user.id)
        ).first()
        if subscription:
            subscription.user_id = None
            db.flush()

        # 사용자 삭제
        db.delete(user)
        db.commit()
        
        return {"message": "계정이 성공적으로 삭제되었습니다."}
    except Exception as e:
        db.rollback()
        logger.error(f"계정 삭제 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"계정 삭제 중 오류가 발생했습니다: {str(e)}"
        ) 

# 비밀번호 변경 요청 모델 추가
class PasswordChange(BaseModel):
    current_password: str
    new_password: str

@router.post("/me/change-password", response_model=dict)
def change_password(
    password_data: PasswordChange,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(deps.get_db)
):
    """
    현재 로그인한 사용자의 비밀번호를 변경합니다.
    """
    try:
        
        # 소셜 로그인 사용자는 비밀번호 변경 불가
        if current_user.auth_provider != "LOCAL":
            raise HTTPException(
                status_code=400,
                detail="소셜 로그인 사용자는 비밀번호를 변경할 수 없습니다."
            )

        # 현재 비밀번호 확인
        if not verify_password(password_data.current_password, current_user.hashed_password):
            raise HTTPException(
                status_code=400,
                detail="현재 비밀번호가 일치하지 않습니다."
            )

        # 새 비밀번호 해시화 및 저장
        user = crud_user.get_user(db, id=current_user.id)
        user.hashed_password = get_password_hash(password_data.new_password)
        db.commit()
        return {"message": "비밀번호가 성공적으로 변경되었습니다."}
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"비밀번호 변경 중 오류 발생: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"비밀번호 변경 중 오류가 발생했습니다: {str(e)}"
        ) 