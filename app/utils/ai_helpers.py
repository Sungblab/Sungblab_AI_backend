"""
AI 관련 헬퍼 함수들 - 캐시 시스템과 통합하여 성능 최적화
"""

import logging
from typing import List, Dict, Any, Optional, Callable
import time
from app.core.cache import (
    token_cache,
    embedding_cache,
    response_cache,
    db_cache,
    cache_invalidator,
    CacheStats,
    monitor_cache_performance,
)

logger = logging.getLogger(__name__)


class OptimizedTokenCalculator:
    """최적화된 토큰 계산기"""

    @staticmethod
    @monitor_cache_performance("token_calculation")
    async def count_tokens_with_cache(
        text: str, model: str, client, original_count_func
    ) -> Dict[str, int]:
        """캐시를 활용한 토큰 계산"""
        if not text or not text.strip():
            return {"input_tokens": 0, "output_tokens": 0}

        cached_tokens = token_cache.get(text, model)
        if cached_tokens:
            # monitor_cache_performance에 캐시 히트 정보 전달
            kwargs = {'cache_hit': True}
            return cached_tokens

        tokens = await original_count_func(text, model, client)
        token_cache.set(text, model, tokens)
        return tokens


class OptimizedEmbeddingGenerator:
    """최��화된 임베딩 생성기"""

    @staticmethod
    @monitor_cache_performance("embedding_generation")
    async def generate_embedding_with_cache(
        text: str,
        model: str,
        client,
        original_generate_func,
        task_type: str = "SEMANTIC_SIMILARITY",
    ) -> List[float]:
        """캐시를 활용한 임베딩 생성"""
        if not text or not text.strip():
            logger.warning(
                "empty_embedding_request",
                extra={"data": {"text_length": len(text), "model": model}},
            )
            return []

        cached_embedding = embedding_cache.get(text, model)
        if cached_embedding:
            kwargs = {'cache_hit': True}
            return cached_embedding

        # 임베딩 생성 함수 래퍼
        async def generate_func_wrapper():
            return await original_generate_func(
                model=model, contents=text, config={"task_type": task_type}
            )

        embedding = await generate_func_wrapper()
        embedding_cache.set(text, model, embedding)
        return embedding


class OptimizedResponseGenerator:
    """최적화된 AI 응답 생성기"""

    @staticmethod
    async def check_cached_response(
        messages: List[Dict[str, str]],
        model: str,
        system_prompt: Optional[str] = None,
        enable_cache: bool = True,
    ) -> Optional[str]:
        """캐시된 응답 확인"""
        if not enable_cache:
            return None

        try:
            return response_cache.get(messages, model, system_prompt)
        except Exception as e:
            logger.warning(
                "response_cache_check_failed",
                extra={
                    "data": {
                        "error": str(e),
                        "model": model,
                        "message_count": len(messages),
                    }
                },
            )
            return None

    @staticmethod
    async def cache_response_if_needed(
        messages: List[Dict[str, str]],
        model: str,
        response: str,
        system_prompt: Optional[str] = None,
        enable_cache: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """필요한 경우 응답 캐싱"""
        if not enable_cache or not response or len(response) < 50:
            return

        try:
            response_cache.set(messages, model, response, system_prompt, metadata)
        except Exception as e:
            logger.warning(
                "response_cache_failed",
                extra={
                    "data": {
                        "error": str(e),
                        "model": model,
                        "response_length": len(response),
                    }
                },
            )


class DatabaseQueryOptimizer:
    """데이터베이스 쿼리 최적화"""

    @staticmethod
    def get_cached_messages(
        room_id: str, limit: int = 50, offset: int = 0, db_query_func: Callable = None
    ):
        """메시지 조회 (캐시 활용)"""
        query_params = {"room_id": room_id, "limit": limit, "offset": offset}
        cached_result = db_cache.get("room_messages", **query_params)

        if cached_result:
            logger.info(
                "performance_metric",
                extra={
                    "data": {
                        "operation": "db_cache_hit",
                        "query_type": "room_messages",
                        "room_id": room_id,
                    }
                },
            )
            return cached_result

        if db_query_func:
            start_time = time.time()
            try:
                result = db_query_func(room_id, limit, offset)
                db_cache.set("room_messages", result, **query_params)
                logger.info(
                    "performance_metric",
                    extra={
                        "data": {
                            "operation": "db_query_executed",
                            "duration": time.time() - start_time,
                            "query_type": "room_messages",
                            "room_id": room_id,
                        }
                    },
                )
                return result
            except Exception as e:
                logger.error(
                    "db_query_error",
                    extra={
                        "data": {
                            "query_type": "room_messages",
                            "error": str(e),
                        }
                    },
                )
                raise
        return None

    @staticmethod
    def invalidate_room_cache(room_id: str):
        """채팅방 관련 캐시 무효화"""
        try:
            cache_invalidator.invalidate_room_cache(room_id)
            logger.info("cache_invalidated", extra={"data": {"type": "room_messages", "room_id": room_id}})
        except Exception as e:
            logger.warning(
                "cache_invalidation_failed",
                extra={"data": {"error": str(e), "room_id": room_id}},
            )


class PerformanceMetrics:
    """성능 메트릭 수집 및 분석"""

    @staticmethod
    def get_ai_performance_summary() -> Dict[str, Any]:
        """AI 작업 성능 요약"""
        try:
            cache_stats = CacheStats.get_cache_stats()
            return {
                "cache_performance": cache_stats,
                "recommendations": PerformanceMetrics._generate_recommendations(
                    cache_stats
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _generate_recommendations(cache_stats: Dict[str, Any]) -> List[str]:
        """성능 개선 권장사항 생성"""
        recommendations = []
        try:
            hit_rate = cache_stats.get("hit_rate", 0)
            if hit_rate < 0.7:
                recommendations.append("캐시 적중률이 낮습니다. TTL 설정을 검토해보세요.")

            total_keys = cache_stats.get("total_keys", 0)
            if total_keys > 100000:
                recommendations.append("캐시 키가 많습니다. 정리 작업을 고려해보세요.")

        except Exception:
            recommendations.append("성능 분석 중 오류가 발생했습니다.")
        return recommendations