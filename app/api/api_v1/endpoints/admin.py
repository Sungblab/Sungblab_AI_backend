from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.api import deps
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.admin import UserResponse, UserUpdate, AdminOverviewResponse
from app.crud import crud_user, crud_admin
from app.crud import crud_project
from app.crud import crud_subscription
from app.models.subscription import Subscription, SubscriptionPlan, KST
from datetime import datetime, timedelta
from pydantic import BaseModel
from app.core.utils import get_kr_time

router = APIRouter()

def get_current_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="관리자 권한이 필요합니다."
        )
    return current_user

@router.get("/users", response_model=List[UserResponse])
def get_users(
    db: Session = Depends(deps.get_db),
    _: User = Depends(get_current_admin),
    skip: int = 0,
    limit: int = 100
):
    """
    모든 사용자 목록을 조회합니다.
    """
    users = crud_user.get_users(db, skip=skip, limit=limit)
    return users

@router.patch("/users/{user_id}/admin-status")
def toggle_admin_status(
    user_id: str,
    db: Session = Depends(deps.get_db),
    _: User = Depends(get_current_admin)
):
    """
    사용자의 관리자 권한을 토글합니다.
    """
    user = crud_user.get_user(db, id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    
    # 자기 자신의 관리자 권한은 변경할 수 없음
    if user.id == _.id:
        raise HTTPException(status_code=400, detail="자신의 관리자 권한은 변경할 수 없습니다.")
    
    user.is_superuser = not user.is_superuser
    db.commit()
    return {"is_admin": user.is_superuser}

@router.patch("/users/{user_id}/status")
def toggle_user_status(
    user_id: str,
    db: Session = Depends(deps.get_db),
    _: User = Depends(get_current_admin)
):
    """
    사용자의 활성화 상태를 토글합니다.
    """
    user = crud_user.get_user(db, id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    
    # 자기 자신은 비활성화할 수 없음
    if user.id == _.id:
        raise HTTPException(status_code=400, detail="자신의 계정은 비활성화할 수 없습니다.")
    
    user.is_active = not user.is_active
    db.commit()
    return {"is_active": user.is_active}

@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    db: Session = Depends(deps.get_db),
    _: User = Depends(get_current_admin)
):
    """
    사용자를 삭제합니다. 토큰 사용량 데이터는 보존됩니다.
    """
    try:
        user = crud_user.get_user(db, id=user_id)
        if not user:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
        
        # 자기 자신은 삭제할 수 없음
        if user.id == _.id:
            raise HTTPException(status_code=400, detail="자신의 계정은 삭제할 수 없습니다.")
        
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
        return {"message": "사용자가 삭제되었습니다."}
    except Exception as e:
        db.rollback()
        print(f"사용자 삭제 중 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"사용자 삭제 중 오류가 발생했습니다: {str(e)}"
        )

@router.get("/subscriptions", response_model=List[dict])
def get_subscriptions(
    db: Session = Depends(deps.get_db),
    _: User = Depends(get_current_admin)
):
    """모든 구독 정보를 조회합니다."""
    subscriptions = db.query(Subscription).all()
    return [sub.to_dict() for sub in subscriptions]

# 요청 데이터 모델 추가
class SubscriptionUpdate(BaseModel):
    plan: SubscriptionPlan
    update_limits: bool = True

@router.patch("/subscriptions/{user_id}")
def update_subscription(
    user_id: str,
    update_data: SubscriptionUpdate,
    db: Session = Depends(deps.get_db),
    _: User = Depends(get_current_admin)
):
    """사용자의 구독 플랜을 변경합니다."""
    updated_subscription = crud_subscription.update_subscription_plan(
        db=db,
        user_id=user_id,
        plan=update_data.plan,
        update_limits=update_data.update_limits
    )
    
    if not updated_subscription:
        raise HTTPException(status_code=404, detail="구독 정보를 찾을 수 없습니다.")
    
    return updated_subscription.to_dict()

@router.post("/users/{user_id}/reset-usage")
def reset_usage(
    user_id: str,
    db: Session = Depends(deps.get_db),
    _: User = Depends(get_current_admin)
):
    """사용자의 사용량을 초기화합니다."""
    updated_subscription = crud_subscription.reset_usage(db=db, user_id=user_id)
    if not updated_subscription:
        raise HTTPException(status_code=404, detail="구독 정보를 찾을 수 없습니다.")
    
    return updated_subscription.to_dict()

@router.get("/overview", response_model=AdminOverviewResponse)
def get_admin_overview(
    db: Session = Depends(deps.get_db),
    current_admin: User = Depends(get_current_admin)
):
    """
    관리자 대시보드의 Overview 데이터를 반환합니다.
    """
    try:
        # 사용자 통계
        user_stats = crud_admin.get_user_stats(db)
        
        # 구독 통계
        subscription_stats = crud_admin.get_subscription_stats(db)
        
        # 최근 가입자
        recent_users = crud_admin.get_recent_users(db)
        
        # AI 모델 사용량
        model_usage_stats = crud_admin.get_model_usage_stats(db)
        
        return {
            "user_stats": user_stats,
            "subscription_stats": subscription_stats,
            "recent_users": recent_users,
            "model_usage_stats": model_usage_stats
        }
        
    except Exception as e:
        print(f"Overview 데이터 조회 중 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Overview 데이터를 불러오는데 실패했습니다: {str(e)}"
        ) 