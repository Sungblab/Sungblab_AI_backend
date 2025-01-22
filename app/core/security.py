from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
import bcrypt  # bcrypt 직접 사용
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings
from app.db.session import get_db

# pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        print(f"Verifying password... (hashed length: {len(hashed_password)})")
        result = bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
        print(f"Password verification result: {result}")
        return result
    except Exception as e:
        print(f"Password verification error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def get_password_hash(password: str) -> str:
    try:
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        result = hashed.decode('utf-8')
        print(f"Generated hash length: {len(result)}")
        return result
    except Exception as e:
        print(f"Password hashing error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise e

def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme), db = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증에 실패했습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        print(f"Received token: {token}")
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError as e:
        print(f"JWT Error: {str(e)}")
        raise credentials_exception
    
    from app.crud.crud_user import get_user
    user = get_user(db, id=user_id)  # String ID 사용
    if user is None:
        raise credentials_exception
    return user 