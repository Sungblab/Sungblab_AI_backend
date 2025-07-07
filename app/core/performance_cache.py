"""
성능 최적화를 위한 고도화된 캐싱 시스템
토큰 계산, 임베딩, AI 응답 캐싱을 전문화하여 성능 향상
"""

import hashlib
import json
import time
from typing import Dict, List, Optional, Any, Tuple
from functools import wraps
import asyncio

from app.core.cache import cache_manager, CacheManager
from app.core.structured_logging import StructuredLogger

# 성능 로거 초기화
perf_logger = StructuredLogger("performance")

class TokenCache:
    """토큰 계산 전용 캐시"""
    
    PREFIX = "token_count"
    DEFAULT_TTL = 86400  # 24시간 (토큰 계산 결과는 변하지 않음)
    
    @staticmethod
    def _generate_token_key(text: str, model: str) -> str:
        """토큰 계산 캐시 키 생성"""
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        return f"{TokenCache.PREFIX}:{model}:{text_hash[:16]}"
    
    @staticmethod
    async def get_or_calculate_tokens(
        text: str, 
        model: str, 
        calculate_func,
        client
    ) -> Dict[str, int]:
        """토큰 수를 캐시에서 가져오거나 계산"""
        
        start_time = time.time()
        cache_key = TokenCache._generate_token_key(text, model)
        
        # 캐시에서 조회
        cached_result = cache_manager.get(cache_key)
        if cached_result:
            perf_logger.log_performance_metric(
                operation="token_count_cache_hit",
                duration=time.time() - start_time,
                success=True,
                text_length=len(text),
                model=model
            )
            return cached_result
        
        # 캐시 미스 - 실제 계산
        try:
            result = await calculate_func(text, model, client)
            
            # 결과 캐싱
            cache_manager.set(cache_key, result, TokenCache.DEFAULT_TTL)
            
            perf_logger.log_performance_metric(
                operation="token_count_calculated",
                duration=time.time() - start_time,
                success=True,
                text_length=len(text),
                model=model,
                tokens=result.get("input_tokens", 0)
            )
            
            return result
            
        except Exception as e:
            perf_logger.log_performance_metric(
                operation="token_count_error",
                duration=time.time() - start_time,
                success=False,
                text_length=len(text),
                model=model
            )
            raise

