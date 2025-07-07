"""
Redis 기반 고도화된 레이트 리미팅 미들웨어
API별 제한, 적응형 제한, 사용자 타입별 제한
"""

import time
import json
from typing import Dict, Optional, Tuple, Any, List
from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.security_enhanced import RedisRateLimiter, SecurityEnforcer, ThreatType, SecurityLevel
from app.core.structured_logging import StructuredLogger
from app.core.exceptions import RateLimitError, ErrorCode
from app.core.config import settings

# 레이트 리미팅 로거
rate_limit_logger = StructuredLogger("rate_limiting")

class AdvancedRateLimitingMiddleware(BaseHTTPMiddleware):
    """고도화된 레이트 리미팅 미들웨어"""
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.rate_limiter = RedisRateLimiter()
        self.security_enforcer = SecurityEnforcer()
        
        # API 경로별 타입 매핑
        self.api_type_mapping = {
            # AI 관련 API (높은 비용)
            "/api/v1/chat/": "ai_chat",
            "/api/v1/chat/stream": "ai_chat",
            "/api/v1/projects/chat": "ai_chat",
            "/api/v1/projects/upload": "file_upload",
            "/api/v1/embedding/": "ai_embedding",
            
            # 인증 관련 API
            "/api/v1/auth/login": "auth_login",
            "/api/v1/auth/register": "auth_register",
            "/api/v1/auth/refresh": "auth_login",
            
            # 관리자 API
            "/api/v1/admin/": "admin",
            
            # 기본 API
            "default": "default"
        }
        
        # 예외 경로 (레이트 리미팅 적용하지 않음)
        self.exempt_paths = {
            "/docs", "/redoc", "/openapi.json",
            "/health", "/metrics", "/favicon.ico"
        }
    
    async def dispatch(self, request: Request, call_next):
        # 예외 경로 확인
        if any(request.url.path.startswith(path) for path in self.exempt_paths):
            return await call_next(request)
        
        start_time = time.time()
        
        try:
            # 클라이언트 식별 및 사용자 타입 결정
            client_id = self._get_client_id(request)
            user_type = await self._get_user_type(request)
            api_type = self._get_api_type(request.url.path)
            
            rate_limit_print("rate_limit_check_started", {
                "client_id": client_id,
                "user_type": user_type,
                "api_type": api_type,
                "path": request.url.path,
                "method": request.method
            })
            
            # 종합 보안 검사 (레이트 리미팅 포함)
            allowed, security_result = await self.security_enforcer.enforce_security(
                request=request,
                client_id=client_id,
                api_type=api_type,
                user_type=user_type
            )
            
            if not allowed:
                # 보안 검사 실패 - 레이트 리미팅 위반
                return self._create_rate_limit_response(
                    security_result, client_id, api_type
                )
            
            # 요청 처리
            response = await call_next(request)
            
            # 응답에 레이트 리미팅 정보 추가
            rate_info = security_result.get("rate_limit", {})
            if rate_info:
                response.headers["X-RateLimit-Limit"] = str(rate_info.get("limit", "unknown"))
                response.headers["X-RateLimit-Remaining"] = str(rate_info.get("remaining", "unknown"))
                response.headers["X-RateLimit-Reset"] = str(int(time.time() + rate_info.get("window", 60)))
            
            # 성공 로깅
            rate_limit_print("rate_limit_check_passed", {
                "client_id": client_id,
                "api_type": api_type,
                "duration": time.time() - start_time,
                "status_code": response.status_code,
                "rate_info": rate_info
            })
            
            return response
            
        except Exception as e:
            rate_limit_logger.error("rate_limit_middleware_error", {
                "error": str(e),
                "path": request.url.path,
                "duration": time.time() - start_time
            })
            
            # 오류 발생시 요청 허용 (가용성 우선)
            return await call_next(request)
    
    def _get_client_id(self, request: Request) -> str:
        """클라이언트 식별자 생성"""
        # 1. Authorization 헤더에서 사용자 ID 추출 시도
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                # JWT 토큰에서 사용자 ID 추출 (실제 구현 필요)
                token = auth_header.replace("Bearer ", "")
                # 간단한 토큰 해싱 (실제로는 JWT 디코딩)
                import hashlib
                user_hash = hashlib.md5(token.encode()).hexdigest()[:16]
                return f"user_{user_hash}"
            except:
                pass
        
        # 2. IP 주소 기반 식별
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            ip = forwarded_for.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"
        
        return f"ip_{ip}"
    
    async def _get_user_type(self, request: Request) -> str:
        """사용자 타입 결정"""
        # Authorization 헤더 확인
        auth_header = request.headers.get("authorization", "")
        
        if not auth_header:
            return "anonymous"
        
        # 실제 환경에서는 JWT 토큰을 디코딩하여 사용자 정보 확인
        # 여기서는 간단히 토큰 존재 여부로만 판단
        if auth_header.startswith("Bearer "):
            # 실제로는 토큰에서 사용자 권한 정보 추출
            # 예: admin, premium, authenticated 등
            return "authenticated"
        
        return "anonymous"
    
    def _get_api_type(self, path: str) -> str:
        """API 경로에 따른 타입 결정"""
        for path_prefix, api_type in self.api_type_mapping.items():
            if path_prefix != "default" and path.startswith(path_prefix):
                return api_type
        
        return "default"
    
    def _create_rate_limit_response(
        self, 
        security_result: Dict[str, Any], 
        client_id: str, 
        api_type: str
    ) -> JSONResponse:
        """레이트 리미팅 응답 생성"""
        
        rate_info = security_result.get("rate_limit", {})
        violations = security_result.get("violations", [])
        
        # 위반 유형에 따른 메시지 생성
        violation_messages = []
        for violation in violations:
            if violation.get("type") == ThreatType.RATE_LIMIT_ABUSE:
                violation_messages.append("요청 빈도 제한을 초과했습니다.")
            elif violation.get("type") == "CLIENT_BLOCKED":
                violation_messages.append("보안 위반으로 인해 차단되었습니다.")
        
        main_message = violation_messages[0] if violation_messages else "요청이 제한되었습니다."
        
        # 응답 데이터 구성
        response_data = {
            "error": "RATE_LIMIT_EXCEEDED",
            "message": main_message,
            "details": {
                "retry_after": rate_info.get("retry_after", 60),
                "limit": rate_info.get("limit"),
                "current_requests": rate_info.get("current_requests"),
                "window": rate_info.get("window")
            }
        }
        
        # 헤더 설정
        headers = {
            "Retry-After": str(rate_info.get("retry_after", 60)),
            "X-RateLimit-Limit": str(rate_info.get("limit", "unknown")),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(int(time.time() + rate_info.get("window", 60)))
        }
        
        rate_limit_logger.warning("rate_limit_exceeded", {
            "client_id": client_id,
            "api_type": api_type,
            "rate_info": rate_info,
            "violations": violations
        })
        
        return JSONResponse(
            status_code=429,
            content=response_data,
            headers=headers
        )

