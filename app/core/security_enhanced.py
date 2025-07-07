"""
고도화된 보안 시스템
입력 검증, Redis 기반 레이트 리미팅, 의심스러운 활동 탐지
"""

import re
import time
import json
import hashlib
import asyncio
from typing import Dict, List, Optional, Any, Set, Tuple
from datetime import datetime, timedelta
from fastapi import Request, UploadFile, HTTPException
from pydantic import BaseModel, validator
from enum import Enum
import bleach
import secrets

from app.core.cache import cache_manager
from app.core.structured_logging import StructuredLogger
from app.core.exceptions import (
    ValidationError, RateLimitError, AuthenticationError,
    ErrorCode, ErrorSeverity
)

# 보안 로거
security_logger = StructuredLogger("security")

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
    
    # 위험한 패턴들
    SQL_INJECTION_PATTERNS = [
        r"(\bUNION\b.*\bSELECT\b)",
        r"(\bSELECT\b.*\bFROM\b.*\bWHERE\b)",
        r"(\bINSERT\b.*\bINTO\b)",
        r"(\bUPDATE\b.*\bSET\b)",
        r"(\bDELETE\b.*\bFROM\b)",
        r"(\bDROP\b.*\bTABLE\b)",
        r"(\bALTER\b.*\bTABLE\b)",
        r"(\bEXEC\b|\bEXECUTE\b)",
        r"(\bSP_\w+)",
        r"(\bXP_\w+)",
        r"('.*OR.*'=')",
        r"('.*AND.*'=')",
        r"(\-\-|\#|\/\*|\*\/)"
    ]
    
    XSS_PATTERNS = [
        r"<script[^>]*>.*?</script>",
        r"<iframe[^>]*>.*?</iframe>",
        r"<object[^>]*>.*?</object>",
        r"<embed[^>]*>",
        r"javascript:",
        r"vbscript:",
        r"on\w+\s*=",
        r"expression\s*\(",
        r"<meta[^>]*http-equiv",
        r"<link[^>]*rel.*stylesheet",
    ]
    
    MALICIOUS_FILE_PATTERNS = [
        r"\.exe$", r"\.bat$", r"\.cmd$", r"\.com$", r"\.scr$",
        r"\.pif$", r"\.msi$", r"\.dll$", r"\.vbs$", r"\.js$",
        r"\.jar$", r"\.sh$", r"\.php$", r"\.asp$", r"\.jsp$"
    ]
    
    @staticmethod
    def validate_text_input(
        text: str, 
        max_length: int = 10000,
        allow_html: bool = False,
        check_sql_injection: bool = True,
        check_xss: bool = True
    ) -> Tuple[str, List[Dict[str, str]]]:
        """텍스트 입력 검증"""
        
        violations = []
        
        # 길이 검증
        if len(text) > max_length:
            violations.append({
                "type": "LENGTH_EXCEEDED",
                "message": f"Text too long: {len(text)} > {max_length}",
                "severity": SecurityLevel.MEDIUM
            })
        
        # SQL 인젝션 검사
        if check_sql_injection:
            for pattern in InputValidator.SQL_INJECTION_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    violations.append({
                        "type": ThreatType.SQL_INJECTION,
                        "message": f"Potential SQL injection detected: {pattern}",
                        "severity": SecurityLevel.HIGH
                    })
                    security_logger.warning("sql_injection_attempt", {
                        "pattern": pattern,
                        "text_sample": text[:100]
                    })
        
        # XSS 검사
        if check_xss:
            for pattern in InputValidator.XSS_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    violations.append({
                        "type": ThreatType.XSS_ATTEMPT,
                        "message": f"Potential XSS detected: {pattern}",
                        "severity": SecurityLevel.HIGH
                    })
                    security_logger.warning("xss_attempt", {
                        "pattern": pattern,
                        "text_sample": text[:100]
                    })
        
        # HTML 태그 처리
        if not allow_html:
            # HTML 태그 제거 또는 이스케이프
            cleaned_text = bleach.clean(
                text,
                tags=[],  # 허용할 태그 (빈 리스트 = 모든 태그 제거)
                attributes={},  # 허용할 속성
                strip=True  # 태그 완전 제거
            )
        else:
            # 안전한 HTML만 허용
            allowed_tags = ['p', 'br', 'strong', 'em', 'u', 'ol', 'ul', 'li']
            cleaned_text = bleach.clean(
                text,
                tags=allowed_tags,
                attributes={},
                strip=True
            )
        
        return cleaned_text, violations
    
    @staticmethod
    def validate_file_upload(file: UploadFile) -> Tuple[bool, List[Dict[str, str]]]:
        """파일 업로드 검증"""
        
        violations = []
        
        # 파일 이름 검증
        if not file.filename:
            violations.append({
                "type": "INVALID_FILENAME",
                "message": "Filename is required",
                "severity": SecurityLevel.MEDIUM
            })
            return False, violations
        
        # 악성 파일 확장자 검사
        filename_lower = file.filename.lower()
        for pattern in InputValidator.MALICIOUS_FILE_PATTERNS:
            if re.search(pattern, filename_lower):
                violations.append({
                    "type": ThreatType.MALICIOUS_FILE,
                    "message": f"Dangerous file extension: {file.filename}",
                    "severity": SecurityLevel.CRITICAL
                })
                security_logger.error("malicious_file_upload_attempt", {
                    "filename": file.filename,
                    "content_type": file.content_type
                })
        
        # 파일 크기 검증 (32MB 제한)
        max_size = 32 * 1024 * 1024
        if file.size and file.size > max_size:
            violations.append({
                "type": "FILE_TOO_LARGE",
                "message": f"File too large: {file.size} > {max_size}",
                "severity": SecurityLevel.MEDIUM
            })
        
        # MIME 타입 검증
        allowed_mime_types = {
            'text/plain', 'text/csv', 'text/markdown',
            'application/pdf', 'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.ms-excel',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'image/jpeg', 'image/png', 'image/gif', 'image/webp'
        }
        
        if file.content_type not in allowed_mime_types:
            violations.append({
                "type": "INVALID_MIME_TYPE",
                "message": f"Unsupported file type: {file.content_type}",
                "severity": SecurityLevel.MEDIUM
            })
        
        # 위험한 패턴이 있으면 차단
        has_critical_violations = any(
            v["severity"] == SecurityLevel.CRITICAL for v in violations
        )
        
        return not has_critical_violations, violations
    
    @staticmethod
    def validate_api_key(api_key: str) -> bool:
        """API 키 형식 검증"""
        # API 키 형식: 최소 32자, 영숫자와 하이픈만 허용
        pattern = r'^[a-zA-Z0-9\-_]{32,}$'
        return bool(re.match(pattern, api_key))
    
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
        
        # 위험한 위반사항이 있으면 예외 발생
        critical_violations = [v for v in violations if v.get("severity") == SecurityLevel.HIGH]
        if critical_violations:
            raise ValidationError(
                message="Security validation failed",
                field_errors=[{
                    "field": v.get("field", "unknown"),
                    "message": v["message"],
                    "type": v["type"]
                } for v in critical_violations]
            )
        
        return cleaned_data

