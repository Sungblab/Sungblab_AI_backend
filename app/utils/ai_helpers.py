"""
AI 관련 헬퍼 함수들 - 캐시 시스템과 통합하여 성능 최적화
"""

from typing import List, Dict, Any, Optional
import time
from app.core.performance_cache import (
    TokenCache, EmbeddingCache, ResponseCache, 
    monitor_cache_performance, perf_logger
)
from app.core.structured_logging import StructuredLogger

# AI 작업 로거
ai_logger = StructuredLogger("ai_operations")

class OptimizedTokenCalculator:
    """최적화된 토큰 계산기"""
    
    @staticmethod
    @monitor_cache_performance("token_calculation")
    async def count_tokens_with_cache(
        text: str, 
        model: str, 
        client,
        original_count_func
    ) -> Dict[str, int]:
        """캐시를 활용한 토큰 계산"""
        
        if not text or not text.strip():
            return {"input_tokens": 0, "output_tokens": 0}
        
        return await TokenCache.get_or_calculate_tokens(
            text=text,
            model=model,
            calculate_func=original_count_func,
            client=client
        )
    
    @staticmethod
    async def batch_count_tokens(
        texts: List[str],
        model: str,
        client,
        original_count_func
    ) -> List[Dict[str, int]]:
        """배치 토큰 계산 (캐시 활용)"""
        
        start_time = time.time()
        results = []
        cache_hits = 0
        
        for text in texts:
            if not text or not text.strip():
                results.append({"input_tokens": 0, "output_tokens": 0})
                continue
            
            # 개별 텍스트에 대해 캐시 확인
            cache_key = TokenCache._generate_token_key(text, model)
            from app.core.performance_cache import cache_manager
            cached_result = cache_manager.get(cache_key)
            
            if cached_result:
                results.append(cached_result)
                cache_hits += 1
            else:
                # 캐시 미스인 경우 개별 계산
                result = await OptimizedTokenCalculator.count_tokens_with_cache(
                    text, model, client, original_count_func
                )
                results.append(result)
        
        perf_logger.log_performance_metric(
            operation="batch_token_calculation",
            duration=time.time() - start_time,
            success=True,
            total_texts=len(texts),
            cache_hits=cache_hits,
            cache_hit_ratio=cache_hits / len(texts) if texts else 0
        )
        
        return results

class OptimizedEmbeddingGenerator:
    """최적화된 임베딩 생성기"""
    
    @staticmethod
    @monitor_cache_performance("embedding_generation")
    async def generate_embedding_with_cache(
        text: str,
        model: str,
        client,
        original_generate_func,
        task_type: str = "SEMANTIC_SIMILARITY"
    ) -> List[float]:
        """캐시를 활용한 임베딩 생성"""
        
        if not text or not text.strip():
            ai_logger.warning("empty_embedding_request", {
                "text_length": len(text),
                "model": model
            })
            return []
        
        # 임베딩 캐시 사용
        async def generate_func_wrapper(text, model, task_type, client):
            return await original_generate_func(
                model=model,
                contents=text,
                config={"task_type": task_type}
            )
        
        return await EmbeddingCache.get_or_generate_embedding(
            text=text,
            model=model,
            task_type=task_type,
            generate_func=generate_func_wrapper,
            client=client
        )
    
    @staticmethod
    async def batch_generate_embeddings_with_cache(
        texts: List[str],
        model: str,
        client,
        original_generate_func,
        task_type: str = "SEMANTIC_SIMILARITY"
    ) -> List[List[float]]:
        """배치 임베딩 생성 (캐시 활용)"""
        
        if not texts:
            return []
        
        # 빈 텍스트 필터링
        valid_texts = [text for text in texts if text and text.strip()]
        if not valid_texts:
            return [[] for _ in texts]
        
        # 배치 임베딩 생성 함수 래퍼
        async def batch_generate_func_wrapper(texts, model, task_type, client):
            embeddings = []
            for text in texts:
                result = await original_generate_func(
                    model=model,
                    contents=text,
                    config={"task_type": task_type}
                )
                embedding = result.embeddings[0] if result.embeddings else []
                embeddings.append(embedding)
            return embeddings
        
        return await EmbeddingCache.batch_get_or_generate_embeddings(
            texts=texts,
            model=model,
            task_type=task_type,
            generate_func=batch_generate_func_wrapper,
            client=client
        )

