"""
통합 보안 모듈: 인증, 인가, 입력 검증, 레이트 리미팅, 위협 탐지
"""
import re
import time
import json
import logging
import hashlib
import asyncio
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Set, Tuple
from enum import Enum

import bcrypt
import bleach
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request, UploadFile
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings
from app.core.cache import cache_manager

from app.core.exceptions import (
    ValidationError, RateLimitError, AuthenticationError,
    ErrorCode, ErrorSeverity
)

# --- 기본 인증 및 JWT 설정 (기존 security.py) ---

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """일반 비밀번호와 해시된 비밀번호를 비교합니다."""
    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    """비밀번호를 해시 처리합니다."""
    try:
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')
    except Exception as e:
        raise e

def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    """액세스 토큰을 생성합니다."""
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode = {"exp": expire, "sub": str(subject)}
    return jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )

def create_refresh_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    """리프레시 토큰을 생성합니다."""
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )
    to_encode = {"exp": expire, "sub": str(subject), "type": "refresh"}
    return jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )

def verify_refresh_token(token: str) -> Optional[str]:
    """리프레시 토큰을 검증하고 사용자 ID를 반환합니다."""
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str = payload.get("sub")
        token_type: str = payload.get("type")
        
        if user_id is None or token_type != "refresh":
            return None
            
        return user_id
    except JWTError:
        return None

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """JWT 토큰을 검증하고 현재 사용자를 반환합니다."""
    from app.api.deps import get_db
    from app.crud.crud_user import get_user

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증에 실패했습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    db_generator = get_db()
    db = next(db_generator)
    try:
        user = get_user(db, id=user_id)
        if user is None:
            raise credentials_exception
        return user
    finally:
        db.close()

# --- 고도화된 보안 기능 (기존 security_enhanced.py) ---

security_logger = logging.getLogger("security")

class SecurityLevel(str, Enum):
    """보안 수준"""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class ThreatType(str, Enum):
    """위협 유형"""
    RATE_LIMIT_ABUSE = "RATE_LIMIT_ABUSE"
    SUSPICIOUS_PATTERN = "SUSPICIOUS_PATTERN"
    MALICIOUS_FILE = "MALICIOUS_FILE"
    SQL_INJECTION = "SQL_INJECTION"
    XSS_ATTEMPT = "XSS_ATTEMPT"
    BRUTE_FORCE = "BRUTE_FORCE"
    UNUSUAL_BEHAVIOR = "UNUSUAL_BEHAVIOR"