class RedisRateLimiter:
    """Redis 기반 고도화된 레이트 리미팅"""
    
    def __init__(self):
        self.redis_client = cache_manager.redis_client
        
        # API별 제한 설정
        self.api_limits = {
            # 일반 API
            "default": {"requests": 60, "window": 60},  # 1분에 60회
            
            # AI 관련 API (높은 비용)
            "ai_chat": {"requests": 20, "window": 60},  # 1분에 20회
            "ai_embedding": {"requests": 10, "window": 60},  # 1분에 10회
            "file_upload": {"requests": 5, "window": 300},  # 5분에 5회
            
            # 인증 관련 (브루트 포스 방지)
            "auth_login": {"requests": 5, "window": 300},  # 5분에 5회
            "auth_register": {"requests": 3, "window": 3600},  # 1시간에 3회
            
            # 관리자 API
            "admin": {"requests": 100, "window": 60},  # 1분에 100회
        }
        
        # 사용자 타입별 승수
        self.user_multipliers = {
            "anonymous": 0.5,  # 50% 제한
            "authenticated": 1.0,  # 기본 제한
            "premium": 2.0,  # 200% 제한
            "admin": 5.0  # 500% 제한
        }
    
    async def check_rate_limit(
        self,
        client_id: str,
        api_type: str = "default",
        user_type: str = "anonymous"
    ) -> Tuple[bool, Dict[str, Any]]:
        """레이트 리미팅 검사"""
        
        # 제한 설정 가져오기
        base_limits = self.api_limits.get(api_type, self.api_limits["default"])
        multiplier = self.user_multipliers.get(user_type, 1.0)
        
        requests_limit = int(base_limits["requests"] * multiplier)
        window_seconds = base_limits["window"]
        
        # Redis 키 생성
        redis_key = f"rate_limit:{api_type}:{client_id}"
        
        try:
            # 현재 시간과 윈도우 시작 시간
            now = int(time.time())
            window_start = now - window_seconds
            
            # 파이프라인을 사용한 원자적 연산
            pipe = self.redis_client.pipeline()
            
            # 윈도우 밖의 오래된 요청 제거
            pipe.zremrangebyscore(redis_key, 0, window_start)
            
            # 현재 요청 수 조회
            pipe.zcard(redis_key)
            
            # 새 요청 추가
            pipe.zadd(redis_key, {str(now): now})
            
            # TTL 설정
            pipe.expire(redis_key, window_seconds + 10)
            
            results = pipe.execute()
            current_requests = results[1]  # zcard 결과
            
            # 제한 초과 확인
            if current_requests >= requests_limit:
                # 제한 초과 로깅
                security_logger.warning("rate_limit_exceeded", {
                    "client_id": client_id,
                    "api_type": api_type,
                    "user_type": user_type,
                    "current_requests": current_requests,
                    "limit": requests_limit,
                    "window": window_seconds
                })
                
                return False, {
                    "allowed": False,
                    "current_requests": current_requests,
                    "limit": requests_limit,
                    "window": window_seconds,
                    "retry_after": window_seconds
                }
            
            return True, {
                "allowed": True,
                "current_requests": current_requests + 1,
                "limit": requests_limit,
                "window": window_seconds,
                "remaining": requests_limit - current_requests - 1
            }
            
        except Exception as e:
            security_logger.error("rate_limit_check_failed", {
                "client_id": client_id,
                "api_type": api_type,
                "error": str(e)
            })
            
            # Redis 오류 시 허용 (가용성 우선)
            return True, {"allowed": True, "error": "rate_limit_check_failed"}
    
    async def add_violation(self, client_id: str, violation_type: str, severity: SecurityLevel):
        """보안 위반 기록"""
        
        redis_key = f"security_violations:{client_id}"
        violation_data = {
            "type": violation_type,
            "severity": severity,
            "timestamp": time.time()
        }
        
        try:
            # 위반 기록 추가
            pipe = self.redis_client.pipeline()
            pipe.lpush(redis_key, json.dumps(violation_data))
            pipe.ltrim(redis_key, 0, 99)  # 최근 100개만 보관
            pipe.expire(redis_key, 86400)  # 24시간 보관
            pipe.execute()
            
            security_logger.warning("security_violation_recorded", {
                "client_id": client_id,
                "violation_type": violation_type,
                "severity": severity
            })
            
        except Exception as e:
            security_logger.error("violation_recording_failed", {
                "client_id": client_id,
                "error": str(e)
            })
    
    async def get_violation_history(self, client_id: str) -> List[Dict[str, Any]]:
        """보안 위반 이력 조회"""
        
        redis_key = f"security_violations:{client_id}"
        
        try:
            violations_raw = self.redis_client.lrange(redis_key, 0, -1)
            violations = []
            
            for violation_raw in violations_raw:
                try:
                    violation = json.loads(violation_raw)
                    violations.append(violation)
                except json.JSONDecodeError:
                    continue
            
            return violations
            
        except Exception as e:
            security_logger.error("violation_history_retrieval_failed", {
                "client_id": client_id,
                "error": str(e)
            })
            return []
    
    async def is_client_blocked(self, client_id: str) -> Tuple[bool, Optional[str]]:
        """클라이언트 차단 여부 확인"""
        
        # 위반 이력 조회
        violations = await self.get_violation_history(client_id)
        
        # 최근 1시간 내 위반 수 계산
        one_hour_ago = time.time() - 3600
        recent_violations = [
            v for v in violations 
            if v.get("timestamp", 0) > one_hour_ago
        ]
        
        # 차단 조건 확인
        critical_violations = [
            v for v in recent_violations 
            if v.get("severity") == SecurityLevel.CRITICAL
        ]
        
        high_violations = [
            v for v in recent_violations 
            if v.get("severity") == SecurityLevel.HIGH
        ]
        
        # 차단 로직
        if len(critical_violations) >= 1:
            return True, "Critical security violation detected"
        
        if len(high_violations) >= 3:
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
            "unusual_payload_size": {"min_size": 0, "max_size": 1024*1024},
            "suspicious_user_agents": [
                "curl", "wget", "python-requests", "bot", "crawler", "spider"
            ]
        }
    
    async def analyze_request(self, request: Request, client_id: str) -> List[Dict[str, Any]]:
        """요청 위협 분석"""
        
        threats = []
        
        # User-Agent 분석
        user_agent = request.headers.get("user-agent", "").lower()
        if any(pattern in user_agent for pattern in self.suspicious_patterns["suspicious_user_agents"]):
            threats.append({
                "type": ThreatType.SUSPICIOUS_PATTERN,
                "severity": SecurityLevel.LOW,
                "message": f"Suspicious user agent: {user_agent[:100]}",
                "details": {"user_agent": user_agent}
            })
        
        # 페이로드 크기 분석
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
                max_size = self.suspicious_patterns["unusual_payload_size"]["max_size"]
                if size > max_size:
                    threats.append({
                        "type": ThreatType.SUSPICIOUS_PATTERN,
                        "severity": SecurityLevel.MEDIUM,
                        "message": f"Unusually large payload: {size} bytes",
                        "details": {"payload_size": size}
                    })
            except ValueError:
                pass
        
        # 요청 빈도 분석
        rapid_requests = await self._check_rapid_requests(client_id)
        if rapid_requests:
            threats.append({
                "type": ThreatType.RATE_LIMIT_ABUSE,
                "severity": SecurityLevel.HIGH,
                "message": "Rapid request pattern detected",
                "details": rapid_requests
            })
        
        return threats
    
    async def _check_rapid_requests(self, client_id: str) -> Optional[Dict[str, Any]]:
        """빠른 요청 패턴 감지"""
        
        redis_key = f"request_pattern:{client_id}"
        threshold = self.suspicious_patterns["rapid_requests"]["threshold"]
        window = self.suspicious_patterns["rapid_requests"]["window"]
        
        try:
            now = int(time.time())
            window_start = now - window
            
            # 최근 요청 수 조회
            request_count = cache_manager.redis_client.zcount(
                redis_key, window_start, now
            )
            
            if request_count > threshold:
                return {
                    "request_count": request_count,
                    "threshold": threshold,
                    "window": window
                }
                
        except Exception as e:
            security_logger.error("rapid_request_check_failed", {
                "client_id": client_id,
                "error": str(e)
            })
        
        return None

