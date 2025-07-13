"""
중앙 집중식 통합 캐시 관리 모듈

- Redis 기반의 범용 캐시 관리자 제공
- 인증, 성능(토큰, 임베딩, AI 응답) 등 특수 목적 캐싱 클래스 통합
- API 응답 캐싱을 위한 데코레이터 제공
- 캐시 무효화 및 통계 관리 기능
"""
import redis
import json
import pickle
import hashlib
import time
import asyncio
from typing import Any, Optional, Union, Dict, List, Tuple, Callable
from functools import wraps

from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# --- 기본 캐시 관리자 ---

class CacheManager:
    """Redis 기반 통합 캐시 관리자"""
    def __init__(self):
        try:
            logger.info(f"Attempting to connect to Redis: {settings.REDIS_URL}")
            self.redis_client = redis.Redis.from_url(
                settings.REDIS_URL, decode_responses=False, max_connections=20,
                retry_on_timeout=True, socket_timeout=5, socket_connect_timeout=5,
                health_check_interval=30
            )
            self.redis_client.ping() # 연결 테스트
            logger.info("Redis cache connected successfully.")
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as e:
            logger.warning(f"Could not connect to Redis: {e}. Caching will be disabled.")
            logger.warning(f"Redis URL used: {settings.REDIS_URL}")
            self.redis_client = None
        except Exception as e:
            logger.warning(f"Unexpected Redis error: {e}. Caching will be disabled.")
            logger.warning(f"Redis URL used: {settings.REDIS_URL}")
            self.redis_client = None
        
        self.default_ttl = 1800  # 30분

    def _generate_key(self, prefix: str, *args, **kwargs) -> str:
        key_data = f"{prefix}:{str(args)}:{str(sorted(kwargs.items()))}"
        return f"{prefix}:{hashlib.md5(key_data.encode()).hexdigest()}"

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        if not self.redis_client: return False
        try:
            ttl = ttl or self.default_ttl
            serialized_value = pickle.dumps(value)
            return self.redis_client.setex(key, ttl, serialized_value)
        except Exception as e:
            logger.error(f"Cache set error for key '{key}': {e}")
            return False

    def get(self, key: str) -> Optional[Any]:
        if not self.redis_client: return None
        try:
            serialized_value = self.redis_client.get(key)
            return pickle.loads(serialized_value) if serialized_value else None
        except Exception as e:
            logger.error(f"Cache get error for key '{key}': {e}")
            return None

    def delete(self, key: str) -> bool:
        if not self.redis_client: return False
        try:
            return bool(self.redis_client.delete(key))
        except Exception as e:
            logger.error(f"Cache delete error for key '{key}': {e}")
            return False

    def clear_pattern(self, pattern: str) -> int:
        if not self.redis_client: return 0
        try:
            keys = [key.decode('utf-8') for key in self.redis_client.scan_iter(match=pattern)]
            if keys:
                return self.redis_client.delete(*keys)
            return 0
        except Exception as e:
            logger.error(f"Cache clear pattern error for '{pattern}': {e}")
            return 0
            
    def exists(self, key: str) -> bool:
        if not self.redis_client: return False
        try:
            return self.redis_client.exists(key)
        except Exception as e:
            logger.error(f"Cache exists error for key '{key}': {e}")
            return False

# 전역 캐시 매니저 인스턴스
cache_manager = CacheManager()

# --- 성능 모니터링 데코레이터 ---

def monitor_cache_performance(operation: str):
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            cache_hit = False
            success = True
            try:
                # 캐시 히트 여부를 확인하기 위한 로직 (함수 구현에 따라 달라질 수 있음)
                # 여기서는 간단히 kwargs에서 cache_hit를 전달받는다고 가정
                if 'cache_hit' in kwargs:
                    cache_hit = kwargs.pop('cache_hit')

                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                logger.error(f"Error during {operation}: {e}")
                raise
            finally:
                duration = time.time() - start_time
                logger.info(
                    "performance_metric",
                    extra={
                        "data": {
                            "operation": operation,
                            "duration": duration,
                            "success": success,
                            "cache_hit": cache_hit,
                        }
                    },
                )
        return wrapper
    return decorator

# --- API 응답 캐싱 데코레이터 ---

def cache_response(ttl: int = 3600, key_prefix: str = "api"):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache_key = cache_manager._generate_key(f"{key_prefix}:{func.__name__}", *args, **kwargs)
            cached_result = cache_manager.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            result = await func(*args, **kwargs)
            cache_manager.set(cache_key, result, ttl)
            return result
        return wrapper
    return decorator

# --- 특수 목적 캐시 클래스들 ---

class AuthCache:
    """인증 정보 캐싱 시스템"""
    def __init__(self, cache: CacheManager):
        self.cache = cache
        self.cache_ttl = 300  # 5분
        self.cache_prefix = "auth_user:"

    def get_cached_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        key = f"{self.cache_prefix}{user_id}"
        return self.cache.get(key)

    def cache_user(self, user_id: str, user_data: Dict[str, Any]):
        key = f"{self.cache_prefix}{user_id}"
        self.cache.set(key, user_data, self.cache_ttl)

    def invalidate_user_cache(self, user_id: str):
        key = f"{self.cache_prefix}{user_id}"
        self.cache.delete(key)

