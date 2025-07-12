from datetime import datetime, timedelta, timezone
import random
import string
from typing import Optional
from sqlalchemy.orm import Session
from app.models.email_verification import EmailVerification
import secrets

def generate_verification_code(length: int = 6) -> str:
    """숫자로 된 인증 코드 생성"""
    return ''.join(random.choices(string.digits, k=length))

def create_email_verification(db: Session, email: str) -> EmailVerification:
    """새로운 이메일 인증 코드 생성"""
    # 기존 인증 정보가 있다면 삭제
    db.query(EmailVerification).filter(EmailVerification.email == email).delete()
    
    # timezone-aware datetime 생성
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)  # 10분 유효
    
    verification = EmailVerification(
        email=email,
        verification_code=generate_verification_code(),
        expires_at=expires_at,
        is_verified=False
    )
    db.add(verification)
    db.commit()
    db.refresh(verification)
    return verification

def get_email_verification(db: Session, email: str) -> Optional[EmailVerification]:
    """이메일 인증 정보 조회"""
    return db.query(EmailVerification).filter(EmailVerification.email == email).first()

def verify_email_code(db: Session, email: str, code: str) -> bool:
    """이메일 인증 코드 확인"""
    verification = get_email_verification(db, email)
    
    if not verification:
        return False
    
    if verification.is_expired():
        return False
    
    if verification.verification_code != code:
        return False
    
    # 인증 성공 시 verified 상태로 변경
    verification.is_verified = True
    db.commit()
    return True

def is_email_verified(db: Session, email: str) -> bool:
    """이메일이 인증되었는지 확인"""
    verification = get_email_verification(db, email)
    return verification is not None and verification.is_verified 