from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Body
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel
import logging

from app.core.config import settings
from app.core import security
from app.core.security import get_current_user
from app.core.oauth2 import verify_google_token
from app.db.session import get_db
from app.schemas.auth import Token, UserCreate, User, SocialLogin, GoogleUser
from app.crud import crud_user
from app.api import deps
from app.core.email import send_reset_password_email
from app.models.user import AuthProvider
from typing import Optional
import secrets

logger = logging.getLogger("sungblab_api")

router = APIRouter()

class LoginRequest(BaseModel):
    email: str
    password: str

@router.post("/signup", response_model=User)
def create_user(user_in: UserCreate, db: Session = Depends(get_db)):
    user = crud_user.get_user_by_email(db, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="이미 등록된 이메일입니다."
        )
    user = crud_user.create_user(db, obj_in=user_in)
    return user

@router.post("/login", response_model=Token)
def login(
    db: Session = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
):
    user = crud_user.authenticate(
        db, email=form_data.username, password=form_data.password
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        user.id, expires_delta=access_token_expires
    )
    return {
        "access_token": access_token,
        "token_type": "bearer"
    }

@router.post("/login-json", response_model=Token)
def login_json(
    login_data: LoginRequest,
    db: Session = Depends(get_db)
):
    user = crud_user.authenticate(
        db, email=login_data.email, password=login_data.password
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        user.id, expires_delta=access_token_expires
    )
    logger.debug(f"Access token created for user: {user.email}")
    return {
        "access_token": access_token,
        "token_type": "bearer"
    }

@router.get("/me", response_model=User)
def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user

@router.post("/find-id", response_model=dict)
def find_id(
    *,
    db: Session = Depends(deps.get_db),
    full_name: str,
) -> dict:
    """
    이름으로 아이디(이메일) 찾기
    """
    user = crud_user.get_user_by_name(db, full_name=full_name)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="해당 이름으로 등록된 계정을 찾을 수 없습니다."
        )
    
    # 이메일 일부를 마스킹 처리
    email_parts = user.email.split('@')
    masked_email = f"{email_parts[0][:3]}{'*' * (len(email_parts[0])-3)}@{email_parts[1]}"
    
    return {
        "email": masked_email
    }

@router.post("/request-password-reset", response_model=dict)
def request_password_reset(
    background_tasks: BackgroundTasks,
    *,
    db: Session = Depends(deps.get_db),
    email: str = Body(..., embed=True),
) -> dict:
    """
    비밀번호 재설정 이메일 전송
    """
    user = crud_user.get_user_by_email(db, email=email)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="해당 이메일로 등록된 계정을 찾을 수 없습니다."
        )
    
    # 비밀번호 재설정 토큰 생성
    reset_token = secrets.token_urlsafe(32)
    crud_user.update_password_reset_token(db, user=user, token=reset_token)
    
    # 이메일 전송 (비동기)
    background_tasks.add_task(
        send_reset_password_email,
        email_to=user.email,
        token=reset_token
    )
    
    return {
        "message": "비밀번호 재설정 링크가 이메일로 전송되었습니다."
    }

@router.post("/reset-password", response_model=dict)
def reset_password(
    *,
    db: Session = Depends(deps.get_db),
    token: str = Body(...),
    new_password: str = Body(...),
) -> dict:
    """
    비밀번호 재설정
    """
    user = crud_user.get_user_by_reset_token(db, token=token)
    if not user:
        raise HTTPException(
            status_code=400,
            detail="유효하지 않거나 만료된 토큰입니다."
        )
    
    crud_user.reset_password(db, user=user, new_password=new_password)
    return {
        "message": "비밀번호가 성공적으로 재설정되었습니다."
    }

@router.post("/social/google", response_model=Token)
async def google_auth(
    social_login: SocialLogin,
    db: Session = Depends(get_db)
):
    """구글 소셜 로그인"""
    try:
        google_user = await verify_google_token(social_login.access_token)
        if not google_user:
            raise HTTPException(
                status_code=400,
                detail="Google 인증에 실패했습니다."
            )

        # 기존 사용자 확인
        user = crud_user.get_user_by_email(db, email=google_user.email)
        
        if not user:
            # 새 사용자 생성
            user = crud_user.create_social_user(
                db,
                email=google_user.email,
                full_name=google_user.name,
                auth_provider=AuthProvider.GOOGLE,  # 직접 enum 값 사용
                social_id=google_user.sub,
                profile_image=google_user.picture
            )
        elif user.auth_provider != AuthProvider.GOOGLE:  # enum 비교
            raise HTTPException(
                status_code=400,
                detail=f"이미 {user.auth_provider.value} 계정으로 가입된 이메일입니다."
            )

        # 액세스 토큰 생성
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = security.create_access_token(
            user.id, expires_delta=access_token_expires
        )

        return {
            "access_token": access_token,
            "token_type": "bearer"
        }
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        ) 