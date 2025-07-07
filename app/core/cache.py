import redis
import json
import pickle
from typing import Any, Optional, Union
from datetime import timedelta
import hashlib
from app.core.config import settings
from functools import wraps
import asyncio

class CacheManager:
    """통합 캐시 관리자"""
    
    def __init__(self):
        # Redis 연결 (환경변수로 설정)
        self.redis_client = redis.Redis.from_url(
            settings.REDIS_URL if hasattr(settings, 'REDIS_URL') 
            else "redis://localhost:6379",
            decode_responses=False  # 바이너리 데이터 지원
        )
        self.default_ttl = 3600  # 1시간
    
    def _generate_key(self, prefix: str, *args, **kwargs) -> str:
        """캐시 키 생성"""
        key_data = f"{prefix}:{str(args)}:{str(sorted(kwargs.items()))}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """값 저장"""
        try:
            ttl = ttl or self.default_ttl
            serialized_value = pickle.dumps(value)
            return self.redis_client.setex(key, ttl, serialized_value)
        except Exception as e:
            print(f"Cache set error: {e}")
            return False
    
    def get(self, key: str) -> Optional[Any]:
        """값 조회"""
        try:
            serialized_value = self.redis_client.get(key)
            if serialized_value:
                return pickle.loads(serialized_value)
            return None
        except Exception as e:
            print(f"Cache get error: {e}")
            return None
    
    def delete(self, key: str) -> bool:
        """값 삭제"""
        try:
            return bool(self.redis_client.delete(key))
        except Exception as e:
            print(f"Cache delete error: {e}")
            return False
    
    def exists(self, key: str) -> bool:
        """키 존재 여부 확인"""
        try:
            return bool(self.redis_client.exists(key))
        except Exception as e:
            print(f"Cache exists error: {e}")
            return False
    
    def clear_pattern(self, pattern: str) -> int:
        """패턴에 맞는 키들 삭제"""
        try:
            keys = self.redis_client.keys(pattern)
            if keys:
                return self.redis_client.delete(*keys)
            return 0
        except Exception as e:
            print(f"Cache clear pattern error: {e}")
            return 0

# 전역 캐시 매니저
cache_manager = CacheManager()

# 캐시 데코레이터들
def cache_response(ttl: int = 3600, key_prefix: str = "api"):
    """API 응답 캐싱 데코레이터"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # 캐시 키 생성
            cache_key = cache_manager._generate_key(
                f"{key_prefix}:{func.__name__}", 
                *args, **kwargs
            )
            
            # 캐시에서 조회
            cached_result = cache_manager.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # 함수 실행
            result = await func(*args, **kwargs)
            
            # 결과 캐싱
            cache_manager.set(cache_key, result, ttl)
            
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # 캐시 키 생성
            cache_key = cache_manager._generate_key(
                f"{key_prefix}:{func.__name__}", 
                *args, **kwargs
            )
            
            # 캐시에서 조회
            cached_result = cache_manager.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # 함수 실행
            result = func(*args, **kwargs)
            
            # 결과 캐싱
            cache_manager.set(cache_key, result, ttl)
            
            return result
        
        # 비동기 함수인지 확인
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

def cache_user_data(ttl: int = 1800):  # 30분
    """사용자 데이터 캐싱"""
    return cache_response(ttl=ttl, key_prefix="user")

def cache_project_data(ttl: int = 3600):  # 1시간
    """프로젝트 데이터 캐싱"""
    return cache_response(ttl=ttl, key_prefix="project")

def cache_ai_response(ttl: int = 86400):  # 24시간
    """AI 응답 캐싱 (동일한 질문에 대한 응답)"""
    return cache_response(ttl=ttl, key_prefix="ai_response")

def cache_embedding(ttl: int = 604800):  # 7일
    """임베딩 결과 캐싱"""
    return cache_response(ttl=ttl, key_prefix="embedding")

# 캐시 무효화 유틸리티
class CacheInvalidator:
    """캐시 무효화 관리"""
    
    @staticmethod
    def invalidate_user_cache(user_id: str):
        """사용자 캐시 무효화"""
        pattern = f"user:*{user_id}*"
        return cache_manager.clear_pattern(pattern)
    
    @staticmethod
    def invalidate_project_cache(project_id: str):
        """프로젝트 캐시 무효화"""
        pattern = f"project:*{project_id}*"
        return cache_manager.clear_pattern(pattern)
    
    @staticmethod
    def invalidate_all_cache():
        """모든 캐시 무효화 (주의해서 사용)"""
        return cache_manager.clear_pattern("*")

# 사용 예시:
# @cache_user_data(ttl=1800)
# def get_user_profile(user_id: str):
#     return user_data
#
# @cache_ai_response(ttl=86400)
# async def generate_ai_response(prompt: str, model: str):
#     return ai_response

# 임베딩 캐시 특수 처리
class EmbeddingCache:
    """임베딩 전용 캐시"""
    
    @staticmethod
    def get_embedding_key(text: str, model: str) -> str:
        """임베딩 캐시 키 생성"""
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        return f"embedding:{model}:{text_hash}"
    
    @staticmethod
    def cache_embedding(text: str, model: str, embedding: list, ttl: int = 604800):
        """임베딩 캐싱"""
        key = EmbeddingCache.get_embedding_key(text, model)
        return cache_manager.set(key, {
            "embedding": embedding,
            "model": model,
            "text_length": len(text)
        }, ttl)
    
    @staticmethod
    def get_cached_embedding(text: str, model: str) -> Optional[list]:
        """캐시된 임베딩 조회"""
        key = EmbeddingCache.get_embedding_key(text, model)
        result = cache_manager.get(key)
        return result["embedding"] if result else None

# 벡터 검색 결과 캐시
class VectorSearchCache:
    """벡터 검색 결과 캐시"""
    
    @staticmethod
    def get_search_key(project_id: str, query_hash: str, top_k: int, threshold: float) -> str:
        """검색 캐시 키 생성"""
        return f"vector_search:{project_id}:{query_hash}:{top_k}:{threshold}"
    
    @staticmethod
    def cache_search_result(project_id: str, query: str, top_k: int, 
                          threshold: float, results: list, ttl: int = 3600):
        """검색 결과 캐싱"""
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
        key = VectorSearchCache.get_search_key(project_id, query_hash, top_k, threshold)
        return cache_manager.set(key, results, ttl)
    
    @staticmethod
    def get_cached_search_result(project_id: str, query: str, 
                               top_k: int, threshold: float) -> Optional[list]:
        """캐시된 검색 결과 조회"""
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
        key = VectorSearchCache.get_search_key(project_id, query_hash, top_k, threshold)
        return cache_manager.get(key) 