class InputValidator:
    """고도화된 입력 검증"""
    SQL_INJECTION_PATTERNS = [
        r"(\bUNION\b.*\bSELECT\b)", r"(\bSELECT\b.*\bFROM\b.*\bWHERE\b)",
        r"(\bINSERT\b.*\bINTO\b)", r"(\bUPDATE\b.*\bSET\b)", r"(\bDELETE\b.*\bFROM\b)",
        r"(\bDROP\b.*\bTABLE\b)", r"(\bALTER\b.*\bTABLE\b)", r"(\bEXEC\b|\bEXECUTE\b)",
        r"(\bSP_\w+)", r"(\bXP_\w+)", r"('.*OR.*'=')", r"('.*AND.*'=')",
        r"(\-\-|\#|\/\*|\*\/)"
    ]
    XSS_PATTERNS = [
        r"<script[^>]*>.*?</script>", r"<iframe[^>]*>.*?</iframe>",
        r"<object[^>]*>.*?</object>", r"<embed[^>]*>", r"javascript:",
        r"vbscript:", r"on\w+\s*=", r"expression\s*\(",
        r"<meta[^>]*http-equiv", r"<link[^>]*rel.*stylesheet",
    ]
    MALICIOUS_FILE_PATTERNS = [
        r"\.exe$", r"\.bat$", r"\.cmd$", r"\.com$", r"\.scr$", r"\.pif$",
        r"\.msi$", r"\.dll$", r"\.vbs$", r"\.js$", r"\.jar$", r"\.sh$",
        r"\.php$", r"\.asp$", r"\.jsp$"
    ]

    @staticmethod
    def validate_text_input(
        text: str, max_length: int = 10000, allow_html: bool = False,
        check_sql_injection: bool = True, check_xss: bool = True
    ) -> Tuple[str, List[Dict[str, str]]]:
        """텍스트 입력 검증"""
        violations = []
        if len(text) > max_length:
            violations.append({"type": "LENGTH_EXCEEDED", "message": f"Text too long: {len(text)} > {max_length}", "severity": SecurityLevel.MEDIUM})
        
        if check_sql_injection:
            for pattern in InputValidator.SQL_INJECTION_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    violations.append({"type": ThreatType.SQL_INJECTION, "message": f"Potential SQL injection detected: {pattern}", "severity": SecurityLevel.HIGH})
                    security_logger.warning("sql_injection_attempt", {"pattern": pattern, "text_sample": text[:100]})
        
        if check_xss:
            for pattern in InputValidator.XSS_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    violations.append({"type": ThreatType.XSS_ATTEMPT, "message": f"Potential XSS detected: {pattern}", "severity": SecurityLevel.HIGH})
                    security_logger.warning("xss_attempt", {"pattern": pattern, "text_sample": text[:100]})
        
        if not allow_html:
            cleaned_text = bleach.clean(text, tags=[], attributes={}, strip=True)
        else:
            allowed_tags = ['p', 'br', 'strong', 'em', 'u', 'ol', 'ul', 'li']
            cleaned_text = bleach.clean(text, tags=allowed_tags, attributes={}, strip=True)
        
        return cleaned_text, violations

    @staticmethod
    def validate_file_upload(file: UploadFile) -> Tuple[bool, List[Dict[str, str]]]:
        """파일 업로드 검증"""
        violations = []
        if not file.filename:
            violations.append({"type": "INVALID_FILENAME", "message": "Filename is required", "severity": SecurityLevel.MEDIUM})
            return False, violations
        
        filename_lower = file.filename.lower()
        for pattern in InputValidator.MALICIOUS_FILE_PATTERNS:
            if re.search(pattern, filename_lower):
                violations.append({"type": ThreatType.MALICIOUS_FILE, "message": f"Dangerous file extension: {file.filename}", "severity": SecurityLevel.CRITICAL})
                security_logger.error("malicious_file_upload_attempt", {"filename": file.filename, "content_type": file.content_type})
        
        max_size = 32 * 1024 * 1024
        if file.size and file.size > max_size:
            violations.append({"type": "FILE_TOO_LARGE", "message": f"File too large: {file.size} > {max_size}", "severity": SecurityLevel.MEDIUM})
        
        allowed_mime_types = {
            'text/plain', 'text/csv', 'text/markdown', 'application/pdf', 'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'image/jpeg', 'image/png', 'image/gif', 'image/webp'
        }
        if file.content_type not in allowed_mime_types:
            violations.append({"type": "INVALID_MIME_TYPE", "message": f"Unsupported file type: {file.content_type}", "severity": SecurityLevel.MEDIUM})
        
        has_critical_violations = any(v["severity"] == SecurityLevel.CRITICAL for v in violations)
        return not has_critical_violations, violations

    @staticmethod
    def validate_api_key(api_key: str) -> bool:
        """API 키 형식 검증"""
        return bool(re.match(r'^[a-zA-Z0-9\-_]{32,}$', api_key))

    @staticmethod
    def validate_user_input(data: Dict[str, Any]) -> Dict[str, Any]:
        """사용자 입력 데이터 종합 검증"""
        violations = []
        cleaned_data = {}
        for key, value in data.items():
            if isinstance(value, str):
                cleaned_value, field_violations = InputValidator.validate_text_input(value)
                cleaned_data[key] = cleaned_value
                violations.extend([{**v, "field": key} for v in field_violations])
            else:
                cleaned_data[key] = value
        
        critical_violations = [v for v in violations if v.get("severity") == SecurityLevel.HIGH]
        if critical_violations:
            raise ValidationError(
                message="Security validation failed",
                field_errors=[{"field": v.get("field", "unknown"), "message": v["message"], "type": v["type"]} for v in critical_violations]
            )
        return cleaned_data