class SecurityEnforcer:
    """보안 정책 적용"""
    
    def __init__(self):
        self.rate_limiter = RedisRateLimiter()
        self.threat_detector = ThreatDetector()
        self.input_validator = InputValidator()
    
    async def enforce_security(
        self,
        request: Request,
        client_id: str,
        api_type: str = "default",
        user_type: str = "anonymous"
    ) -> Tuple[bool, Dict[str, Any]]:
        """종합 보안 검사"""
        
        security_result = {
            "allowed": True,
            "violations": [],
            "rate_limit": {},
            "threats": [],
            "actions_taken": []
        }
        
        try:
            # 1. 클라이언트 차단 여부 확인
            is_blocked, block_reason = await self.rate_limiter.is_client_blocked(client_id)
            if is_blocked:
                security_result["allowed"] = False
                security_result["violations"].append({
                    "type": "CLIENT_BLOCKED",
                    "message": block_reason,
                    "severity": SecurityLevel.CRITICAL
                })
                return False, security_result
            
            # 2. 레이트 리미팅 검사
            rate_allowed, rate_info = await self.rate_limiter.check_rate_limit(
                client_id, api_type, user_type
            )
            security_result["rate_limit"] = rate_info
            
            if not rate_allowed:
                security_result["allowed"] = False
                security_result["violations"].append({
                    "type": ThreatType.RATE_LIMIT_ABUSE,
                    "message": "Rate limit exceeded",
                    "severity": SecurityLevel.MEDIUM
                })
                
                # 위반 기록
                await self.rate_limiter.add_violation(
                    client_id, ThreatType.RATE_LIMIT_ABUSE, SecurityLevel.MEDIUM
                )
                
                return False, security_result
            
            # 3. 위협 탐지
            threats = await self.threat_detector.analyze_request(request, client_id)
            security_result["threats"] = threats
            
            # 위협 수준에 따른 조치
            for threat in threats:
                if threat["severity"] in [SecurityLevel.HIGH, SecurityLevel.CRITICAL]:
                    # 위반 기록
                    await self.rate_limiter.add_violation(
                        client_id, threat["type"], threat["severity"]
                    )
                    
                    security_result["actions_taken"].append(f"Recorded {threat['type']} violation")
            
            return True, security_result
            
        except Exception as e:
            security_logger.error("security_enforcement_failed", {
                "client_id": client_id,
                "api_type": api_type,
                "error": str(e)
            })
            
            # 오류 시 허용 (가용성 우선)
            return True, {"allowed": True, "error": "security_check_failed"}

# 보안 데코레이터
def require_security_check(api_type: str = "default"):
    """보안 검사 데코레이터"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # request 객체 찾기
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            
            if not request:
                # request가 없으면 그냥 실행
                return await func(*args, **kwargs)
            
            # 보안 검사 실행
            security_enforcer = SecurityEnforcer()
            client_id = security_enforcer.rate_limiter._get_client_id(request)
            
            allowed, security_result = await security_enforcer.enforce_security(
                request, client_id, api_type
            )
            
            if not allowed:
                raise RateLimitError(
                    message="Security check failed",
                    retry_after=security_result.get("rate_limit", {}).get("retry_after")
                )
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator

# 전역 보안 인스턴스
security_enforcer = SecurityEnforcer()
input_validator = InputValidator()
rate_limiter = RedisRateLimiter()
threat_detector = ThreatDetector() 