class OptimizedResponseGenerator:
    """최적화된 AI 응답 생성기"""
    
    @staticmethod
    async def check_cached_response(
        messages: List[Dict[str, str]],
        model: str,
        system_prompt: Optional[str] = None,
        enable_cache: bool = True
    ) -> Optional[str]:
        """캐시된 응답 확인"""
        
        if not enable_cache:
            return None
        
        try:
            return await ResponseCache.get_cached_response(
                messages=messages,
                model=model,
                system_prompt=system_prompt
            )
        except Exception as e:
            ai_logger.warning("response_cache_check_failed", {
                "error": str(e),
                "model": model,
                "message_count": len(messages)
            })
            return None
    
    @staticmethod
    async def cache_response_if_needed(
        messages: List[Dict[str, str]],
        model: str,
        response: str,
        system_prompt: Optional[str] = None,
        enable_cache: bool = True,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """필요한 경우 응답 캐싱"""
        
        if not enable_cache or not response or len(response) < 50:
            return  # 너무 짧은 응답은 캐싱하지 않음
        
        try:
            await ResponseCache.cache_response(
                messages=messages,
                model=model,
                response=response,
                system_prompt=system_prompt,
                metadata=metadata
            )
        except Exception as e:
            ai_logger.warning("response_cache_failed", {
                "error": str(e),
                "model": model,
                "response_length": len(response)
            })

class DatabaseQueryOptimizer:
    """데이터베이스 쿼리 최적화"""
    
    @staticmethod
    def get_cached_messages(
        room_id: str,
        limit: int = 50,
        offset: int = 0,
        db_query_func=None
    ):
        """메시지 조회 (캐시 활용)"""
        from app.core.performance_cache import DatabaseCache
        
        # 캐시 키 생성
        cache_key = f"room_messages:{room_id}:{limit}:{offset}"
        
        # 캐시에서 조회
        cached_result = DatabaseCache.get_cached_query(
            "room_messages", room_id=room_id, limit=limit, offset=offset
        )
        
        if cached_result:
            perf_logger.log_performance_metric(
                operation="db_cache_hit",
                duration=0,
                success=True,
                query_type="room_messages",
                room_id=room_id
            )
            return cached_result
        
        # 캐시 미스 - DB 조회
        if db_query_func:
            start_time = time.time()
            try:
                result = db_query_func(room_id, limit, offset)
                
                # 결과 캐싱 (5분)
                DatabaseCache.cache_query_result(
                    "room_messages", result, ttl=300,
                    room_id=room_id, limit=limit, offset=offset
                )
                
                perf_logger.log_performance_metric(
                    operation="db_query_executed",
                    duration=time.time() - start_time,
                    success=True,
                    query_type="room_messages",
                    room_id=room_id,
                    result_count=len(result) if isinstance(result, list) else 1
                )
                
                return result
                
            except Exception as e:
                perf_logger.log_performance_metric(
                    operation="db_query_error",
                    duration=time.time() - start_time,
                    success=False,
                    query_type="room_messages",
                    error=str(e)
                )
                raise
        
        return None
    
    @staticmethod
    def invalidate_room_cache(room_id: str):
        """채팅방 관련 캐시 무효화"""
        from app.core.performance_cache import DatabaseCache
        
        try:
            # 해당 방의 모든 메시지 캐시 삭제
            pattern = f"db_query:room_messages:*{room_id}*"
            DatabaseCache.cache_manager.clear_pattern(pattern)
            
            ai_print("cache_invalidated", {
                "type": "room_messages",
                "room_id": room_id
            })
        except Exception as e:
            ai_logger.warning("cache_invalidation_failed", {
                "error": str(e),
                "room_id": room_id
            })

# 성능 메트릭 수집기
class PerformanceMetrics:
    """성능 메트릭 수집 및 분석"""
    
    @staticmethod
    def get_ai_performance_summary() -> Dict[str, Any]:
        """AI 작업 성능 요약"""
        from app.core.performance_cache import CacheStats
        
        try:
            cache_stats = CacheStats.get_cache_stats()
            
            return {
                "cache_performance": cache_stats,
                "recommendations": PerformanceMetrics._generate_recommendations(cache_stats)
            }
        except Exception as e:
            return {"error": str(e)}
    
    @staticmethod
    def _generate_recommendations(cache_stats: Dict[str, Any]) -> List[str]:
        """성능 개선 권장사항 생성"""
        recommendations = []
        
        try:
            redis_info = cache_stats.get("redis_info", {})
            hit_rate = redis_info.get("hit_rate", 0)
            
            if hit_rate < 0.7:
                recommendations.append("캐시 적중률이 낮습니다. TTL 설정을 검토해보세요.")
            
            cache_keys = cache_stats.get("cache_keys", {})
            total_keys = sum(cache_keys.values())
            
            if total_keys > 100000:
                recommendations.append("캐시 키가 많습니다. 정리 작업을 고려해보세요.")
            
            if cache_keys.get("token_cache", 0) < 100:
                recommendations.append("토큰 캐시 사용량이 적습니다. 더 적극적인 캐싱을 고려해보세요.")
                
        except Exception:
            recommendations.append("성능 분석 중 오류가 발생했습니다.")
        
        return recommendations

# 캐시 통합 관리자
class CacheIntegrationManager:
    """캐시 시스템 통합 관리"""
    
    @staticmethod
    async def warm_up_common_data():
        """자주 사용되는 데이터 캐시 예열"""
        
        # 시스템 프롬프트 토큰 계산 예열
        common_system_prompts = [
            "You are a helpful AI assistant.",
            "당신은 Sungblab AI 교육 어시스턴트입니다.",
            # 더 많은 공통 프롬프트 추가 가능
        ]
        
        # 공통 모델들
        common_models = ["gemini-2.5-flash", "gemini-2.5-pro"]
        
        try:
            for prompt in common_system_prompts:
                for model in common_models:
                    cache_key = TokenCache._generate_token_key(prompt, model)
                    if not TokenCache.cache_manager.exists(cache_key):
                        # 실제 계산 없이 예상 토큰 수로 캐시 채우기
                        estimated_tokens = {"input_tokens": len(prompt) // 4, "output_tokens": 0}
                        TokenCache.cache_manager.set(cache_key, estimated_tokens, TokenCache.DEFAULT_TTL)
            
            ai_print("cache_warmup_completed", {
                "system_prompts": len(common_system_prompts),
                "models": len(common_models)
            })
            
        except Exception as e:
            ai_logger.warning("cache_warmup_failed", {"error": str(e)})
    
    @staticmethod
    def cleanup_expired_cache():
        """만료된 캐시 정리"""
        try:
            # Redis 자체적으로 TTL 관리하지만, 필요시 수동 정리 가능
            ai_print("cache_cleanup_completed", {})
        except Exception as e:
            ai_logger.warning("cache_cleanup_failed", {"error": str(e)})

# 사용 예시와 마이그레이션 가이드
class MigrationHelper:
    """기존 코드를 캐시 시스템으로 마이그레이션하는 헬퍼"""
    
    @staticmethod
    def example_token_calculation_migration():
        """
        토큰 계산 마이그레이션 예시
        
        # 기존 방식
        async def old_way(text, model, client):
            return await count_gemini_tokens(text, model, client)
        
        # 새로운 방식 (캐시 활용)
        async def new_way(text, model, client):
            return await OptimizedTokenCalculator.count_tokens_with_cache(
                text, model, client, count_gemini_tokens
            )
        """
        pass
    
    @staticmethod 
    def example_embedding_migration():
        """
        임베딩 생성 마이그레이션 예시
        
        # 기존 방식
        async def old_way(text, model, client):
            result = await client.models.embed_content(
                model=model,
                contents=text,
                config=types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY")
            )
            return result.embeddings[0] if result.embeddings else []
        
        # 새로운 방식 (캐시 활용)
        async def new_way(text, model, client):
            return await OptimizedEmbeddingGenerator.generate_embedding_with_cache(
                text, model, "SEMANTIC_SIMILARITY", client, 
                lambda **kwargs: client.models.embed_content(**kwargs)
            )
        """
        pass 