class RedisRateLimiter:
    """Redis 기반 고도화된 레이트 리미팅"""
    def __init__(self):
        self.redis_client = cache_manager.redis_client
        self.api_limits = {
            "default": {"requests": 60, "window": 60},
            "ai_chat": {"requests": 20, "window": 60},
            "ai_embedding": {"requests": 10, "window": 60},
            "file_upload": {"requests": 5, "window": 300},
            "auth_login": {"requests": 5, "window": 300},
            "auth_register": {"requests": 3, "window": 3600},
            "admin": {"requests": 100, "window": 60},
        }
        self.user_multipliers = {"anonymous": 0.5, "authenticated": 1.0, "premium": 2.0, "admin": 5.0}

    async def check_rate_limit(self, client_id: str, api_type: str = "default", user_type: str = "anonymous") -> Tuple[bool, Dict[str, Any]]:
        """레이트 리미팅 검사"""
        base_limits = self.api_limits.get(api_type, self.api_limits["default"])
        multiplier = self.user_multipliers.get(user_type, 1.0)
        requests_limit = int(base_limits["requests"] * multiplier)
        window_seconds = base_limits["window"]
        redis_key = f"rate_limit:{api_type}:{client_id}"
        
        try:
            now = int(time.time())
            window_start = now - window_seconds
            pipe = self.redis_client.pipeline()
            pipe.zremrangebyscore(redis_key, 0, window_start)
            pipe.zcard(redis_key)
            pipe.zadd(redis_key, {str(now): now})
            pipe.expire(redis_key, window_seconds + 10)
            results = pipe.execute()
            current_requests = results[1]
            
            if current_requests >= requests_limit:
                security_logger.warning("rate_limit_exceeded", {"client_id": client_id, "api_type": api_type, "user_type": user_type, "current_requests": current_requests, "limit": requests_limit, "window": window_seconds})
                return False, {"allowed": False, "current_requests": current_requests, "limit": requests_limit, "window": window_seconds, "retry_after": window_seconds}
            
            return True, {"allowed": True, "current_requests": current_requests + 1, "limit": requests_limit, "window": window_seconds, "remaining": requests_limit - current_requests - 1}
        except Exception as e:
            security_logger.error("rate_limit_check_failed", {"client_id": client_id, "api_type": api_type, "error": str(e)})
            return True, {"allowed": True, "error": "rate_limit_check_failed"}

    async def add_violation(self, client_id: str, violation_type: str, severity: SecurityLevel):
        """보안 위반 기록"""
        redis_key = f"security_violations:{client_id}"
        violation_data = {"type": violation_type, "severity": severity, "timestamp": time.time()}
        try:
            pipe = self.redis_client.pipeline()
            pipe.lpush(redis_key, json.dumps(violation_data))
            pipe.ltrim(redis_key, 0, 99)
            pipe.expire(redis_key, 86400)
            pipe.execute()
            security_logger.warning("security_violation_recorded", {"client_id": client_id, "violation_type": violation_type, "severity": severity})
        except Exception as e:
            security_logger.error("violation_recording_failed", {"client_id": client_id, "error": str(e)})

    async def get_violation_history(self, client_id: str) -> List[Dict[str, Any]]:
        """보안 위반 이력 조회"""
        redis_key = f"security_violations:{client_id}"
        try:
            violations_raw = self.redis_client.lrange(redis_key, 0, -1)
            return [json.loads(v) for v in violations_raw]
        except Exception as e:
            security_logger.error("violation_history_retrieval_failed", {"client_id": client_id, "error": str(e)})
            return []

    async def is_client_blocked(self, client_id: str) -> Tuple[bool, Optional[str]]:
        """클라이언트 차단 여부 확인"""
        violations = await self.get_violation_history(client_id)
        one_hour_ago = time.time() - 3600
        recent_violations = [v for v in violations if v.get("timestamp", 0) > one_hour_ago]
        
        if len([v for v in recent_violations if v.get("severity") == SecurityLevel.CRITICAL]) >= 1:
            return True, "Critical security violation detected"
        if len([v for v in recent_violations if v.get("severity") == SecurityLevel.HIGH]) >= 3:
            return True, "Multiple high-severity violations"
        if len(recent_violations) >= 10:
            return True, "Too many security violations"
        return False, None

class ThreatDetector:
    """위협 탐지 시스템"""
    def __init__(self):
        self.suspicious_patterns = {
            "rapid_requests": {"threshold": 100, "window": 60},
            "failed_logins": {"threshold": 5, "window": 300},
            "unusual_payload_size": {"min_size": 0, "max_size": 1024 * 1024},
            "suspicious_user_agents": ["curl", "wget", "python-requests", "bot", "crawler", "spider"]
        }

    async def analyze_request(self, request: Request, client_id: str) -> List[Dict[str, Any]]:
        """요청 위협 분석"""
        threats = []
        user_agent = request.headers.get("user-agent", "").lower()
        if any(pattern in user_agent for pattern in self.suspicious_patterns["suspicious_user_agents"]):
            threats.append({"type": ThreatType.SUSPICIOUS_PATTERN, "severity": SecurityLevel.LOW, "message": f"Suspicious user agent: {user_agent[:100]}", "details": {"user_agent": user_agent}})
        
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
                if size > self.suspicious_patterns["unusual_payload_size"]["max_size"]:
                    threats.append({"type": ThreatType.SUSPICIOUS_PATTERN, "severity": SecurityLevel.MEDIUM, "message": f"Unusually large payload: {size} bytes", "details": {"payload_size": size}})
            except ValueError: pass
        
        rapid_requests = await self._check_rapid_requests(client_id)
        if rapid_requests:
            threats.append({"type": ThreatType.RATE_LIMIT_ABUSE, "severity": SecurityLevel.HIGH, "message": "Rapid request pattern detected", "details": rapid_requests})
        
        return threats

    async def _check_rapid_requests(self, client_id: str) -> Optional[Dict[str, Any]]:
        """빠른 요청 패턴 감지"""
        redis_key = f"request_pattern:{client_id}"
        threshold = self.suspicious_patterns["rapid_requests"]["threshold"]
        window = self.suspicious_patterns["rapid_requests"]["window"]
        try:
            now = int(time.time())
            if cache_manager.redis_client.zcount(redis_key, now - window, now) > threshold:
                return {"request_count": cache_manager.redis_client.zcard(redis_key), "threshold": threshold, "window": window}
        except Exception as e:
            security_logger.error("rapid_request_check_failed", {"client_id": client_id, "error": str(e)})
        return None

