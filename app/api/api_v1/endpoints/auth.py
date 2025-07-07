from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Body, Form
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from app.core.config import settings
from app.core import security
from app.core.security import get_current_user
from app.core.oauth2 import verify_google_token
from app.db.session import get_db
from app.schemas.auth import Token, UserCreate, User, SocialLogin, GoogleUser
from app.crud import crud_user, crud_email_verification
from app.api import deps
from app.core.email import send_reset_password_email, send_verification_email
from app.models.user import AuthProvider
from typing import Optional
import secrets

router = APIRouter()

class LoginRequest(BaseModel):
    email: str
    password: str
    remember_me: bool = False

class EmailVerificationRequest(BaseModel):
    email: EmailStr

class EmailVerificationCodeRequest(BaseModel):
    email: EmailStr
    verification_code: str

@router.post("/signup", response_model=User, summary="사용자 회원가입")
def create_user(user_in: UserCreate, db: Session = Depends(get_db)):
    """
    새로운 사용자 회원가입
    
    - **email**: 사용자 이메일 주소 (필수, 이메일 인증 완료 필요)
    - **password**: 비밀번호 (필수, 최소 8자 이상)
    - **full_name**: 사용자 이름 (필수)
    - **is_student**: 학생 여부 (선택)
    
    **주의사항:**
    - 이메일 인증이 완료된 이메일만 회원가입 가능
    - 이미 가입된 이메일로는 재가입 불가
    
    **응답:**
    - 생성된 사용자 정보 반환
    """
    # 이미 가입된 이메일인지 확인
    user = crud_user.get_user_by_email(db, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="이미 가입된 이메일입니다.",
        )
    
    # 이메일 인증 여부 확인
    if not crud_email_verification.is_email_verified(db, user_in.email):
        raise HTTPException(
            status_code=400,
            detail="이메일 인증이 필요합니다.",
        )
    
    try:
        user = crud_user.create_user(db, obj_in=user_in)
        return user
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

@router.post("/login", response_model=Token, summary="사용자 로그인 (Form 방식)")
def login(
    db: Session = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
    remember_me: bool = Form(False)
):
    """
    사용자 로그인 (OAuth2 Form 방식)
    
    - **username**: 사용자 이메일 주소
    - **password**: 비밀번호
    - **remember_me**: 로그인 유지 여부 (선택, 기본값: False)
    
    **토큰 만료 시간:**
    - 일반 로그인: 24시간
    - 로그인 유지 선택시: 30일
    
    **응답:**
    - access_token: JWT 토큰
    - token_type: "bearer"
    - expires_in: 토큰 만료 시간 (초 단위)
    """
    user = crud_user.authenticate(
        db, email=form_data.username, password=form_data.password
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # remember_me 값에 따라 토큰 만료 시간 설정
    if remember_me:
        # 장기 토큰 (30일)
        access_token_expires = timedelta(days=30)
    else:
        # 기본 토큰 (1일)
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    access_token = security.create_access_token(
        user.id, expires_delta=access_token_expires
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": int(access_token_expires.total_seconds())  # 만료 시간을 초 단위로 반환
    }

@router.post("/login-json", response_model=Token, summary="사용자 로그인 (JSON 방식)")
def login_json(
    login_data: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    사용자 로그인 (JSON 방식)
    
    - **email**: 사용자 이메일 주소
    - **password**: 비밀번호
    - **remember_me**: 로그인 유지 여부 (선택, 기본값: False)
    
    **토큰 만료 시간:**
    - 일반 로그인: 24시간
    - 로그인 유지 선택시: 30일
    
    **응답:**
    - access_token: JWT 토큰
    - token_type: "bearer"
    - expires_in: 토큰 만료 시간 (초 단위)
    
    **예시:**
    ```json
    {
        "email": "user@example.com",
        "password": "password123",
        "remember_me": false
    }
    ```
    """
    user = crud_user.authenticate(
        db, email=login_data.email, password=login_data.password
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # remember_me 값에 따라 토큰 만료 시간 설정
    if login_data.remember_me:
        # 장기 토큰 (30일)
        access_token_expires = timedelta(days=30)
    else:
        # 기본 토큰 (1일)
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    access_token = security.create_access_token(
        user.id, expires_delta=access_token_expires
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": int(access_token_expires.total_seconds())  # 만료 시간을 초 단위로 반환
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

        # 소셜 로그인은 항상 30일 토큰 발급
        access_token_expires = timedelta(days=30)

        # 액세스 토큰 생성
        access_token = security.create_access_token(
            user.id, expires_delta=access_token_expires
        )

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": int(access_token_expires.total_seconds())  # 만료 시간을 초 단위로 반환
        }
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

@router.post("/send-verification", response_model=dict)
def send_verification(
    request: EmailVerificationRequest,
    db: Session = Depends(deps.get_db),
) -> dict:
    """
    회원가입을 위한 이메일 인증 코드 전송
    """
    # 이미 가입된 이메일인지 확인
    user = crud_user.get_user_by_email(db, email=request.email)
    if user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 가입된 이메일입니다.",
        )
    
    # 인증 코드 생성 및 저장
    verification = crud_email_verification.create_email_verification(db, request.email)
    
    # 이메일 전송
    send_verification_email(request.email, verification.verification_code)
    
    return {"message": "인증 코드가 이메일로 전송되었습니다."}

@router.post("/verify-email", response_model=dict)
def verify_email(
    request: EmailVerificationCodeRequest,
    db: Session = Depends(deps.get_db),
) -> dict:
    """
    이메일 인증 코드 확인
    """
    if not crud_email_verification.verify_email_code(db, request.email, request.verification_code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="잘못된 인증 코드이거나 만료되었습니다.",
        )
    
    return {"message": "이메일 인증이 완료되었습니다."} 