class EmbeddingCache:
    """임베딩 전용 고성능 캐시"""
    
    PREFIX = "embedding_v2"
    DEFAULT_TTL = 604800  # 7일 (임베딩은 장기간 유효)
    BATCH_SIZE = 50  # 배치 처리 크기
    
    @staticmethod
    def _generate_embedding_key(text: str, model: str, task_type: str = "SEMANTIC_SIMILARITY") -> str:
        """임베딩 캐시 키 생성"""
        content = f"{text}:{model}:{task_type}"
        text_hash = hashlib.sha256(content.encode()).hexdigest()
        return f"{EmbeddingCache.PREFIX}:{text_hash[:20]}"
    
    @staticmethod
    async def get_or_generate_embedding(
        text: str,
        model: str,
        task_type: str,
        generate_func,
        client
    ) -> List[float]:
        """임베딩을 캐시에서 가져오거나 생성"""
        
        start_time = time.time()
        cache_key = EmbeddingCache._generate_embedding_key(text, model, task_type)
        
        # 캐시에서 조회
        cached_result = cache_manager.get(cache_key)
        if cached_result:
            perf_logger.log_performance_metric(
                operation="embedding_cache_hit",
                duration=time.time() - start_time,
                success=True,
                text_length=len(text),
                model=model,
                task_type=task_type
            )
            return cached_result["embedding"]
        
        # 캐시 미스 - 임베딩 생성
        try:
            result = await generate_func(text, model, task_type, client)
            embedding = result.embeddings[0] if result.embeddings else []
            
            # 메타데이터와 함께 캐싱
            cache_data = {
                "embedding": embedding,
                "model": model,
                "task_type": task_type,
                "text_length": len(text),
                "created_at": time.time()
            }
            cache_manager.set(cache_key, cache_data, EmbeddingCache.DEFAULT_TTL)
            
            perf_logger.log_performance_metric(
                operation="embedding_generated",
                duration=time.time() - start_time,
                success=True,
                text_length=len(text),
                model=model,
                task_type=task_type,
                embedding_dimensions=len(embedding)
            )
            
            return embedding
            
        except Exception as e:
            perf_logger.log_performance_metric(
                operation="embedding_error",
                duration=time.time() - start_time,
                success=False,
                text_length=len(text),
                model=model,
                task_type=task_type
            )
            raise
    
    @staticmethod
    async def batch_get_or_generate_embeddings(
        texts: List[str],
        model: str,
        task_type: str,
        generate_func,
        client
    ) -> List[List[float]]:
        """배치 임베딩 생성 (캐시 활용)"""
        
        start_time = time.time()
        results = []
        cache_hits = 0
        cache_misses = []
        
        # 1단계: 캐시에서 일괄 조회
        for i, text in enumerate(texts):
            cache_key = EmbeddingCache._generate_embedding_key(text, model, task_type)
            cached_result = cache_manager.get(cache_key)
            
            if cached_result:
                results.append(cached_result["embedding"])
                cache_hits += 1
            else:
                results.append(None)  # 자리 표시
                cache_misses.append((i, text))
        
        # 2단계: 캐시 미스 텍스트들을 배치로 처리
        if cache_misses:
            miss_texts = [text for _, text in cache_misses]
            
            try:
                # 배치 임베딩 생성
                batch_results = await generate_func(miss_texts, model, task_type, client)
                
                # 결과를 캐시에 저장하고 results 배열에 업데이트
                for (original_index, text), embedding in zip(cache_misses, batch_results):
                    cache_key = EmbeddingCache._generate_embedding_key(text, model, task_type)
                    cache_data = {
                        "embedding": embedding,
                        "model": model,
                        "task_type": task_type,
                        "text_length": len(text),
                        "created_at": time.time()
                    }
                    cache_manager.set(cache_key, cache_data, EmbeddingCache.DEFAULT_TTL)
                    results[original_index] = embedding
                
            except Exception as e:
                perf_logger.log_performance_metric(
                    operation="batch_embedding_error",
                    duration=time.time() - start_time,
                    success=False,
                    total_texts=len(texts),
                    cache_hits=cache_hits,
                    cache_misses=len(cache_misses)
                )
                raise
        
        perf_logger.log_performance_metric(
            operation="batch_embedding_completed",
            duration=time.time() - start_time,
            success=True,
            total_texts=len(texts),
            cache_hits=cache_hits,
            cache_misses=len(cache_misses),
            cache_hit_ratio=cache_hits / len(texts) if texts else 0
        )
        
        return results