class SecurityEnforcer:
    """보안 정책 적용"""
    def __init__(self):
        self.rate_limiter = RedisRateLimiter()
        self.threat_detector = ThreatDetector()
        self.input_validator = InputValidator()

    async def enforce_security(self, request: Request, client_id: str, api_type: str = "default", user_type: str = "anonymous") -> Tuple[bool, Dict[str, Any]]:
        """종합 보안 검사"""
        security_result = {"allowed": True, "violations": [], "rate_limit": {}, "threats": [], "actions_taken": []}
        try:
            is_blocked, block_reason = await self.rate_limiter.is_client_blocked(client_id)
            if is_blocked:
                security_result["allowed"] = False
                security_result["violations"].append({"type": "CLIENT_BLOCKED", "message": block_reason, "severity": SecurityLevel.CRITICAL})
                return False, security_result
            
            rate_allowed, rate_info = await self.rate_limiter.check_rate_limit(client_id, api_type, user_type)
            security_result["rate_limit"] = rate_info
            if not rate_allowed:
                security_result["allowed"] = False
                security_result["violations"].append({"type": ThreatType.RATE_LIMIT_ABUSE, "message": "Rate limit exceeded", "severity": SecurityLevel.MEDIUM})
                await self.rate_limiter.add_violation(client_id, ThreatType.RATE_LIMIT_ABUSE, SecurityLevel.MEDIUM)
                return False, security_result
            
            threats = await self.threat_detector.analyze_request(request, client_id)
            security_result["threats"] = threats
            for threat in threats:
                if threat["severity"] in [SecurityLevel.HIGH, SecurityLevel.CRITICAL]:
                    await self.rate_limiter.add_violation(client_id, threat["type"], threat["severity"])
                    security_result["actions_taken"].append(f"Recorded {threat['type']} violation")
            
            return True, security_result
        except Exception as e:
            security_logger.error("Security enforcement failed", extra={"extra_info": {"client_id": client_id, "api_type": api_type, "error": str(e)}})
            return True, {"allowed": True, "error": "security_check_failed"}

def get_client_ip(request: Request) -> str:
    """클라이언트 IP 주소 가져오기 (X-Forwarded-For 헤더 고려)"""
    x_forwarded_for = request.headers.get('x-forwarded-for')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.client.host

def require_security_check(api_type: str = "default"):
    """보안 검사 데코레이터"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            request = kwargs.get("request")
            if not isinstance(request, Request):
                return await func(*args, **kwargs)
            
            client_id = get_client_ip(request)
            # user 정보가 있으면 user_id를 client_id로 사용
            # user = kwargs.get("current_user")
            # if user:
            #     client_id = str(user.id)

            allowed, security_result = await security_enforcer.enforce_security(request, client_id, api_type)
            if not allowed:
                raise RateLimitError(message="Security check failed", retry_after=security_result.get("rate_limit", {}).get("retry_after"))
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator

class SecurityHeadersMiddleware:
    """보안 헤더 추가 미들웨어"""
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message['type'] == 'http.response.start':
                headers = message.get('headers', [])
                security_headers = [
                    (b'X-Content-Type-Options', b'nosniff'),
                    (b'X-Frame-Options', b'DENY'),
                    (b'X-XSS-Protection', b'1; mode=block'),
                    (b'Strict-Transport-Security', b'max-age=31536000; includeSubDomains'),
                    (b'Content-Security-Policy', b"default-src 'self'; script-src 'self'; object-src 'none';"),
                    (b'Referrer-Policy', b'strict-origin-when-cross-origin'),
                ]
                existing_headers = {h[0].lower() for h in headers}
                for name, value in security_headers:
                    if name.lower() not in existing_headers:
                        headers.append((name, value))
                message['headers'] = headers
            await send(message)
        
        await self.app(scope, receive, send_wrapper)

# --- 전역 인스턴스 및 헬퍼 함수 ---
security_enforcer = SecurityEnforcer()
input_validator = InputValidator()
rate_limiter = RedisRateLimiter()
threat_detector = ThreatDetector()

def generate_secure_token(length: int = 32) -> str:
    """암호학적으로 안전한 토큰 생성"""
    return secrets.token_hex(length)

def hash_data(data: str) -> str:
    """데이터 해싱 (SHA-256)"""
    return hashlib.sha256(data.encode('utf-8')).hexdigest()

def verify_data_hash(data: str, hashed_data: str) -> bool:
    """해시 검증"""
    return hash_data(data) == hashed_data