class AdaptiveRateLimiter:
    """적응형 레이트 리미팅 (시스템 부하에 따라 동적 조정)"""
    
    def __init__(self):
        self.base_rate_limiter = RedisRateLimiter()
        self.system_load_threshold = 0.8  # 80% 부하시 제한 강화
        self.load_adjustment_factor = 0.5  # 부하시 50% 제한
        
    async def get_adaptive_limits(
        self, 
        api_type: str, 
        user_type: str
    ) -> Tuple[int, int]:
        """시스템 부하에 따른 적응형 제한값 계산"""
        
        # 기본 제한값 가져오기
        base_limits = self.base_rate_limiter.api_limits.get(
            api_type, self.base_rate_limiter.api_limits["default"]
        )
        multiplier = self.base_rate_limiter.user_multipliers.get(user_type, 1.0)
        
        base_requests = int(base_limits["requests"] * multiplier)
        base_window = base_limits["window"]
        
        # 시스템 부하 확인
        system_load = await self._get_system_load()
        
        if system_load > self.system_load_threshold:
            # 시스템 부하가 높으면 제한 강화
            adjusted_requests = int(base_requests * self.load_adjustment_factor)
            
            rate_limit_logger.warning("adaptive_rate_limiting_activated", {
                "system_load": system_load,
                "threshold": self.system_load_threshold,
                "original_limit": base_requests,
                "adjusted_limit": adjusted_requests,
                "api_type": api_type,
                "user_type": user_type
            })
            
            return adjusted_requests, base_window
        
        return base_requests, base_window
    
    async def _get_system_load(self) -> float:
        """시스템 부하 측정"""
        try:
            # Redis 연결 수, 메모리 사용량 등을 기반으로 부하 계산
            redis_info = self.base_rate_limiter.redis_client.info()
            
            # 간단한 부하 계산 (실제로는 더 정교한 메트릭 사용)
            connected_clients = redis_info.get("connected_clients", 0)
            used_memory = redis_info.get("used_memory", 0)
            max_memory = redis_info.get("maxmemory", 1) or 1
            
            # 정규화된 부하 계산 (0.0 ~ 1.0)
            client_load = min(connected_clients / 100, 1.0)  # 100개 클라이언트 기준
            memory_load = used_memory / max_memory
            
            system_load = max(client_load, memory_load)
            
            return system_load
            
        except Exception as e:
            rate_limit_logger.error("system_load_calculation_failed", {
                "error": str(e)
            })
            return 0.0  # 오류시 부하 없음으로 처리

