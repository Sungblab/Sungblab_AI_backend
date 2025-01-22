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

router = APIRouter()

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
    
    if not subscription:
        raise HTTPException(
            status_code=404,
            detail="구독 정보를 찾을 수 없습니다."
        )
    
    return subscription.to_dict() 

@router.delete("/me", response_model=dict)
def delete_current_user(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(deps.get_db)
):
    """
    현재 로그인한 사용자의 계정을 삭제합니다.
    """
    try:
        # crud_user를 통해 사용자 조회
        user = crud_user.get_user(db, id=current_user.id)
        if not user:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

        # 구독 정보 삭제
        subscription = db.query(Subscription).filter(
            Subscription.user_id == str(user.id)
        ).first()
        if subscription:
            db.delete(subscription)
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
        print(f"Auth provider: {current_user.auth_provider}")
        
        # 소셜 로그인 사용자는 비밀번호 변경 불가
        if current_user.auth_provider != "LOCAL":
            raise HTTPException(
                status_code=400,
                detail="소셜 로그인 사용자는 비밀번호를 변경할 수 없습니다."
            )

        print("Verifying current password...")
        # 현재 비밀번호 확인
        if not verify_password(password_data.current_password, current_user.hashed_password):
            print("Current password verification failed")
            raise HTTPException(
                status_code=400,
                detail="현재 비밀번호가 일치하지 않습니다."
            )

        print("Updating password...")
        # 새 비밀번호 해시화 및 저장
        user = crud_user.get_user(db, id=current_user.id)
        user.hashed_password = get_password_hash(password_data.new_password)
        db.commit()
        return {"message": "비밀번호가 성공적으로 변경되었습니다."}
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Unexpected error in change_password: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"비밀번호 변경 중 오류가 발생했습니다: {str(e)}"
        ) 