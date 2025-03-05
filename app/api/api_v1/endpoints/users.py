from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user, get_password_hash, verify_password
from app.db.session import get_db
from app.schemas.auth import User
from app.api import deps
from app.models.subscription import Subscription
from app.models.user import User as UserModel
from app.crud import crud_user
from pydantic import BaseModel
from app.schemas.user import UserProfile, UserProfileUpdate
from app.schemas.subscription import SubscriptionInfo
from app.crud import crud_subscription
from app.core.utils import get_kr_time

router = APIRouter()

@router.get("/me", response_model=UserProfile)
def get_user_profile(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(get_current_user)
):
    """
    현재 로그인한 사용자의 프로필 정보를 조회합니다.
    """
    return current_user

@router.put("/me", response_model=UserProfile)
def update_user_profile(
    profile_update: UserProfileUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(get_current_user)
):
    """
    현재 로그인한 사용자의 프로필 정보를 업데이트합니다.
    """
    updated_user = crud_user.update_user(
        db, 
        user_id=str(current_user.id), 
        user_in=profile_update
    )
    return updated_user

@router.get("/me/subscription", response_model=SubscriptionInfo)
def get_user_subscription(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(get_current_user)
):
    """
    현재 로그인한 사용자의 구독 정보를 조회합니다.
    만료된 구독은 자동으로 갱신됩니다.
    """
    # 구독 정보 조회 (이 함수 내에서 만료된 구독은 자동 갱신됨)
    subscription = crud_subscription.get_subscription(db, str(current_user.id))
    if not subscription:
        raise HTTPException(status_code=404, detail="구독 정보를 찾을 수 없습니다.")
    
    # 현재 시간 기준으로 남은 일수 계산
    current_time = get_kr_time()
    remaining_days = (subscription.end_date - current_time).days
    
    return {
        "plan": subscription.plan,
        "start_date": subscription.start_date,
        "end_date": subscription.end_date,
        "remaining_days": max(0, remaining_days),  # 음수 방지
        "monthly_token_limit": subscription.monthly_token_limit,
        "remaining_tokens": subscription.remaining_tokens,
        "token_usage_percent": round((1 - subscription.remaining_tokens / subscription.monthly_token_limit) * 100, 1) if subscription.monthly_token_limit > 0 else 0
    }

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
        print(f"계정 삭제 중 오류 발생: {str(e)}")
        # 더 자세한 에러 정보 출력
        import traceback
        traceback.print_exc()
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
        import traceback
        traceback.print_exc()
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"비밀번호 변경 중 오류가 발생했습니다: {str(e)}"
        ) 