class RateLimitingMetrics:
    """레이트 리미팅 메트릭 수집"""
    
    def __init__(self):
        self.rate_limiter = RedisRateLimiter()
    
    async def get_rate_limiting_stats(self) -> Dict[str, Any]:
        """레이트 리미팅 통계 조회"""
        try:
            redis_client = self.rate_limiter.redis_client
            
            # 현재 활성 제한 키 수
            rate_limit_keys = len(redis_client.keys("rate_limit:*"))
            
            # 보안 위반 기록 수
            violation_keys = len(redis_client.keys("security_violations:*"))
            
            # 최근 1시간 레이트 리미팅 위반 수
            now = int(time.time())
            one_hour_ago = now - 3600
            
            recent_violations = 0
            for key in redis_client.keys("security_violations:*"):
                violations_raw = redis_client.lrange(key, 0, -1)
                for violation_raw in violations_raw:
                    try:
                        violation = json.loads(violation_raw)
                        if violation.get("timestamp", 0) > one_hour_ago:
                            recent_violations += 1
                    except:
                        continue
            
            return {
                "active_rate_limits": rate_limit_keys,
                "clients_with_violations": violation_keys,
                "recent_violations_1h": recent_violations,
                "rate_limiting_enabled": True,
                "adaptive_limiting_enabled": True
            }
            
        except Exception as e:
            rate_limit_logger.error("rate_limiting_stats_failed", {
                "error": str(e)
            })
            return {"error": "Failed to collect rate limiting stats"}
    
    async def get_top_violators(self, limit: int = 10) -> List[Dict[str, Any]]:
        """상위 위반자 목록 조회"""
        try:
            redis_client = self.rate_limiter.redis_client
            violators = []
            
            # 모든 위반 기록 조회
            for key in redis_client.keys("security_violations:*"):
                client_id = key.replace("security_violations:", "")
                violations_raw = redis_client.lrange(key, 0, -1)
                
                # 최근 24시간 위반 수 계산
                one_day_ago = time.time() - 86400
                recent_violation_count = 0
                
                for violation_raw in violations_raw:
                    try:
                        violation = json.loads(violation_raw)
                        if violation.get("timestamp", 0) > one_day_ago:
                            recent_violation_count += 1
                    except:
                        continue
                
                if recent_violation_count > 0:
                    violators.append({
                        "client_id": client_id,
                        "violation_count_24h": recent_violation_count,
                        "total_violations": len(violations_raw)
                    })
            
            # 위반 수로 정렬
            violators.sort(key=lambda x: x["violation_count_24h"], reverse=True)
            
            return violators[:limit]
            
        except Exception as e:
            rate_limit_logger.error("top_violators_query_failed", {
                "error": str(e)
            })
            return []

# 전역 인스턴스
rate_limiting_middleware = AdvancedRateLimitingMiddleware
adaptive_rate_limiter = AdaptiveRateLimiter()
rate_limiting_metrics = RateLimitingMetrics()

# 유틸리티 함수
async def check_api_rate_limit(
    request: Request,
    api_type: str = "default",
    custom_limit: Optional[int] = None
) -> bool:
    """개별 API에서 레이트 리미팅 체크"""
    try:
        security_enforcer = SecurityEnforcer()
        
        # 클라이언트 정보 추출
        client_id = security_enforcer.rate_limiter._get_client_id(request)
        user_type = "anonymous"  # 실제로는 토큰에서 추출
        
        # 보안 검사
        allowed, security_result = await security_enforcer.enforce_security(
            request=request,
            client_id=client_id,
            api_type=api_type,
            user_type=user_type
        )
        
        if not allowed:
            rate_info = security_result.get("rate_limit", {})
            raise RateLimitError(
                message="Rate limit exceeded",
                retry_after=rate_info.get("retry_after", 60)
            )
        
        return True
        
    except RateLimitError:
        raise
    except Exception as e:
        rate_limit_logger.error("individual_rate_limit_check_failed", {
            "error": str(e),
            "api_type": api_type
        })
        return True  # 오류시 허용 