class ResponseCache:
    """AI 응답 캐싱 (유사한 질문에 대한 응답 재사용)"""
    
    PREFIX = "ai_response"
    DEFAULT_TTL = 3600  # 1시간 (응답은 상대적으로 짧은 TTL)
    SIMILARITY_THRESHOLD = 0.9  # 유사도 임계값
    
    @staticmethod
    def _generate_response_key(
        messages: List[Dict[str, str]], 
        model: str, 
        system_prompt: Optional[str] = None
    ) -> str:
        """응답 캐시 키 생성"""
        # 메시지와 설정을 조합하여 해시 생성
        content = {
            "messages": messages,
            "model": model,
            "system_prompt": system_prompt
        }
        content_str = json.dumps(content, sort_keys=True)
        content_hash = hashlib.sha256(content_str.encode()).hexdigest()
        return f"{ResponseCache.PREFIX}:{content_hash[:20]}"
    
    @staticmethod
    async def get_cached_response(
        messages: List[Dict[str, str]],
        model: str,
        system_prompt: Optional[str] = None
    ) -> Optional[str]:
        """캐시된 응답 조회"""
        
        cache_key = ResponseCache._generate_response_key(messages, model, system_prompt)
        cached_result = cache_manager.get(cache_key)
        
        if cached_result:
            perf_logger.log_performance_metric(
                operation="response_cache_hit",
                duration=0,
                success=True,
                model=model,
                message_count=len(messages)
            )
            return cached_result["response"]
        
        return None
    
    @staticmethod
    async def cache_response(
        messages: List[Dict[str, str]],
        model: str,
        response: str,
        system_prompt: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """응답 캐싱"""
        
        cache_key = ResponseCache._generate_response_key(messages, model, system_prompt)
        
        cache_data = {
            "response": response,
            "model": model,
            "message_count": len(messages),
            "response_length": len(response),
            "created_at": time.time(),
            "metadata": metadata or {}
        }
        
        cache_manager.set(cache_key, cache_data, ResponseCache.DEFAULT_TTL)
        
        perf_logger.log_performance_metric(
            operation="response_cached",
            duration=0,
            success=True,
            model=model,
            message_count=len(messages),
            response_length=len(response)
        )

class DatabaseCache:
    """데이터베이스 쿼리 결과 캐싱"""
    
    PREFIX = "db_query"
    DEFAULT_TTL = 300  # 5분 (DB 결과는 짧은 TTL)
    
    @staticmethod
    def _generate_query_key(query_type: str, *args, **kwargs) -> str:
        """DB 쿼리 캐시 키 생성"""
        content = f"{query_type}:{str(args)}:{str(sorted(kwargs.items()))}"
        content_hash = hashlib.md5(content.encode()).hexdigest()
        return f"{DatabaseCache.PREFIX}:{content_hash[:16]}"
    
    @staticmethod
    def cache_query_result(query_type: str, result: Any, ttl: Optional[int] = None, *args, **kwargs):
        """쿼리 결과 캐싱"""
        cache_key = DatabaseCache._generate_query_key(query_type, *args, **kwargs)
        cache_manager.set(cache_key, result, ttl or DatabaseCache.DEFAULT_TTL)
    
    @staticmethod
    def get_cached_query(query_type: str, *args, **kwargs) -> Optional[Any]:
        """캐시된 쿼리 결과 조회"""
        cache_key = DatabaseCache._generate_query_key(query_type, *args, **kwargs)
        return cache_manager.get(cache_key)

# 성능 모니터링 데코레이터
def monitor_cache_performance(cache_type: str):
    """캐시 성능 모니터링 데코레이터"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                perf_logger.log_performance_metric(
                    operation=f"{cache_type}_operation",
                    duration=time.time() - start_time,
                    success=True
                )
                return result
            except Exception as e:
                perf_logger.log_performance_metric(
                    operation=f"{cache_type}_operation",
                    duration=time.time() - start_time,
                    success=False,
                    error=str(e)
                )
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                perf_logger.log_performance_metric(
                    operation=f"{cache_type}_operation",
                    duration=time.time() - start_time,
                    success=True
                )
                return result
            except Exception as e:
                perf_logger.log_performance_metric(
                    operation=f"{cache_type}_operation",
                    duration=time.time() - start_time,
                    success=False,
                    error=str(e)
                )
                raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

# 캐시 통계 수집
class CacheStats:
    """캐시 성능 통계"""
    
    @staticmethod
    def get_cache_stats() -> Dict[str, Any]:
        """캐시 통계 조회"""
        try:
            info = cache_manager.redis_client.info()
            return {
                "redis_info": {
                    "used_memory": info.get("used_memory_human"),
                    "connected_clients": info.get("connected_clients"),
                    "total_commands_processed": info.get("total_commands_processed"),
                    "keyspace_hits": info.get("keyspace_hits"),
                    "keyspace_misses": info.get("keyspace_misses"),
                    "hit_rate": (
                        info.get("keyspace_hits", 0) / 
                        (info.get("keyspace_hits", 0) + info.get("keyspace_misses", 1))
                    )
                },
                "cache_keys": {
                    "token_cache": len(cache_manager.redis_client.keys(f"{TokenCache.PREFIX}:*")),
                    "embedding_cache": len(cache_manager.redis_client.keys(f"{EmbeddingCache.PREFIX}:*")),
                    "response_cache": len(cache_manager.redis_client.keys(f"{ResponseCache.PREFIX}:*")),
                    "db_cache": len(cache_manager.redis_client.keys(f"{DatabaseCache.PREFIX}:*"))
                }
            }
        except Exception as e:
            return {"error": str(e)}

# 캐시 워밍업
class CacheWarmer:
    """캐시 예열"""
    
    @staticmethod
    async def warm_up_common_tokens(common_prompts: List[str], models: List[str]):
        """자주 사용되는 프롬프트의 토큰 수 미리 계산"""
        # 구현 필요시 추가
        pass
    
    @staticmethod
    async def warm_up_system_embeddings(system_texts: List[str], model: str):
        """시스템 텍스트 임베딩 예열"""
        # 구현 필요시 추가
        pass 