class EmbeddingCache:
    """임베딩 전용 고성능 캐시"""
    PREFIX = "embedding_v2"
    DEFAULT_TTL = 604800  # 7일

    def __init__(self, cache: CacheManager):
        self.cache = cache

    def _get_key(self, text: str, model: str) -> str:
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        return f"{self.PREFIX}:{model}:{text_hash[:20]}"

    def get(self, text: str, model: str) -> Optional[List[float]]:
        key = self._get_key(text, model)
        cached = self.cache.get(key)
        return cached.get("embedding") if cached else None

    def set(self, text: str, model: str, embedding: List[float]):
        key = self._get_key(text, model)
        cache_data = {
            "embedding": embedding,
            "model": model,
            "text_length": len(text),
            "created_at": time.time()
        }
        self.cache.set(key, cache_data, self.DEFAULT_TTL)

class ResponseCache:
    """AI 응답 캐싱"""
    PREFIX = "ai_response_v2"
    DEFAULT_TTL = 3600 # 1시간

    def __init__(self, cache: CacheManager):
        self.cache = cache

    def _get_key(self, messages: List[Dict[str, str]], model: str, system_prompt: Optional[str] = None) -> str:
        content = {"messages": messages, "model": model, "system_prompt": system_prompt}
        content_str = json.dumps(content, sort_keys=True)
        content_hash = hashlib.sha256(content_str.encode()).hexdigest()
        return f"{self.PREFIX}:{content_hash[:20]}"

    def get(self, messages: List[Dict[str, str]], model: str, system_prompt: Optional[str] = None) -> Optional[str]:
        key = self._get_key(messages, model, system_prompt)
        cached = self.cache.get(key)
        return cached.get("response") if cached else None

    def set(self, messages: List[Dict[str, str]], model: str, response: str, system_prompt: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        key = self._get_key(messages, model, system_prompt)
        cache_data = {
            "response": response,
            "model": model,
            "message_count": len(messages),
            "response_length": len(response),
            "created_at": time.time(),
            "metadata": metadata or {}
        }
        self.cache.set(key, cache_data, self.DEFAULT_TTL)

class TokenCache:
    """토큰 계산 결과 캐싱"""
    PREFIX = "token_cache"
    DEFAULT_TTL = 86400 # 24시간

    def __init__(self, cache: CacheManager):
        self.cache = cache

    def _get_key(self, text: str, model: str) -> str:
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        return f"{self.PREFIX}:{model}:{text_hash[:20]}"

    def get(self, text: str, model: str) -> Optional[Dict[str, int]]:
        key = self._get_key(text, model)
        return self.cache.get(key)

    def set(self, text: str, model: str, token_counts: Dict[str, int]):
        key = self._get_key(text, model)
        self.cache.set(key, token_counts, self.DEFAULT_TTL)

class DatabaseCache:
    """데이터베이스 쿼리 결과 캐싱"""
    PREFIX = "db_query"
    DEFAULT_TTL = 300 # 5분

    def __init__(self, cache: CacheManager):
        self.cache = cache

    def _get_key(self, query_type: str, **kwargs) -> str:
        key_parts = [f"{k}:{v}" for k, v in sorted(kwargs.items())]
        return f"{self.PREFIX}:{query_type}:{':'.join(key_parts)}"

    def get(self, query_type: str, **kwargs) -> Optional[Any]:
        key = self._get_key(query_type, **kwargs)
        return self.cache.get(key)

    def set(self, query_type: str, result: Any, ttl: Optional[int] = None, **kwargs):
        key = self._get_key(query_type, **kwargs)
        self.cache.set(key, result, ttl or self.DEFAULT_TTL)

# --- 캐시 통계 및 관리 ---

class CacheStats:
    """캐시 통계 조회"""
    @staticmethod
    def get_cache_stats() -> Dict[str, Any]:
        if not cache_manager.redis_client:
            return {"status": "disabled"}
        try:
            redis_info = cache_manager.redis_client.info()
            keyspace_info = redis_info.get('db0', {})
            
            return {
                "redis_version": redis_info.get("redis_version"),
                "uptime_in_seconds": redis_info.get("uptime_in_seconds"),
                "connected_clients": redis_info.get("connected_clients"),
                "used_memory_human": redis_info.get("used_memory_human"),
                "total_keys": keyspace_info.get("keys"),
                "expires": keyspace_info.get("expires"),
                "hit_rate": (redis_info['keyspace_hits'] / (redis_info['keyspace_hits'] + redis_info['keyspace_misses'])) if (redis_info['keyspace_hits'] + redis_info['keyspace_misses']) > 0 else 0,
            }
        except Exception as e:
            logger.error(f"Could not get Redis stats: {e}")
            return {"error": str(e)}

class CacheInvalidator:
    """캐시 무효화 유틸리티"""
    @staticmethod
    def invalidate_user_cache(user_id: str):
        logger.info(f"Invalidating cache for user: {user_id}")
        auth_cache.invalidate_user_cache(user_id)
        cache_manager.clear_pattern(f"api:get_projects_for_user*:{user_id}*")

    @staticmethod
    def invalidate_project_cache(project_id: str):
        logger.info(f"Invalidating cache for project: {project_id}")
        cache_manager.clear_pattern(f"*:*{project_id}*")
        
    @staticmethod
    def invalidate_room_cache(room_id: str):
        logger.info(f"Invalidating cache for room: {room_id}")
        db_cache.cache.clear_pattern(f"{DatabaseCache.PREFIX}:room_messages:*{room_id}*")

    @staticmethod
    def invalidate_all_cache():
        logger.warning("Clearing all application cache.")
        if cache_manager.redis_client:
            cache_manager.redis_client.flushdb()

# --- 전역 특수 캐시 인스턴스 --- 
auth_cache = AuthCache(cache_manager)
embedding_cache = EmbeddingCache(cache_manager)
response_cache = ResponseCache(cache_manager)
token_cache = TokenCache(cache_manager)
db_cache = DatabaseCache(cache_manager)
cache_invalidator = CacheInvalidator()
