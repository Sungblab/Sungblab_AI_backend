from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.schemas.chat import (
    ChatRoom, ChatRoomCreate, ChatRoomList, 
    ChatMessageCreate, ChatMessage, ChatMessageList,
    ChatRequest, TokenUsage, PromptGenerateRequest
)
from app.crud import crud_chat, crud_stats, crud_project, crud_subscription
from app.crud.crud_anonymous_usage import crud_anonymous_usage
from app.db.session import get_db
from app.db.retry_session import get_robust_db, retry_db_operation
from app.core.security import get_current_user
from app.models.user import User
import json
from app.core.config import settings
import logging
import base64
from typing import Optional, List, AsyncGenerator, Dict, Any, Set
import os
from datetime import datetime, timezone
from app.models.subscription import Subscription
import time
import asyncio
import io
import hashlib
import uuid
from typing import Dict, Set
from fastapi import HTTPException

# 새로운 Google Genai 라이브러리 import
from google import genai
from google.genai import types

from app.core.models import (
    ACTIVE_MODELS, get_model_config, get_multimodal_models, 
    ALLOWED_MODELS, ModelProvider
)

router = APIRouter()
logger = logging.getLogger(__name__)

# 멀티모달 모델 리스트
MULTIMODAL_MODELS = get_multimodal_models()

# Gemini 모델 리스트
GEMINI_MODELS = [
    model_name for model_name, config in ACTIVE_MODELS.items()
    if config.provider == ModelProvider.GOOGLE
]

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
GEMINI_INLINE_DATA_LIMIT = 10 * 1024 * 1024  # 10MB (Gemini API 제한)

# 최신 Gemini 모델 컨텍스트 한도 설정 (API 문서 기준)
MODEL_CONTEXT_LIMITS = {
    "gemini-2.5-pro": {
        "total_tokens": 2_000_000,  # 2M 토큰
        "output_reserve": 4096,     # 출력용 예약
        "system_reserve": 2048,     # 시스템 프롬프트용 예약
        "file_reserve": 10000       # 파일용 예약
    },
    "gemini-2.5-flash": {
        "total_tokens": 1_000_000,  # 1M 토큰
        "output_reserve": 2048,     # 출력용 예약
        "system_reserve": 1024,     # 시스템 프롬프트용 예약
        "file_reserve": 5000        # 파일용 예약
    },
    "gemini-2.0-flash": {
        "total_tokens": 1_000_000,  # 1M 토큰
        "output_reserve": 2048,
        "system_reserve": 1024,
        "file_reserve": 5000
    },
    "gemini-1.5-pro": {
        "total_tokens": 2_000_000,  # 2M 토큰
        "output_reserve": 4096,
        "system_reserve": 2048,
        "file_reserve": 10000
    },
    "gemini-1.5-flash": {
        "total_tokens": 1_000_000,  # 1M 토큰
        "output_reserve": 2048,
        "system_reserve": 1024,
        "file_reserve": 5000
    }
}

# 사고 기능 최적화 설정 추가
THINKING_OPTIMIZATION = {
    "gemini-2.5-flash": {
        "default_budget": 0,  # 빠른 응답을 위해 기본적으로 비활성화
        "max_budget": 24576,
        "adaptive": True  # 상황에 따라 적응형 사고 예산
    },
    "gemini-2.5-pro": {
        "default_budget": 4096,  # Pro는 품질 위해 기본 사고 유지
        "max_budget": 8192,
        "adaptive": True
    }
}

# 채팅 세션 캐시 (메모리 기반)
CHAT_SESSION_CACHE = {}

# 스트리밍 버퍼 설정
STREAMING_BUFFER_SIZE = 1024  # 바이트 단위
STREAMING_FLUSH_INTERVAL = 0.1  # 초 단위

# 컨텍스트 압축 설정
CONTEXT_COMPRESSION_THRESHOLD = 0.8  # 컨텍스트 80% 초과 시 압축
CONTEXT_SUMMARY_RATIO = 0.3  # 압축 시 30%로 요약

def generateUniqueId():
    return int(time.time() * 1000)

async def process_file_to_base64(file: UploadFile) -> tuple[str, str]:
    try:
        contents = await file.read()
        
        # 파일이 Gemini API 제한을 초과하는 경우 File API 사용
        if len(contents) > GEMINI_INLINE_DATA_LIMIT:
            logger.warning(f"File {file.filename} ({len(contents)} bytes) exceeds Gemini inline data limit. Using File API instead.")
            
            # Gemini 클라이언트 생성
            client = get_gemini_client()
            if not client:
                raise HTTPException(status_code=500, detail="Gemini API 클라이언트 생성 실패")
            
            try:
                # File API를 사용하여 업로드
                uploaded_file = client.files.upload(
                    file=io.BytesIO(contents),
                    config=dict(
                        mime_type=file.content_type,
                        display_name=f"chat_{file.filename}"
                    )
                )
                
                # 파일이 처리될 때까지 대기 (최대 30초)
                max_wait_time = 30
                wait_time = 0
                while uploaded_file.state.name == 'PROCESSING' and wait_time < max_wait_time:
                    await asyncio.sleep(2)
                    wait_time += 2
                    try:
                        uploaded_file = client.files.get(name=uploaded_file.name)
                    except Exception as e:
                        logger.error(f"Error checking file status: {e}", exc_info=True)
                        break
                
                # 처리 상태 확인
                if uploaded_file.state.name != 'ACTIVE':
                    logger.warning(f"File {file.filename} is in state {uploaded_file.state.name}")
                
                # File API URI 반환 (base64 대신)
                return f"FILE_API:{uploaded_file.name}", file.content_type
                
            except Exception as e:
                logger.error(f"File API upload failed for {file.filename}: {e}", exc_info=True)
                # 폴백: 파일 정보만 전송
                file_info = f"파일명: {file.filename}, 크기: {len(contents)} bytes, 타입: {file.content_type} (File API 업로드 실패)"
                base64_data = base64.b64encode(file_info.encode()).decode('utf-8')
                return base64_data, file.content_type
        else:
            # 작은 파일은 기존 방식 유지
            base64_data = base64.b64encode(contents).decode('utf-8')
            return base64_data, file.content_type
            
    except Exception as e:
        raise

def get_gemini_client():
    """새로운 Gemini 클라이언트를 생성하는 함수"""
    try:
        if not settings.GEMINI_API_KEY:
            return None
        
        # 새로운 방식으로 클라이언트 생성
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return client
    except Exception as e:
        logger.error(f"Gemini client creation error: {e}", exc_info=True)
        return None

def count_tokens_with_tiktoken(text: str, model: str = "gpt-4") -> dict:
    """tiktoken을 사용한 정확한 토큰 계산"""
    import tiktoken
    
    try:
        # Gemini 모델은 OpenAI와 다른 토크나이저를 사용하지만, 
        # tiktoken의 cl100k_base는 비교적 정확한 추정을 제공
        if "gemini" in model.lower():
            # Gemini용으로 cl100k_base 사용 (GPT-4와 유사한 토큰화)
            encoding_name = "cl100k_base"
        else:
            # 기타 모델용 기본값
            encoding_name = "cl100k_base"
            
        encoding = tiktoken.get_encoding(encoding_name)
        token_count = len(encoding.encode(text))
        
        return {
            "input_tokens": token_count,
            "output_tokens": 0,
            "method": "tiktoken",
            "encoding": encoding_name
        }
    except Exception as e:
        logger.warning(f"tiktoken calculation failed: {e}, using fallback")
        return fallback_token_calculation(text)

def fallback_token_calculation(text: str) -> dict:
    """tiktoken 실패 시 fallback 계산"""
    import re
    
    # 한국어/영어 혼합 텍스트 정확한 추정
    korean_chars = len(re.findall(r'[가-힣]', text))
    english_chars = len(re.findall(r'[a-zA-Z]', text))
    numbers_symbols = len(re.findall(r'[0-9\s\.,;:!?\-\(\)\[\]{}]', text))
    other_chars = len(text) - korean_chars - english_chars - numbers_symbols
    
    # 한국어 1.3자/토큰, 영어 3.5자/토큰 (tiktoken 기준 조정)
    estimated_tokens = (
        korean_chars / 1.3 + 
        english_chars / 3.5 + 
        numbers_symbols / 2.5 + 
        other_chars / 2
    )
    
    return {
        "input_tokens": max(1, int(estimated_tokens)),
        "output_tokens": 0,
        "method": "fallback",
        "encoding": "estimated"
    }

# 컨텍스트 관리 설정
MAX_MESSAGES_WINDOW = 15  # 최대 메시지 개수
SUMMARY_TRIGGER_THRESHOLD = 12  # 요약 트리거 메시지 개수
CONTEXT_SUMMARY_CACHE = {}  # 요약 캐시

def get_dynamic_context_limit(model: str, system_tokens: int = 0, file_tokens: int = 0) -> int:
    """모델별 동적 컨텍스트 한도 계산 (최신 API 기준)"""
    # 기본값 설정 (호환성을 위해)
    default_config = {
        "total_tokens": 1_000_000,
        "output_reserve": 2048,
        "system_reserve": 1024,
        "file_reserve": 5000
    }
    
    config = MODEL_CONTEXT_LIMITS.get(model, default_config)
    
    # 사용 가능한 컨텍스트 계산
    available_tokens = (
        config["total_tokens"] 
        - config["output_reserve"] 
        - system_tokens 
        - file_tokens
    )
    
    # 최소 한도 보장 (너무 작으면 기본값 사용)
    min_context = 10000
    if available_tokens < min_context:
        logger.warning(f"Calculated context too small ({available_tokens}), using minimum: {min_context}")
        return min_context
    
    logger.info(f"Dynamic context limit for {model}: {available_tokens} tokens")
    return available_tokens

async def summarize_old_messages(client, model: str, messages: list, target_length: int = 3) -> str:
    """오래된 메시지들을 요약하여 컨텍스트 절약"""
    if len(messages) <= target_length:
        return ""
    
    # 요약할 메시지들 (최신 3개 제외)
    messages_to_summarize = messages[:-target_length]
    
    # 요약 내용 구성
    summary_content = ""
    for msg in messages_to_summarize:
        role = "사용자" if msg["role"] == "user" else "AI"
        summary_content += f"{role}: {msg['content'][:200]}{'...' if len(msg['content']) > 200 else ''}\n"
    
    # 요약 생성 프롬프트
    summary_prompt = f"""다음 대화 내용을 핵심만 간단히 요약해주세요 (200자 이내):

{summary_content}

요약 형식: "사용자가 [주제]에 대해 질문했고, AI가 [답변 요약]을 제공했습니다."""
    
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",  # 요약은 빠른 모델 사용
            contents=[summary_prompt],
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=300,
                thinking_config=types.ThinkingConfig(thinking_budget=0)  # 요약은 사고 없이
            )
        )
        
        summary = response.text.strip()
        logger.info(f"Generated conversation summary: {summary[:100]}...")
        return summary
        
    except Exception as e:
        logger.error(f"Failed to generate summary: {e}")
        # Fallback: 간단한 요약
        return f"이전 대화 ({len(messages_to_summarize)}개 메시지): 주요 질문과 답변들"

def apply_sliding_window_with_summary(messages: list, room_id: str, max_messages: int = MAX_MESSAGES_WINDOW) -> list:
    """슬라이딩 윈도우와 요약을 적용한 메시지 관리"""
    
    if len(messages) <= max_messages:
        return messages
    
    # room_id 유효성 검사
    if not room_id or room_id.strip() == "":
        # room_id가 없으면 간단히 최신 메시지만 반환
        logger.warning("No valid room_id provided, using simple sliding window")
        return messages[-max_messages:]
    
    # 캐시 키 생성
    cache_key = f"{room_id}_{len(messages)}"
    
    # 최신 메시지들 유지
    recent_messages = messages[-max_messages:]
    
    # 요약이 필요한 경우
    if len(messages) > SUMMARY_TRIGGER_THRESHOLD:
        # 요약 캐시 확인
        if cache_key not in CONTEXT_SUMMARY_CACHE:
            # 요약 생성 (비동기 처리를 위해 일단 기본 요약 사용)
            old_messages = messages[:-max_messages]
            summary_text = f"[이전 대화 요약: {len(old_messages)}개 메시지]"
            CONTEXT_SUMMARY_CACHE[cache_key] = summary_text
        
        # 요약을 첫 번째 메시지로 추가
        summary_message = {
            "role": "system",
            "content": CONTEXT_SUMMARY_CACHE[cache_key],
            "created_at": messages[0].get("created_at", ""),
            "updated_at": messages[0].get("updated_at", ""),
            "is_summary": True
        }
        
        return [summary_message] + recent_messages
    
    return recent_messages

def intelligent_message_selection(messages: list, max_tokens: int, model: str) -> list:
    """지능형 메시지 선별 (중요도 + 토큰 기반)"""
    if not messages:
        return []
    
    selected_messages = []
    current_tokens = 0
    
    # 최신 3개 메시지는 무조건 포함
    recent_count = min(3, len(messages))
    recent_messages = messages[-recent_count:]
    
    for msg in recent_messages:
        token_info = count_tokens_with_tiktoken(msg.get("content", ""), model)
        current_tokens += token_info["input_tokens"]
    
    # 남은 토큰 예산으로 나머지 메시지 선별
    remaining_messages = messages[:-recent_count] if len(messages) > recent_count else []
    remaining_budget = max_tokens - current_tokens
    
    # 중요도 기반 정렬
    scored_messages = []
    for msg in remaining_messages:
        content = msg.get("content", "")
        score = calculate_message_importance(content, msg.get("role", ""))
        token_info = count_tokens_with_tiktoken(content, model)
        
        scored_messages.append({
            "message": msg,
            "score": score,
            "tokens": token_info["input_tokens"]
        })
    
    # 중요도 순으로 정렬
    scored_messages.sort(key=lambda x: x["score"], reverse=True)
    
    # 토큰 예산 내에서 선별
    for item in scored_messages:
        if current_tokens + item["tokens"] <= remaining_budget:
            selected_messages.append(item["message"])
            current_tokens += item["tokens"]
    
    # 시간순으로 정렬하여 반환
    selected_messages.sort(key=lambda x: x.get("created_at", ""))
    
    return selected_messages + recent_messages

def calculate_message_importance(content: str, role: str) -> float:
    """메시지 중요도 계산"""
    if not content:
        return 0.0
    
    score = 0.0
    
    # 길이 기반 점수 (적당한 길이가 좋음)
    length = len(content)
    if 20 <= length <= 500:
        score += 1.0
    elif length > 500:
        score += 0.7  # 너무 긴 메시지는 약간 감점
    else:
        score += 0.3  # 너무 짧은 메시지는 감점
    
    # 키워드 기반 점수
    important_keywords = [
        "질문", "문제", "오류", "에러", "도움", "설명", "방법", 
        "어떻게", "왜", "무엇", "중요", "핵심", "요약", "결론"
    ]
    keyword_score = sum(0.2 for keyword in important_keywords if keyword in content)
    score += min(keyword_score, 1.5)  # 최대 1.5점
    
    # 역할 기반 점수
    if role == "user":
        score *= 1.3  # 사용자 메시지가 더 중요
    
    # 특수 문자 점수 (질문표, 코드 블록 등)
    if "?" in content or "```" in content:
        score += 0.3
    
    return score

# 함수 호출을 위한 유틸리티 함수들
def create_weather_function():
    """날씨 정보 조회 함수"""
    return {
        "name": "get_weather",
        "description": "지정된 위치의 현재 날씨 정보를 조회합니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "날씨를 조회할 도시 이름 (예: 서울, 부산)",
                },
                "unit": {
                    "type": "string",
                    "enum": ["celsius", "fahrenheit"],
                    "description": "온도 단위 (기본값: celsius)",
                },
            },
            "required": ["location"],
        },
    }

def create_calculator_function():
    """계산기 함수"""
    return {
        "name": "calculate",
        "description": "수학 계산을 수행합니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "계산할 수학 표현식 (예: 2+3*4, sqrt(16))",
                },
            },
            "required": ["expression"],
        },
    }

def create_search_function():
    """검색 함수"""
    return {
        "name": "search_knowledge",
        "description": "지식베이스에서 정보를 검색합니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "검색할 키워드나 질문",
                },
                "category": {
                    "type": "string",
                    "enum": ["academic", "general", "technical"],
                    "description": "검색 카테고리",
                },
            },
            "required": ["query"],
        },
    }

async def execute_function_call(function_name: str, arguments: dict) -> dict:
    """함수 호출 실행"""
    try:
        if function_name == "get_weather":
            location = arguments.get("location", "")
            unit = arguments.get("unit", "celsius")
            # 실제 날씨 API 호출 대신 더미 데이터 반환
            return {
                "location": location,
                "temperature": 22 if unit == "celsius" else 72,
                "unit": unit,
                "description": "맑음",
                "humidity": 65
            }
        
        elif function_name == "calculate":
            expression = arguments.get("expression", "")
            try:
                # 안전한 수학 계산
                import math
                import re
                
                # 허용된 함수들만 사용
                allowed_names = {
                    "sqrt": math.sqrt,
                    "sin": math.sin,
                    "cos": math.cos,
                    "tan": math.tan,
                    "log": math.log,
                    "exp": math.exp,
                    "pow": pow,
                    "abs": abs,
                    "round": round,
                    "pi": math.pi,
                    "e": math.e
                }
                
                # 안전한 표현식인지 확인
                if re.search(r'[a-zA-Z_]', expression):
                    # 함수명이 포함된 경우 허용된 함수인지 확인
                    for name in allowed_names.keys():
                        expression = expression.replace(name, f"allowed_names['{name}']")
                
                result = eval(expression, {"__builtins__": {}, "allowed_names": allowed_names})
                return {"result": result, "expression": arguments.get("expression", "")}
            except Exception as e:
                return {"error": f"계산 오류: {str(e)}", "expression": arguments.get("expression", "")}
        
        elif function_name == "search_knowledge":
            query = arguments.get("query", "")
            category = arguments.get("category", "general")
            # 실제 검색 대신 더미 데이터 반환
            return {
                "query": query,
                "category": category,
                "results": [
                    {"title": f"{query}에 대한 정보", "content": f"{category} 카테고리에서 {query}에 대한 검색 결과입니다."}
                ]
            }
        
        else:
            return {"error": f"알 수 없는 함수: {function_name}"}
    
    except Exception as e:
        return {"error": f"함수 실행 오류: {str(e)}"}

async def generate_gemini_stream_response(
    request: Request,
    messages: list,
    model: str,
    room_id: str,
    db: Session,
    user_id: str,
    file_data_list: Optional[List[str]] = None,
    file_types: Optional[List[str]] = None,
    file_names: Optional[List[str]] = None,
    enable_thinking: bool = True,
    enable_grounding: bool = True,
    enable_code_execution: bool = True,
    thinking_budget: int = 8192
) -> AsyncGenerator[str, None]:
    try:
        client = get_gemini_client()
        if not client:
            raise HTTPException(status_code=500, detail="Gemini client not available")

        config = get_model_config(model)
        if not config or config.provider != ModelProvider.GOOGLE:
            raise HTTPException(status_code=400, detail="Invalid Gemini model")

        # 메시지 유효성 검사
        if not messages or len(messages) == 0:
            raise HTTPException(
                status_code=400,
                detail="At least one message is required"
            )

        # 🚀 새로운 컨텍스트 관리 시스템
        # 1단계: 슬라이딩 윈도우 적용 (최대 15개 메시지)
        messages = apply_sliding_window_with_summary(messages, room_id)
        
        logger.info(f"After sliding window: {len(messages)} messages")
        
        # 2단계: 시스템 프롬프트 토큰 계산 (tiktoken 사용)
        system_tokens = 0
        if config.system_prompt:
            system_token_info = count_tokens_with_tiktoken(config.system_prompt, model)
            system_tokens = system_token_info.get("input_tokens", 0)
        
        # 3단계: 파일 토큰 계산
        file_tokens = 0
        if file_data_list and file_types:
            for file_type in file_types:
                if file_type.startswith("image/"):
                    file_tokens += 258  # Gemini 2.5 기준: 이미지당 258 토큰
                elif file_type == "application/pdf":
                    file_tokens += 258 * 10  # 예상 페이지 수 * 258 토큰
                elif file_type.startswith("video/"):
                    file_tokens += 263 * 60  # 예상 1분 * 263 토큰/초
                elif file_type.startswith("audio/"):
                    file_tokens += 32 * 60   # 예상 1분 * 32 토큰/초
        
        # 4단계: 동적 컨텍스트 한도 계산
        MAX_CONTEXT_TOKENS = get_dynamic_context_limit(model, system_tokens, file_tokens)
        
        # 5단계: 지능형 메시지 선별 (tiktoken 기반)
        available_tokens = MAX_CONTEXT_TOKENS - system_tokens - file_tokens
        valid_messages = intelligent_message_selection(messages, available_tokens, model)
        
        # 최종 토큰 계산
        total_tokens = system_tokens + file_tokens
        for msg in valid_messages:
            if msg.get("content") and msg["content"].strip():
                token_info = count_tokens_with_tiktoken(msg["content"], model)
                total_tokens += token_info["input_tokens"]
        
        # 최소한 하나의 메시지는 포함되어야 함
        if len(valid_messages) == 0 and len(messages) > 0:
            last_msg = messages[-1]
            if last_msg.get("content") and last_msg["content"].strip():
                valid_messages = [last_msg]
        
        if len(valid_messages) == 0:
            raise HTTPException(
                status_code=400,
                detail="No valid message content found"
            )
        
        logger.info(f"Context management: Using {len(valid_messages)} messages with {total_tokens} tokens")

        # 컨텍스트 압축 적용 (필요한 경우)
        if len(valid_messages) > 5:  # 5개 이상 메시지가 있을 때만 압축 고려
            valid_messages = await compress_context_if_needed(
                client=client,
                model=model,
                messages=valid_messages,
                max_tokens=MAX_CONTEXT_TOKENS
            )

        # 컨텐츠 구성
        contents = []
        
        # 파일이 있는 경우 멀티모달 컨텐츠 생성
        if file_data_list and file_types and file_names:
            for file_data, file_type, file_name in zip(file_data_list, file_types, file_names):
                # File API로 업로드된 파일인지 확인
                if file_data.startswith("FILE_API:"):
                    # File API URI에서 파일 이름 추출
                    file_uri = file_data.replace("FILE_API:", "")
                    try:
                        # File API 객체로 직접 추가
                        uploaded_file = client.files.get(name=file_uri)
                        contents.append(uploaded_file)
                        logger.info(f"Added File API file: {file_name} ({file_uri})")
                    except Exception as e:
                        logger.error(f"Failed to get File API file {file_uri}: {e}", exc_info=True)
                        # 폴백: 파일 정보 텍스트로 추가
                        contents.append(f"파일: {file_name} (File API 처리 실패)")
                else:
                    # 기존 base64 방식 처리
                    if file_type.startswith("image/"):
                        contents.append(
                            types.Part.from_bytes(
                                data=base64.b64decode(file_data),
                                mime_type=file_type
                            )
                        )
                    elif file_type == "application/pdf":
                        # PDF 파일 처리
                        pdf_data = base64.b64decode(file_data)
                        contents.append(
                            types.Part.from_bytes(
                                data=pdf_data,
                                mime_type=file_type
                            )
                        )

        # 대화 내용 추가
        conversation_text = ""
        for message in valid_messages:
            role_text = "Human" if message["role"] == "user" else "Assistant"
            conversation_text += f"{role_text}: {message['content']}\n"

        contents.append(conversation_text)

        # 도구 설정 - 최신 API 구조 사용
        tools = []
        
        if enable_grounding:
            # Google 검색 그라운딩 추가 (최신 API 방식)
            tools.append(types.Tool(google_search=types.GoogleSearch()))
        
        if enable_code_execution:
            # 코드 실행 추가
            tools.append(types.Tool(code_execution=types.ToolCodeExecution()))

        # 채팅 세션 관리 (컨텍스트 캐싱 대체)
        chat_session = None
        if room_id:
            chat_session = await get_or_create_chat_session(
                client=client,
                model=model,
                room_id=room_id,
                system_instruction=config.system_prompt
            )

        # 생성 설정 (최적화된 구조)
        generation_config = types.GenerateContentConfig(
            system_instruction=config.system_prompt,
            temperature=config.temperature,
            top_p=config.top_p,
            max_output_tokens=config.max_tokens,
            tools=tools if tools else None
        )

        # 최적화된 사고 기능 설정
        if enable_thinking:
            optimized_thinking_config = await get_optimized_thinking_config(
                model=model,
                request_type="complex" if len(valid_messages) > 5 else "simple",
                user_preference=None  # 향후 사용자 설정에서 가져올 수 있음
            )
            if optimized_thinking_config:
                generation_config.thinking_config = optimized_thinking_config

        # 입력 토큰 계산
        input_token_count = count_tokens_with_tiktoken(conversation_text, model)
        input_tokens = input_token_count.get("input_tokens", 0)

        # 스트리밍 응답 생성 (버퍼링 최적화)
        accumulated_content = ""
        accumulated_thinking = ""
        thought_time = 0.0
        citations = []
        web_search_queries = []
        streaming_completed = False  # 스트리밍 완료 여부 체크
        is_disconnected = False  # 연결 중단 플래그 추가
        
        # 스트리밍 버퍼 초기화
        content_buffer = StreamingBuffer()
        thinking_buffer = StreamingBuffer()

        try:
            response = client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=generation_config
            )

            start_time = time.time()

            for chunk in response:
                # 클라이언트 연결 상태 확인
                if await request.is_disconnected():
                    is_disconnected = True
                    logger.warning("Client disconnected. Stopping stream.")
                    break
                if chunk.candidates and len(chunk.candidates) > 0:
                    candidate = chunk.candidates[0]
                    
                    # 콘텐츠 파트 처리
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            # 사고 내용과 일반 콘텐츠 분리
                            if hasattr(part, 'thought') and part.thought:
                                # 사고 내용만 처리
                                if part.text:
                                    accumulated_thinking += part.text
                                    thought_time = time.time() - start_time
                                    
                                    # 버퍼링된 사고 내용 전송
                                    if thinking_buffer.add_chunk(part.text):
                                        buffered_content = thinking_buffer.flush()
                                        try:
                                            yield f"data: {json.dumps({'reasoning_content': buffered_content, 'thought_time': thought_time})}\n\n"
                                        except (ConnectionError, BrokenPipeError, GeneratorExit):
                                            logger.warning("Client disconnected during reasoning streaming")
                                            return
                            elif part.text:
                                # 일반 응답 내용만 처리
                                accumulated_content += part.text
                                
                                # 버퍼링된 일반 내용 전송
                                if content_buffer.add_chunk(part.text):
                                    buffered_content = content_buffer.flush()
                                    try:
                                        yield f"data: {json.dumps({'content': buffered_content})}\n\n"
                                    except (ConnectionError, BrokenPipeError, GeneratorExit):
                                        logger.warning("Client disconnected during content streaming")
                                        return

                    # 그라운딩 메타데이터 처리 (최신 API 구조)
                    if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                        grounding = candidate.grounding_metadata
                        
                        # 실제 값들 확인
                        logger.debug("=== GROUNDING VALUES DEBUG ===")
                        logger.debug(f"web_search_queries: {getattr(grounding, 'web_search_queries', None)}")
                        logger.debug(f"grounding_chunks: {getattr(grounding, 'grounding_chunks', None)}")
                        logger.debug(f"grounding_supports: {getattr(grounding, 'grounding_supports', None)}")
                        
                        # 웹 검색 쿼리 수집
                        if hasattr(grounding, 'web_search_queries') and grounding.web_search_queries:
                            logger.debug(f"Adding web_search_queries: {grounding.web_search_queries}")
                            web_search_queries.extend(grounding.web_search_queries)
                        
                        # grounding_supports에서 citations 추출 시도
                        if hasattr(grounding, 'grounding_supports') and grounding.grounding_supports:
                            logger.debug(f"Found grounding_supports: {len(grounding.grounding_supports)} supports")
                            new_citations = []
                            for i, support in enumerate(grounding.grounding_supports):
                                logger.debug(f"Support {i}: type={type(support)}, dir={dir(support)}")
                                logger.debug(f"Support {i} content: {support}")
                                
                                # grounding_chunk_indices가 있는지 확인
                                if hasattr(support, 'grounding_chunk_indices') and support.grounding_chunk_indices:
                                    for chunk_idx in support.grounding_chunk_indices:
                                        if (hasattr(grounding, 'grounding_chunks') and 
                                            grounding.grounding_chunks and 
                                            chunk_idx < len(grounding.grounding_chunks)):
                                            chunk = grounding.grounding_chunks[chunk_idx]
                                            logger.debug(f"Referenced chunk {chunk_idx}: {chunk}")
                                            
                                            if hasattr(chunk, 'web') and chunk.web:
                                                citation = {
                                                    "url": getattr(chunk.web, 'uri', ''),
                                                    "title": getattr(chunk.web, 'title', '')
                                                }
                                                logger.debug(f"Extracted citation from support: {citation}")
                                                if citation['url'] and not any(c['url'] == citation['url'] for c in citations):
                                                    citations.append(citation)
                                                    new_citations.append(citation)
                        
                        # 직접 grounding chunks에서도 시도
                        if hasattr(grounding, 'grounding_chunks') and grounding.grounding_chunks:
                            logger.debug(f"Found grounding_chunks: {len(grounding.grounding_chunks)} chunks")
                            new_citations = []
                            for i, chunk in enumerate(grounding.grounding_chunks):
                                logger.debug(f"Direct chunk {i}: {chunk}")
                                if hasattr(chunk, 'web') and chunk.web:
                                    citation = {
                                        "url": getattr(chunk.web, 'uri', ''),
                                        "title": getattr(chunk.web, 'title', '')
                                    }
                                    logger.debug(f"Direct extracted citation: {citation}")
                                    if citation['url'] and not any(c['url'] == citation['url'] for c in citations):
                                        citations.append(citation)
                                        new_citations.append(citation)
                            
                            # 새로운 인용 정보만 전송
                            if new_citations:
                                logger.debug(f"Sending {len(new_citations)} new citations")
                                try:
                                    yield f"data: {json.dumps({'citations': new_citations})}\n\n"
                                except (ConnectionError, BrokenPipeError, GeneratorExit):
                                    logger.warning("Client disconnected during citations streaming")
                                    return
                        
                        # 검색 쿼리 전송
                        if web_search_queries:
                            logger.debug(f"Sending search queries: {web_search_queries}")
                            try:
                                yield f"data: {json.dumps({'search_queries': web_search_queries})}\n\n"
                            except (ConnectionError, BrokenPipeError, GeneratorExit):
                                logger.warning("Client disconnected during search queries streaming")
                                return

            # 연결이 중단되었는지 확인
            if is_disconnected:
                logger.info("Skipping post-processing due to client disconnection.")
                return
            
            # 버퍼에 남은 내용 처리
            remaining_content = content_buffer.flush()
            if remaining_content:
                try:
                    yield f"data: {json.dumps({'content': remaining_content})}\n\n"
                except (ConnectionError, BrokenPipeError, GeneratorExit):
                    logger.warning("Client disconnected during final content flush")
                    return
            
            remaining_thinking = thinking_buffer.flush()
            if remaining_thinking:
                try:
                    yield f"data: {json.dumps({'reasoning_content': remaining_thinking, 'thought_time': thought_time})}\n\n"
                except (ConnectionError, BrokenPipeError, GeneratorExit):
                    logger.warning("Client disconnected during final thinking flush")
                    return
            
            # 스트리밍이 정상적으로 완료됨
            streaming_completed = True
            
            # 출력 토큰 계산
            output_token_count = count_tokens_with_tiktoken(accumulated_content, model)
            output_tokens = output_token_count.get("input_tokens", 0)
            
            # 사고 토큰 계산
            thinking_tokens = 0
            if accumulated_thinking:
                thinking_token_count = count_tokens_with_tiktoken(accumulated_thinking, model)
                thinking_tokens = thinking_token_count.get("input_tokens", 0)

            # 토큰 사용량 저장 (KST 시간으로 저장)
            from pytz import timezone
            kst = timezone('Asia/Seoul')
            crud_stats.create_token_usage(
                db=db,
                user_id=user_id,
                room_id=room_id,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens + thinking_tokens,  # 사고 토큰 포함
                timestamp=datetime.now(kst)
            )

        except (ConnectionError, BrokenPipeError, GeneratorExit):
            streaming_completed = False  # 클라이언트 연결 끊김 시 완료되지 않음
            logger.warning("Client disconnected during main streaming loop")
            return
        except Exception as api_error:
            streaming_completed = False  # 에러 발생 시 완료되지 않음
            error_message = f"Gemini API Error: {str(api_error)}"
            try:
                yield f"data: {json.dumps({'error': error_message})}\n\n"
            except (ConnectionError, BrokenPipeError, GeneratorExit):
                logger.warning("Client disconnected during error streaming")
                return
        
        # 스트리밍이 정상적으로 완료된 경우에만 DB에 저장 (새로운 DB 세션 사용)
        if streaming_completed and accumulated_content:
            logger.debug("=== SAVING MESSAGE DEBUG ===")
            logger.debug(f"streaming_completed: {streaming_completed}")
            logger.debug(f"accumulated_content length: {len(accumulated_content)}")
            logger.debug(f"citations count: {len(citations)}")
            logger.debug(f"citations: {citations}")
            
            # room_id 유효성 검사 (메시지 저장 전)
            if not room_id or room_id.strip() == "" or room_id == "unknown":
                logger.warning(f"Invalid room_id for message saving: {room_id}, skipping save")
            else:
                # 새로운 DB 세션으로 저장 (기존 세션과 분리)
                from app.db.session import SessionLocal
                new_db = SessionLocal()
                try:
                    message_create = ChatMessageCreate(
                        content=accumulated_content,
                        role="assistant",
                        room_id=room_id,
                        reasoning_content=accumulated_thinking if accumulated_thinking else None,
                        thought_time=thought_time if thought_time > 0 else None,
                        citations=citations if citations else None
                    )
                    saved_message = crud_chat.create_message(new_db, room_id, message_create)
                    logger.info(f"Message saved with ID: {saved_message.id}")
                    logger.debug(f"Saved message citations: {saved_message.citations}")
                    logger.debug("=== END SAVING DEBUG ===")
                finally:
                    new_db.close()
        else:
            logger.info("=== MESSAGE NOT SAVED ===")
            logger.info(f"streaming_completed: {streaming_completed}")
            logger.info(f"accumulated_content: {bool(accumulated_content)}")
            logger.info(f"Reason: {'Streaming was interrupted' if not streaming_completed else 'No content'}")
            logger.info("=== END NOT SAVED DEBUG ===")

    except Exception as e:
        error_message = f"Stream Generation Error: {str(e)}"
        try:
            yield f"data: {json.dumps({'error': error_message})}\n\n"
        except (ConnectionError, BrokenPipeError, GeneratorExit):
            logger.warning("Client disconnected during final error streaming (generate_gemini_stream_response)")
            return

async def generate_stream_response(
    request: Request,
    chat_request: ChatRequest,
    file_data_list: Optional[List[str]] = None,
    file_types: Optional[List[str]] = None,
    room_id: Optional[str] = None,
    db: Optional[Session] = None,
    user_id: Optional[str] = None,
    subscription_plan: Optional[str] = None,
    file_names: Optional[List[str]] = None
):
    try:
        config = get_model_config(chat_request.model)
        if not config:
            raise HTTPException(status_code=400, detail="Invalid model specified")

        # 메시지 유효성 검사
        if not chat_request.messages or len(chat_request.messages) == 0:
            raise HTTPException(
                status_code=400,
                detail="At least one message is required"
            )

        # 최근 10개 메시지만 유지
        MAX_MESSAGES = 10
        valid_messages = [
            msg for msg in chat_request.messages[-MAX_MESSAGES:] 
            if msg.content and msg.content.strip()
        ]
        
        if len(valid_messages) == 0:
            raise HTTPException(
                status_code=400,
                detail="No valid message content found"
            )

        # Gemini 모델 처리
        formatted_messages = [
            {"role": msg.role, "content": msg.content} 
            for msg in valid_messages
        ]
        
        # 고급 기능 설정 (구독 등급에 따라 조정 가능)
        enable_thinking = True
        enable_grounding = True
        enable_code_execution = True
        thinking_budget = 8192
        
        if subscription_plan:
            # 구독 등급에 따른 기능 제한 (예시)
            if subscription_plan == "FREE":
                thinking_budget = 1024
                enable_grounding = False
                enable_code_execution = False
            elif subscription_plan == "BASIC":
                thinking_budget = 4096
                enable_grounding = True
                enable_code_execution = False
        
        async for chunk in generate_gemini_stream_response(
            request,
            formatted_messages, 
            chat_request.model, 
            room_id or "", 
            db, 
            user_id or "",
            file_data_list, 
            file_types, 
            file_names,
            enable_thinking=enable_thinking,
            enable_grounding=enable_grounding,
            enable_code_execution=enable_code_execution,
            thinking_budget=thinking_budget
        ):
            yield chunk

    except Exception as e:
        error_message = f"Stream Generation Error: {str(e)}"
        try:
            yield f"data: {json.dumps({'error': error_message})}\n\n"
        except (ConnectionError, BrokenPipeError, GeneratorExit):
            logger.warning("Client disconnected during final error streaming (generate_stream_response)")
            return

async def validate_file(file: UploadFile) -> bool:
    """파일 유효성 검사"""
    if file.size and file.size > MAX_FILE_SIZE:
        return False
    
    # 지원되는 파일 형식 확장
    if file.content_type.startswith("image/"):
        return True
    elif file.content_type == "application/pdf":
        return True
    elif file.content_type in ["text/plain", "text/csv", "application/json"]:
        return True
    elif file.content_type.startswith("text/"):
        return True
    elif file.content_type in ["application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             "application/vnd.openxmlformats-officedocument.presentationml.presentation"]:
        return True
    elif file.content_type.startswith("application/"):
        return True
    
    return False

async def generate_chat_room_name(first_message: str) -> str:
    """Open-WebUI 스타일의 AI 기반 채팅방 제목 생성"""
    try:
        # 빈 메시지 처리
        if not first_message or len(first_message.strip()) == 0:
            return "새 채팅"
        
        # 간단한 fallback 먼저 생성 (AI 실패 시 사용)
        words = first_message.strip().split()
        fallback_title = " ".join(words[:3]) if len(words) >= 3 else " ".join(words)
        if len(fallback_title) > 20:
            fallback_title = fallback_title[:17] + "..."
        
        # Gemini 클라이언트 확인
        client = get_gemini_client()
        if not client:
            logger.info("Gemini client not available, using fallback")
            return fallback_title
        
        # Open-WebUI 스타일의 채팅방 제목 생성 프롬프트
        prompt_template = """Generate a concise and descriptive title in Korean for this chat conversation based on the AI response content.

Requirements:
- Use 2-10 Korean words only
- No emojis or special characters
- Capture the main topic or purpose
- Be specific and informative
- Return only JSON format

Examples:
{{"title": "파이썬 기초 학습"}}
{{"title": "레시피 추천"}}
{{"title": "프로그래밍 질문"}}
{{"title": "일반 대화"}}
{{"title": "인사"}}

AI Response Content: {message}

Generate title as JSON:"""

        # 메시지 길이 제한 (토큰 절약)
        limited_message = first_message[:300] if len(first_message) > 300 else first_message
        
        # 프롬프트 생성
        prompt = prompt_template.format(message=limited_message)
        
        logger.info(f"Generating AI title for response: '{limited_message[:50]}...'")
        
        # Gemini API 호출
        logger.debug(f"Final prompt being sent to Gemini: {repr(prompt)}")
        try:
            logger.info(f"Calling Gemini API with model: gemini-2.0-flash-lite")
            response = client.models.generate_content(
                model="gemini-2.0-flash-lite",
                contents=[prompt],
                config=types.GenerateContentConfig(
                    temperature=0.3,  # 창의적인 제목 생성을 위해 적당한 온도
                    max_output_tokens=50  # 간단한 JSON 응답용
                )
            )
            logger.info(f"API call completed successfully")
            logger.debug(f"Response object: {type(response)}")
            
            # text 속성 확인
            if hasattr(response, 'text'):
                logger.debug(f"Gemini raw response text: {repr(response.text)}")
            
            # candidates 확인
            if hasattr(response, 'candidates'):
                logger.debug(f"Response has {len(response.candidates) if response.candidates else 0} candidates")
            
            # 응답 텍스트 추출 및 JSON 파싱
            response_text = None
            
            # Gemini API 문서에 따른 표준 응답 구조로 텍스트 추출
            # 1. candidates[0].content.parts에서 텍스트 추출 (표준 방법)
            if hasattr(response, 'candidates') and response.candidates and len(response.candidates) > 0:
                candidate = response.candidates[0]  # 첫 번째 후보 사용
                logger.debug(f"Working with candidate: {type(candidate)}")
                
                if hasattr(candidate, 'content') and candidate.content:
                    content = candidate.content
                    logger.debug(f"Content type: {type(content)}")
                    
                    # content.parts 확인
                    if hasattr(content, 'parts'):
                        if content.parts and len(content.parts) > 0:
                            logger.debug(f"Found {len(content.parts)} parts")
                            for i, part in enumerate(content.parts):
                                if hasattr(part, 'text') and part.text:
                                    response_text = part.text
                                    logger.info(f"Got text from part {i}: '{response_text[:100]}...'")
                                    break
                        else:
                            logger.debug("Parts list is empty")
                            # content를 dict로 변환해서 확인
                            try:
                                content_dict = content.model_dump() if hasattr(content, 'model_dump') else content.dict()
                                if 'parts' in content_dict and content_dict['parts']:
                                    for i, part_dict in enumerate(content_dict['parts']):
                                        if 'text' in part_dict and part_dict['text']:
                                            response_text = part_dict['text']
                                            logger.info(f"Got text from dict part {i}: '{response_text[:100]}...'")
                                            break
                            except Exception as e:
                                logger.debug(f"Error converting content to dict: {e}")
                            
                            # content에서 직접 텍스트 찾기
                            if not response_text and hasattr(content, 'text') and content.text:
                                response_text = content.text
                                logger.info(f"Got text from content.text: '{response_text[:100]}...'")
                    else:
                        logger.debug("No parts attribute in content")
                else:
                    logger.debug("No content found in candidate")
            
            # 2. response.text fallback 시도
            elif hasattr(response, 'text') and response.text:
                response_text = response.text
                logger.info(f"Got text from response.text (fallback): '{response_text[:100]}...'")
            
            # 응답 텍스트가 있으면 JSON 파싱 시도
            if response_text:
                try:
                    import json
                    import re
                    
                    # 마크다운 코드 블록 제거
                    text = response_text.strip()
                    if text.startswith('```'):
                        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
                        if json_match:
                            text = json_match.group(1).strip()
                    
                    # JSON 파싱
                    result = json.loads(text)
                    if 'title' in result and result['title']:
                        ai_title = result['title'].strip()
                        if len(ai_title) <= 25:
                            logger.info(f"Successfully generated AI title: '{ai_title}'")
                            return ai_title
                        else:
                            logger.info(f"AI title too long: '{ai_title}'")
                except json.JSONDecodeError as e:
                    logger.debug(f"JSON decode error: {e}, text: '{text[:100]}...'")
                except Exception as e:
                    logger.debug(f"Error parsing response: {e}")
            else:
                logger.debug("Could not extract text from response")
            
        except Exception as api_error:
            logger.info(f"Gemini API call failed: {api_error}")
        
        # AI 생성 실패 시 fallback 사용
        logger.info(f"Using fallback title: '{fallback_title}'")
        return fallback_title
        
            
    except Exception as e:
        logger.error(f"Chat room name generation error: {e}", exc_info=True)
        return "새 채팅"

@router.post("/title/generate", summary="채팅방 제목 생성")
async def generate_title_api(
    request: Request
):
    """Open-WebUI 스타일 채팅방 제목 생성 API"""
    try:
        body = await request.json()
        messages = body.get("messages", [])
        
        if not messages:
            raise HTTPException(
                status_code=400,
                detail="At least one message is required"
            )
        
        # 첫 번째 user 메시지 찾기
        first_user_message = None
        for msg in messages:
            if msg.get("role") == "user" and msg.get("content"):
                first_user_message = msg.get("content")
                break
        
        if not first_user_message:
            raise HTTPException(
                status_code=400,
                detail="No user message found"
            )
        
        # 제목 생성
        title = await generate_chat_room_name(first_user_message)
        
        return {
            "title": title,
            "status": "success"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Title generation API error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error during title generation"
        )

@router.post("/rooms", response_model=ChatRoom, summary="새 채팅방 생성")
def create_chat_room(
    room: ChatRoomCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    새로운 채팅방을 생성합니다.
    
    - **title**: 채팅방 제목 (필수)
    - **model**: 사용할 AI 모델 (필수, 지원되는 모델: gemini-1.5-flash, gemini-1.5-pro, gemini-2.0-flash-exp 등)
    - **system_prompt**: 시스템 프롬프트 (선택)
    - **project_id**: 프로젝트 ID (선택, 프로젝트 내 채팅방인 경우)
    
    **지원되는 AI 모델:**
    - Gemini Flash (빠른 응답)
    - Gemini Pro (고품질 응답)
    - Gemini Flash Thinking (추론 과정 포함)
    
    **응답:**
    - 생성된 채팅방 정보 반환
    """
    return crud_chat.create_chat_room(db, room, current_user.id)

@router.post("/rooms/{room_id}/generate-name")
async def generate_room_name(
    room_id: str,
    message_content: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """첫 번째 메시지를 기반으로 채팅방 이름을 생성하고 업데이트합니다."""
    try:
        logger.info(f"🔍 generate_room_name called - room_id: {room_id}, message: {message_content[:50]}...")
        
        # 채팅방 소유권 확인
        chat_room = crud_chat.get_chat_room(db, room_id, current_user.id)
        if not chat_room:
            logger.info(f"❌ Chat room not found: {room_id} - room may not be created yet")
            return {
                "room_id": room_id,
                "generated_name": "새 채팅",
                "message": "Chat room not found - may not be created yet"
            }
        
        logger.info(f"🔍 Found chat room: {chat_room.id}, current name: '{chat_room.name}'")
        
        # 채팅방 이름이 이미 설정되어 있는지 확인
        try:
            current_name = getattr(chat_room, 'name', None)
            current_name_str = str(current_name) if current_name is not None else ""
        except:
            current_name_str = ""
            
        logger.info(f"🔍 Current name check: '{current_name_str}'")
        
        # "새 채팅"인 경우에만 제목 생성
        if current_name_str and current_name_str.strip() != "" and current_name_str != "새 채팅":
            logger.info(f"⏭️ Room already has a name: '{current_name_str}'")
            return {
                "room_id": room_id,
                "generated_name": current_name_str,
                "message": "Room already has a name"
            }
        
        # 전달받은 메시지 내용으로 제목 생성
        if not message_content or message_content.strip() == "":
            logger.info("❌ Message content is required")
            raise HTTPException(status_code=400, detail="Message content is required")
        
        logger.info(f"🔄 Generating room name for message: '{message_content[:50]}...'")
        
        # AI 기반 제목 생성
        generated_name = await generate_chat_room_name(message_content.strip())
        logger.info(f"🎯 AI generated name: '{generated_name}'")
        
        if not generated_name or generated_name == "새 채팅":
            # AI 생성 실패 시 fallback
            words = message_content.strip().split()
            fallback_title = " ".join(words[:3]) if len(words) >= 3 else message_content.strip()
            if len(fallback_title) > 20:
                fallback_title = fallback_title[:17] + "..."
            generated_name = fallback_title
            logger.info(f"🔄 Using fallback title: '{generated_name}'")
        
        # 채팅방 이름 업데이트
        from app.schemas.chat import ChatRoomCreate
        room_update = ChatRoomCreate(name=generated_name)
        
        logger.info(f"💾 Updating room name to: '{generated_name}'")
        updated_room = crud_chat.update_chat_room(db, room_id, room_update, current_user.id)
        
        logger.info(f"✅ Room name updated: '{generated_name}'")
        
        return {
            "room_id": room_id,
            "generated_name": generated_name,
            "updated_room": updated_room
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Room name generation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate room name")

@router.get("/rooms", response_model=ChatRoomList)
async def get_chatroom(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    rooms = crud_chat.get_chatroom(db, current_user.id)
    return ChatRoomList(rooms=rooms)

@router.delete("/rooms/{room_id}")
async def delete_chat_room(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    crud_chat.delete_chat_room(db, room_id, current_user.id)
    return {"message": "Room deleted successfully"}

@router.post("/rooms/{room_id}/messages")
async def create_message(
    room_id: str,
    message: ChatMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 모델 유효성 검사
    if hasattr(message, 'model') and message.model:
        config = get_model_config(message.model)
        if not config:
            raise HTTPException(status_code=400, detail="Invalid model specified")
    
    # 메시지 생성
    created_message = crud_chat.create_message(db, room_id, message)
    
    # 구독 정보 확인 및 사용량 업데이트
    if hasattr(message, 'model') and message.model:
        updated_subscription = crud_subscription.update_model_usage(
            db, current_user.id, message.model
        )
        
        if not updated_subscription:
            # 생성된 메시지 삭제 (롤백)
            db.delete(created_message)
            db.commit()
            raise HTTPException(
                status_code=403, 
                detail="Usage limit exceeded for this model group"
            )
    
    return created_message

@router.get("/rooms/{room_id}/messages", response_model=ChatMessageList)
async def get_chat_messages(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    messages = crud_chat.get_room_messages(db, room_id, current_user.id)
    return ChatMessageList(messages=messages)

@router.post("/rooms/{room_id}/chat")
async def create_chat_message(
    room_id: str,
    request: Request,
    request_data: str = Form(...),
    files: List[UploadFile] = File([]),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        # JSON 파싱
        try:
            parsed_data = json.loads(request_data)
            chat_request = ChatRequest(**parsed_data)
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON format: {str(e)}")

        # 모델 설정 확인
        config = get_model_config(chat_request.model)
        if not config:
            raise HTTPException(status_code=400, detail="Invalid model specified")

        # 파일 처리
        file_data_list = []
        file_types = []
        file_names = []
        
        if files and files[0].filename:
            if not config.supports_multimodal:
                raise HTTPException(
                    status_code=400,
                    detail="File upload is not supported for this model"
                )
            
            for file in files:
                if not await validate_file(file):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid file: {file.filename}"
                    )
                
                file_data, file_type = await process_file_to_base64(file)
                file_data_list.append(file_data)
                file_types.append(file_type)
                file_names.append(file.filename)

        # 사용자 메시지 저장
        if chat_request.messages:
            last_message = chat_request.messages[-1]
            user_message = ChatMessageCreate(
                content=last_message.content,
                role="user",
                room_id=room_id,
                files=[{
                    "type": file_type,
                    "name": file_name,
                    "data": file_data
                } for file_data, file_type, file_name in zip(file_data_list, file_types, file_names)] if file_data_list else None
            )
            # room_id 검증 후 저장
            if room_id and room_id.strip() != "" and room_id != "unknown":
                crud_chat.create_message(db, room_id, user_message)
            else:
                logger.warning(f"Invalid room_id for user message saving: {room_id}, skipping save")

        # 구독 사용량 업데이트 (crud_subscription 사용)
        updated_subscription = crud_subscription.update_model_usage(
            db, current_user.id, chat_request.model
        )
        
        if not updated_subscription:
            raise HTTPException(
                status_code=403, 
                detail="Usage limit exceeded for this model group"
            )

        # 스트리밍 응답 생성
        return StreamingResponse(
            generate_stream_response(
                request,
                chat_request,
                file_data_list,
                file_types,
                room_id,
                db,
                current_user.id,
                updated_subscription.plan,
                file_names
            ),
            media_type="text/plain"
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.patch("/rooms/{room_id}", response_model=ChatRoom)
async def update_chat_room(
    room_id: str,
    room: ChatRoomCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return crud_chat.update_chat_room(db, room_id, room, current_user.id)

@router.get("/rooms/{room_id}", response_model=ChatRoom)
async def get_chat_room(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return crud_chat.get_chat_room(db, room_id, current_user.id)

# 컨텍스트 캐싱 관련 엔드포인트 추가
@router.post("/cache")
async def create_context_cache(
    content: str = Form(...),
    model: str = Form(...),
    ttl: int = Form(3600),  # 기본 1시간
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """컨텍스트 캐시 생성"""
    try:
        client = get_gemini_client()
        if not client:
            raise HTTPException(status_code=500, detail="Gemini client not available")
        
        # 캐시 생성
        cache = client.caches.create(
            model=model,
            config=types.CreateCachedContentConfig(
                display_name=f"cache_{current_user.id}_{int(time.time())}",
                contents=[content],
                ttl=f"{ttl}s"
            )
        )
        
        return {
            "cache_name": cache.name,
            "ttl": ttl,
            "message": "Cache created successfully"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create cache: {str(e)}")

@router.get("/cache")
async def list_context_caches(
    current_user: User = Depends(get_current_user)
):
    """사용자의 컨텍스트 캐시 목록 조회"""
    try:
        client = get_gemini_client()
        if not client:
            raise HTTPException(status_code=500, detail="Gemini client not available")
        
        caches = []
        for cache in client.caches.list():
            if cache.display_name and cache.display_name.startswith(f"cache_{current_user.id}_"):
                caches.append({
                    "name": cache.name,
                    "display_name": cache.display_name,
                    "model": cache.model,
                    "create_time": cache.create_time.isoformat() if cache.create_time else None,
                    "expire_time": cache.expire_time.isoformat() if cache.expire_time else None
                })
        
        return {"caches": caches}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list caches: {str(e)}")

@router.delete("/cache/{cache_name}")
async def delete_context_cache(
    cache_name: str,
    current_user: User = Depends(get_current_user)
):
    """컨텍스트 캐시 삭제"""
    try:
        client = get_gemini_client()
        if not client:
            raise HTTPException(status_code=500, detail="Gemini client not available")
        
        client.caches.delete(cache_name)
        
        return {"message": "Cache deleted successfully"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete cache: {str(e)}")

@router.get("/stats/token-usage", response_model=List[TokenUsage])
async def get_token_usage(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # KST 시간 문자열을 datetime으로 변환
    start_dt = None
    end_dt = None
    
    if start_date:
        # "YYYY-MM-DD HH:MM:SS" 형식의 KST 시간을 파싱
        start_dt = datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S')
    if end_date:
        # "YYYY-MM-DD HH:MM:SS" 형식의 KST 시간을 파싱
        end_dt = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S')
    
    return crud_stats.get_token_usage(
        db=db,
        start_date=start_dt,
        end_date=end_dt,
        user_id=user_id or current_user.id
    )

@router.get("/stats/chat-usage")
async def get_chat_usage(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # KST 시간 문자열을 datetime으로 변환
    start_dt = None
    end_dt = None
    
    if start_date:
        # "YYYY-MM-DD HH:MM:SS" 형식의 KST 시간을 파싱
        start_dt = datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S')
    if end_date:
        # "YYYY-MM-DD HH:MM:SS" 형식의 KST 시간을 파싱
        end_dt = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S')
    
    return crud_stats.get_chat_statistics(
        db=db,
        start_date=start_dt,
        end_date=end_dt,
        user_id=user_id
    )

@router.get("/stats/token-usage-history")
async def get_token_usage_history(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # KST 시간 문자열을 datetime으로 변환
    start_dt = None
    end_dt = None
    
    if start_date:
        # "YYYY-MM-DD HH:MM:SS" 형식의 KST 시간을 파싱
        start_dt = datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S')
    if end_date:
        # "YYYY-MM-DD HH:MM:SS" 형식의 KST 시간을 파싱
        end_dt = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S')
    
    return crud_stats.get_token_usage_history(
        db=db,
        start=start_dt,
        end=end_dt,
        user_id=user_id
    )

# 임베딩 관련 엔드포인트 추가
@router.post("/embeddings")
async def create_embeddings(
    texts: List[str] = Form(...),
    model: str = Form("text-embedding-004"),
    task_type: str = Form("SEMANTIC_SIMILARITY"),
    current_user: User = Depends(get_current_user)
):
    """텍스트 임베딩 생성"""
    try:
        client = get_gemini_client()
        if not client:
            raise HTTPException(status_code=500, detail="Gemini client not available")
        
        embeddings = []
        for text in texts:
            result = client.models.embed_content(
                model=model,
                contents=text,
                config=types.EmbedContentConfig(task_type=task_type)
            )
            embeddings.append({
                "text": text,
                "embedding": result.embeddings[0] if result.embeddings else []
            })
        
        return {"embeddings": embeddings}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create embeddings: {str(e)}")

# 프롬프트 생성 엔드포인트 개선
@router.post("/generate-prompt")
async def generate_prompt(
    category: str = Form(...),  # 카테고리 (학습, 창작, 분석, 번역, 코딩 등)
    task_description: str = Form(...),  # 작업 설명
    style: str = Form("친근한"),  # 스타일 (친근한, 전문적, 창의적, 간결한)
    complexity: str = Form("중간"),  # 복잡도 (간단, 중간, 고급)
    output_format: str = Form("자유형식"),  # 출력 형식 (자유형식, 단계별, 표형식, 리스트)
    include_examples: bool = Form(True),  # 예시 포함 여부
    include_constraints: bool = Form(False),  # 제약사항 포함 여부
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """개선된 AI 프롬프트 생성기 (로그인 필요)"""
    try:
        client = get_gemini_client()
        if not client:
            raise HTTPException(status_code=500, detail="Gemini client not available")
        
        # 카테고리별 전문 시스템 지시 생성
        category_instructions = {
            "학습": "교육 및 학습 최적화 프롬프트 전문가로서, 학습자의 이해도를 높이고 단계적 학습을 유도하는 프롬프트를 생성합니다.",
            "창작": "창의적 콘텐츠 생성 전문가로서, 상상력을 자극하고 독창적인 결과를 도출하는 프롬프트를 생성합니다.",
            "분석": "데이터 분석 및 논리적 사고 전문가로서, 체계적이고 객관적인 분석을 유도하는 프롬프트를 생성합니다.",
            "번역": "다국어 번역 전문가로서, 문맥과 뉘앙스를 정확히 전달하는 번역 프롬프트를 생성합니다.",
            "코딩": "소프트웨어 개발 전문가로서, 효율적이고 안전한 코드 작성을 유도하는 프롬프트를 생성합니다.",
            "비즈니스": "비즈니스 전략 및 의사결정 전문가로서, 실용적이고 결과 지향적인 프롬프트를 생성합니다.",
            "일반": "범용 프롬프트 엔지니어링 전문가로서, 다양한 상황에 적용 가능한 효과적인 프롬프트를 생성합니다."
        }
        
        # 스타일별 톤 설정
        style_tones = {
            "친근한": "친근하고 접근하기 쉬운 톤으로, 사용자와의 자연스러운 대화를 유도",
            "전문적": "전문적이고 정확한 톤으로, 신뢰성 있는 결과를 제공",
            "창의적": "창의적이고 영감을 주는 톤으로, 혁신적인 아이디어를 자극",
            "간결한": "명확하고 간결한 톤으로, 효율적인 소통을 추구"
        }
        
        # 복잡도별 접근 방식
        complexity_approaches = {
            "간단": "초보자도 쉽게 이해할 수 있는 단순하고 직관적인 접근",
            "중간": "기본 지식을 바탕으로 한 균형잡힌 접근",
            "고급": "전문적 지식과 깊이 있는 분석을 요구하는 고급 접근"
        }
        
        # 출력 형식별 구조
        format_structures = {
            "자유형식": "자연스러운 텍스트 형태로 유연한 응답 구조",
            "단계별": "1단계, 2단계 등 순차적 단계별 응답 구조",
            "표형식": "표나 차트 형태로 정리된 체계적 응답 구조",
            "리스트": "불릿 포인트나 번호 목록 형태의 명확한 응답 구조"
        }
        
        system_instruction = f"""
        당신은 {category_instructions.get(category, category_instructions["일반"])}
        
        프롬프트 생성 원칙:
        1. {style_tones.get(style, style_tones["친근한"])}
        2. {complexity_approaches.get(complexity, complexity_approaches["중간"])}
        3. {format_structures.get(output_format, format_structures["자유형식"])}
        4. 명확한 지시사항과 구체적인 기대 결과를 포함
        5. 사용자의 의도를 정확히 파악하고 최적의 결과를 도출하는 프롬프트 생성
        
        응답 형식:
        - 프롬프트 제목 (간결하고 목적이 명확)
        - 메인 프롬프트 (실제 사용할 완성된 프롬프트)
        - 사용 팁 (효과적인 사용 방법)
        - 변형 제안 (상황에 따른 프롬프트 변형 방법)
        """
        
        user_request = f"""
        다음 조건에 맞는 최적의 프롬프트를 생성해주세요:
        
        📋 **기본 정보**
        - 카테고리: {category}
        - 작업 설명: {task_description}
        - 스타일: {style}
        - 복잡도: {complexity}
        - 출력 형식: {output_format}
        
        📌 **추가 요구사항**
        - 예시 포함: {'예' if include_examples else '아니오'}
        - 제약사항 포함: {'예' if include_constraints else '아니오'}
        
        생성된 프롬프트는 실제 사용 시 바로 복사해서 사용할 수 있도록 완성된 형태로 작성해주세요.
        """
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[user_request],
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.8,  # 창의성을 위해 온도 조금 상승
                max_output_tokens=3000,  # 더 자세한 프롬프트 생성을 위해 토큰 증가
            )
        )
        
        return {
            "generated_prompt": response.text,
            "category": category,
            "task_description": task_description,
            "style": style,
            "complexity": complexity,
            "output_format": output_format,
            "settings": {
                "include_examples": include_examples,
                "include_constraints": include_constraints
            }
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate prompt: {str(e)}")

# 검색 엔드포인트 추가 (스트리밍 버전)
@router.post("/search")
async def search_web(
    request: Request,
    query: str = Form(...),
    room_id: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Google 검색을 사용한 웹 검색 (스트리밍)"""
    try:
        # 사용자 검색 질문을 DB에 저장
        user_message = ChatMessageCreate(
            content=f"🔍 검색: {query}",
            role="user",
            room_id=room_id
        )
        crud_chat.create_message(db, room_id, user_message)
        
        async def generate_search_stream():
            try:
                client = get_gemini_client()
                if not client:
                    yield f"data: {json.dumps({'error': 'Gemini client not available'})}\n\n"
                    return
                
                # 검색 도구 설정 (최신 API 방식)
                tools = [types.Tool(google_search=types.GoogleSearch())]
                
                # 검색을 위한 시스템 지시
                system_instruction = """당신은 검색 전문가입니다. 
                사용자의 검색 쿼리에 대해 정확하고 관련성 높은 정보를 제공하세요.
                검색 결과를 요약하고 출처를 명확히 표시하세요."""
                
                # 생성 설정
                generation_config = types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.7,
                    max_output_tokens=2048,
                    tools=tools
                )
                
                # 스트리밍 검색 실행
                response = client.models.generate_content_stream(
                    model="gemini-2.5-flash",
                    contents=[f"다음에 대해 검색해주세요: {query}"],
                    config=generation_config
                )
                
                accumulated_content = ""
                citations = []
                web_search_queries = []
                citations_sent = set()  # 중복 방지를 위한 set
                search_completed = False  # 검색 완료 여부 체크
                is_disconnected = False  # 연결 중단 플래그 추가
                
                for chunk in response:
                    # 클라이언트 연결 상태 확인
                    if await request.is_disconnected():
                        is_disconnected = True
                        logger.warning("Client disconnected during search. Stopping stream.")
                        break
                    if chunk.candidates and len(chunk.candidates) > 0:
                        candidate = chunk.candidates[0]
                        
                        # 콘텐츠 처리
                        if candidate.content and candidate.content.parts:
                            for part in candidate.content.parts:
                                if part.text:
                                    accumulated_content += part.text
                                    try:
                                        yield f"data: {json.dumps({'content': part.text})}\n\n"
                                    except (ConnectionError, BrokenPipeError, GeneratorExit):
                                        logger.warning("Client disconnected during search content streaming")
                                        return
                        
                        # 그라운딩 메타데이터 처리 (최신 API 구조)
                        if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                            grounding = candidate.grounding_metadata
                            
                            # 디버깅: grounding metadata 구조 확인 (검색용)
                            logger.debug("=== SEARCH GROUNDING METADATA DEBUG ===")
                            logger.debug(f"grounding type: {type(grounding)}")
                            logger.debug(f"grounding dir: {dir(grounding)}")
                            
                            # 웹 검색 쿼리 수집
                            if hasattr(grounding, 'web_search_queries') and grounding.web_search_queries:
                                logger.debug(f"Found web_search_queries: {grounding.web_search_queries}")
                                web_search_queries.extend(grounding.web_search_queries)
                            
                            # grounding chunks에서 citations 추출
                            if hasattr(grounding, 'grounding_chunks') and grounding.grounding_chunks:
                                logger.debug(f"Found grounding_chunks: {len(grounding.grounding_chunks)} chunks")
                                new_citations = []
                                for i, chunk in enumerate(grounding.grounding_chunks):
                                    logger.debug(f"Search Chunk {i}: type={type(chunk)}, dir={dir(chunk)}")
                                    if hasattr(chunk, 'web') and chunk.web:
                                        logger.debug(f"Search Chunk {i} web: type={type(chunk.web)}, dir={dir(chunk.web)}")
                                        citation_url = chunk.web.uri
                                        
                                        # Mixed Content 문제 방지: HTTP URL을 HTTPS로 변환
                                        if citation_url.startswith('http://'):
                                            citation_url = citation_url.replace('http://', 'https://', 1)
                                        
                                        # 중복 방지
                                        if citation_url not in citations_sent:
                                            citation = {
                                                "url": citation_url,
                                                "title": chunk.web.title if hasattr(chunk.web, 'title') else ""
                                            }
                                            logger.debug(f"Search extracted citation: {citation}")
                                            citations.append(citation)
                                            new_citations.append(citation)
                                            citations_sent.add(citation_url)
                                
                                # 새로운 인용 정보만 전송
                                if new_citations:
                                    logger.debug(f"Search sending {len(new_citations)} new citations")
                                    try:
                                        yield f"data: {json.dumps({'citations': new_citations})}\n\n"
                                    except (ConnectionError, BrokenPipeError, GeneratorExit):
                                        logger.warning("Client disconnected during search citations streaming")
                                        return
                
                # 연결이 중단되었는지 확인
                if is_disconnected:
                    logger.info("Skipping search post-processing due to client disconnection.")
                    return
                
                # 검색이 정상적으로 완료됨
                search_completed = True
                
                # 최종 메타데이터 전송
                if web_search_queries:
                    try:
                        yield f"data: {json.dumps({'search_queries': web_search_queries})}\n\n"
                    except (ConnectionError, BrokenPipeError, GeneratorExit):
                        logger.warning("Client disconnected during final search queries streaming")
                        return
                
            except Exception as e:
                search_completed = False  # 에러 발생 시 완료되지 않음
                try:
                    yield f"data: {json.dumps({'error': f'Search failed: {str(e)}'})}\n\n"
                except (ConnectionError, BrokenPipeError, GeneratorExit):
                    logger.warning("Client disconnected during search error streaming")
                    return
            
            # 검색이 정상적으로 완료된 경우에만 DB에 저장
            if search_completed and accumulated_content and room_id and room_id.strip() != "" and room_id != "unknown":
                logger.debug("=== SEARCH SAVING DEBUG ===")
                logger.debug(f"search_completed: {search_completed}")
                logger.debug(f"Saving search response with {len(citations)} citations: {citations}")
                ai_message = ChatMessageCreate(
                    content=accumulated_content,
                    role="assistant",
                    room_id=room_id,
                    citations=citations if citations else None
                )
                saved_message = crud_chat.create_message(db, room_id, ai_message)
                logger.debug(f"Saved message citations: {saved_message.citations}")
                logger.debug("=== END SEARCH SAVING DEBUG ===")
            else:
                logger.info("=== SEARCH MESSAGE NOT SAVED ===")
                logger.info(f"search_completed: {search_completed}")
                logger.info(f"accumulated_content: {bool(accumulated_content)}")
                logger.info(f"Reason: {'Search was interrupted' if not search_completed else 'No content'}")
                logger.info("=== END SEARCH NOT SAVED DEBUG ===")
        
        return StreamingResponse(
            generate_search_stream(),
            media_type="text/plain"
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

async def get_optimized_thinking_config(
    model: str, 
    request_type: str = "normal",
    user_preference: Optional[str] = None
) -> Optional[types.ThinkingConfig]:
    """적응형 사고 설정 생성"""
    if model not in THINKING_OPTIMIZATION:
        return None
    
    config = THINKING_OPTIMIZATION[model]
    
    # 사용자 선호도 기반 조정
    if user_preference == "fast":
        budget = 0  # 빠른 응답
    elif user_preference == "quality":
        budget = config["max_budget"]  # 최고 품질
    else:
        # 적응형 예산 계산
        if request_type == "simple":
            budget = config["default_budget"]
        elif request_type == "complex":
            budget = config["max_budget"] // 2
        else:
            budget = config["default_budget"]
    
    return types.ThinkingConfig(
        thinking_budget=budget,
        include_thoughts=budget > 0
    )

async def get_or_create_chat_session(
    client, 
    model: str, 
    room_id: str,
    system_instruction: Optional[str] = None
):
    """채팅 세션 캐시 관리"""
    cache_key = f"{model}:{room_id}"
    
    # 기존 세션 확인
    if cache_key in CHAT_SESSION_CACHE:
        session_info = CHAT_SESSION_CACHE[cache_key]
        # 세션 만료 확인 (1시간)
        if time.time() - session_info["created_at"] < 3600:
            return session_info["session"]
    
    # 새 세션 생성
    try:
        chat_session = client.chats.create(
            model=model,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction
            ) if system_instruction else None
        )
        
        CHAT_SESSION_CACHE[cache_key] = {
            "session": chat_session,
            "created_at": time.time()
        }
        
        return chat_session
    except Exception as e:
        logger.error(f"Chat session creation error: {e}", exc_info=True)
        return None

async def compress_context_if_needed(
    client,
    model: str,
    messages: List[dict],
    max_tokens: int
) -> List[dict]:
    """컨텍스트 압축 (필요한 경우)"""
    # 토큰 수 계산
    total_tokens = 0
    for msg in messages:
        token_count = count_tokens_with_tiktoken(msg["content"], model)
        total_tokens += token_count.get("input_tokens", 0)
    
    # 압축이 필요한지 확인
    if total_tokens < max_tokens * CONTEXT_COMPRESSION_THRESHOLD:
        return messages
    
    logger.info(f"Context compression needed: {total_tokens} tokens > {max_tokens * CONTEXT_COMPRESSION_THRESHOLD}")
    
    # 최신 메시지는 유지하고 오래된 메시지들을 요약
    keep_recent = 3  # 최근 3개 메시지 유지
    recent_messages = messages[-keep_recent:]
    old_messages = messages[:-keep_recent]
    
    if not old_messages:
        return recent_messages
    
    # 오래된 메시지들을 요약
    try:
        summary_content = "\n".join([
            f"{msg['role']}: {msg['content']}" 
            for msg in old_messages
        ])
        
        summary_response = client.models.generate_content(
            model="gemini-2.5-flash",  # 요약은 빠른 모델 사용
            contents=[f"다음 대화를 간단히 요약해주세요 (핵심 내용만):\n\n{summary_content}"],
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=512,
                thinking_config=types.ThinkingConfig(thinking_budget=0)  # 요약은 사고 없이
            )
        )
        
        # 요약된 메시지로 교체
        compressed_messages = [
            {"role": "system", "content": f"이전 대화 요약: {summary_response.text}"}
        ] + recent_messages
        
        logger.info(f"Context compressed: {len(messages)} -> {len(compressed_messages)} messages")
        return compressed_messages
        
    except Exception as e:
        logger.error(f"Context compression error: {e}", exc_info=True)
        return messages[-keep_recent:]  # 실패시 최근 메시지만 유지

class StreamingBuffer:
    """스트리밍 응답 버퍼링"""
    def __init__(self, buffer_size: int = STREAMING_BUFFER_SIZE):
        self.buffer = []
        self.buffer_size = buffer_size
        self.current_size = 0
        self.last_flush = time.time()
    
    def add_chunk(self, chunk: str) -> bool:
        """청크 추가, 플러시 필요시 True 반환"""
        self.buffer.append(chunk)
        self.current_size += len(chunk.encode('utf-8'))
        
        # 버퍼가 가득 찼거나 일정 시간이 지난 경우 플러시
        now = time.time()
        return (self.current_size >= self.buffer_size or 
                now - self.last_flush >= STREAMING_FLUSH_INTERVAL)
    
    def flush(self) -> str:
        """버퍼 내용 반환 및 초기화"""
        if not self.buffer:
            return ""
        
        content = "".join(self.buffer)
        self.buffer.clear()
        self.current_size = 0
        self.last_flush = time.time()
        return content

# ============================================================================
# 익명 사용자 채팅 관련 함수들
# ============================================================================

def get_client_ip(request: Request) -> str:
    """클라이언트 IP 주소 추출"""
    # X-Forwarded-For 헤더 확인 (프록시/로드밸런서 환경)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # 첫 번째 IP 주소 사용 (원본 클라이언트 IP)
        return forwarded_for.split(",")[0].strip()
    
    # X-Real-IP 헤더 확인 (Nginx 등)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    # 직접 연결된 클라이언트 IP
    return request.client.host if request.client else "unknown"

def generate_anonymous_session_id() -> str:
    """익명 사용자 세션 ID 생성"""
    return str(uuid.uuid4())

async def check_anonymous_rate_limit(
    request: Request, 
    db: Session,
    session_id: str,
    limit: int = 5
) -> tuple[bool, int, str]:
    """
    익명 사용자 사용량 제한 확인
    
    Returns:
        (is_limit_exceeded, current_usage, ip_address)
    """
    ip_address = get_client_ip(request)
    
    # 사용량 확인
    current_usage = crud_anonymous_usage.get_usage_count(db, session_id, ip_address)
    is_limit_exceeded = crud_anonymous_usage.check_usage_limit(db, session_id, ip_address, limit)
    
    return is_limit_exceeded, current_usage, ip_address

async def generate_anonymous_gemini_stream_response(
    request: Request,
    messages: list,
    model: str,
    session_id: str,
    ip_address: str,
    db: Session
) -> AsyncGenerator[str, None]:
    """익명 사용자를 위한 제한된 Gemini 스트리밍 응답"""
    try:
        client = get_gemini_client()
        if not client:
            yield f"data: {json.dumps({'error': 'AI 서비스를 사용할 수 없습니다.'})}\n\n"
            return
        
        # 제한된 시스템 지시 (간단한 답변 유도)
        system_instruction = """당신은 Sungblab AI 교육 어시스턴트입니다. 
학습자가 쉽게 이해할 수 있도록 친근하고 명확한 설명을 제공해주세요.

답변은 500자를 넘지 않도록 간결하게 작성하되, 핵심 내용은 놓치지 않도록 해주세요."""
        
        # 제한된 생성 설정 (비용 절약)
        generation_config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.7,
            max_output_tokens=512,  # 익명 사용자는 짧은 답변만
            # 익명 사용자는 function calling, grounding 등 고급 기능 제한
        )
        
        # 메시지 포맷 변환
        formatted_messages = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            formatted_messages.append({
                "role": role,
                "parts": [{"text": msg["content"]}]
            })
        
        # 스트리밍 응답 생성
        response = client.models.generate_content_stream(
            model=model,
            contents=formatted_messages,
            config=generation_config
        )
        
        accumulated_content = ""
        
        for chunk in response:
            # 클라이언트 연결 상태 확인
            if await request.is_disconnected():
                logger.warning("Anonymous client disconnected. Stopping stream.")
                break
                
            if chunk.candidates and len(chunk.candidates) > 0:
                candidate = chunk.candidates[0]
                
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.text:
                            accumulated_content += part.text
                            try:
                                yield f"data: {json.dumps({'content': part.text})}\n\n"
                            except (ConnectionError, BrokenPipeError, GeneratorExit):
                                logger.warning("Anonymous client disconnected during streaming")
                                return
        
        # 사용량 증가 (성공적으로 응답이 완료된 경우에만)
        if accumulated_content.strip():
            crud_anonymous_usage.increment_usage(db, session_id, ip_address)
            
    except Exception as e:
        logger.error(f"Anonymous chat error: {e}", exc_info=True)
        yield f"data: {json.dumps({'error': '죄송합니다. 일시적인 오류가 발생했습니다.'})}\n\n"


# ============================================================================
# 익명 사용자 API 엔드포인트들
# ============================================================================

@router.post("/anonymous-chat")
async def anonymous_chat(
    request: Request,
    session_id: str = Form(...),
    message: str = Form(...),
    model: str = Form("gemini-2.5-flash"),  # 익명 사용자는 Flash 모델만
    db: Session = Depends(get_db)
):
    """익명 사용자를 위한 채팅 엔드포인트 (로그인 불필요, 5회 제한)"""
    
    try:
        # 입력 검증
        if not message.strip():
            raise HTTPException(status_code=400, detail="메시지를 입력해주세요.")
        
        if len(message) > 2000:  # 익명 사용자는 짧은 메시지만
            raise HTTPException(status_code=400, detail="메시지가 너무 깁니다. (최대 2000자)")
        
        # 세션 ID 검증
        try:
            uuid.UUID(session_id)  # 유효한 UUID인지 확인
        except ValueError:
            raise HTTPException(status_code=400, detail="잘못된 세션 ID입니다.")
        
        # 사용량 제한 확인
        is_limit_exceeded, current_usage, ip_address = await check_anonymous_rate_limit(
            request, db, session_id
        )
        
        if is_limit_exceeded:
            raise HTTPException(
                status_code=429, 
                detail={
                    "message": "익명 채팅 횟수를 모두 사용했습니다. 회원가입하고 더 많은 기능을 이용해보세요!",
                    "current_usage": current_usage,
                    "limit": 5
                }
            )
        
        # 허용된 모델인지 확인 (익명 사용자는 Flash만)
        if model not in ["gemini-2.5-flash"]:
            model = "gemini-2.5-flash"
        
        # 간단한 메시지 히스토리 (최근 5개만)
        messages = [
            {"role": "user", "content": message}
        ]
        
        # 스트리밍 응답 생성
        async def generate_anonymous_stream():
            async for chunk in generate_anonymous_gemini_stream_response(
                request, messages, model, session_id, ip_address, db
            ):
                yield chunk
        
        return StreamingResponse(
            generate_anonymous_stream(),
            media_type="text/plain",
            headers={
                "X-Anonymous-Usage": str(current_usage + 1),
                "X-Anonymous-Limit": "5"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Anonymous chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다.")


@router.get("/anonymous-usage/{session_id}")
@retry_db_operation(max_retries=3, delay=1.0)
async def get_anonymous_usage(
    request: Request,
    session_id: str,
    db: Session = Depends(get_robust_db)
):
    """익명 사용자의 현재 사용량 조회"""
    
    try:
        # 세션 ID 검증
        try:
            uuid.UUID(session_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="잘못된 세션 ID입니다.")
        
        ip_address = get_client_ip(request)
        current_usage = crud_anonymous_usage.get_usage_count(db, session_id, ip_address)
        
        return {
            "session_id": session_id,
            "current_usage": current_usage,
            "limit": 5,
            "remaining": max(0, 5 - current_usage),
            "is_limit_exceeded": current_usage >= 5
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Anonymous usage check error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="사용량 조회 중 오류가 발생했습니다.")


@router.post("/anonymous-session")
async def create_anonymous_session(request: Request):
    """새로운 익명 세션 ID 생성"""
    
    try:
        session_id = generate_anonymous_session_id()
        ip_address = get_client_ip(request)
        
        return {
            "session_id": session_id,
            "ip_address": ip_address,  # 디버깅용 (실제 서비스에서는 제거)
            "limit": 5,
            "message": "익명 세션이 생성되었습니다. 5번의 무료 채팅을 이용하실 수 있습니다."
        }
        
    except Exception as e:
        logger.error(f"Anonymous session creation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="세션 생성 중 오류가 발생했습니다.")


# 관리자용 엔드포인트 (선택적)
@router.get("/admin/anonymous-stats")
async def get_anonymous_stats(
    date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """익명 사용자 통계 조회 (관리자만)"""
    
    # 관리자 권한 확인 (필요에 따라 수정)
    if not current_user.email.endswith("@admin.com"):  # 실제 관리자 조건으로 수정
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    
    try:
        target_date = None
        if date:
            target_date = datetime.fromisoformat(date)
            
        stats = crud_anonymous_usage.get_daily_stats(db, target_date)
        return stats
        
    except Exception as e:
        logger.error(f"Anonymous stats error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="통계 조회 중 오류가 발생했습니다.")


# 프롬프트 개선 API (일반 채팅용)
@router.post("/improve-prompt")
async def improve_chat_prompt(
    original_prompt: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """사용자 프롬프트를 AI가 개선하여 반환합니다 (일반 채팅용)."""
    try:
        # Gemini 2.0 Flash-Lite 클라이언트 초기화
        client = genai.Client(api_key=settings.GEMINI_API_KEY)

        # 프롬프트 개선을 위한 시스템 프롬프트
        improvement_prompt = """당신은 프롬프트 최적화 전문가입니다. 사용자가 제공한 원본 프롬프트를 분석하고, 더 명확하고 효과적인 프롬프트로 개선해주세요.

## 개선 원칙:
1. **명확성**: 모호한 표현을 구체적으로 개선
2. **구조화**: 요청사항을 논리적으로 정리
3. **맥락 제공**: 필요한 배경 정보 추가
4. **구체성**: 추상적 요청을 구체적으로 변환
5. **실행 가능성**: AI가 수행할 수 있는 형태로 조정

## 개선 방법:
- 핵심 의도는 유지하면서 표현 방식 개선
- 단계별 요청이 필요한 경우 순서 명시
- 예시나 형식이 필요한 경우 구체적으로 제시
- 너무 길어지지 않도록 간결하게 유지

사용자의 원본 프롬프트를 개선된 버전으로만 응답해주세요. 설명이나 부가 내용 없이 개선된 프롬프트만 제공하세요."""

        # 개선 요청 메시지 구성 (Gemini API v2.5 형식)
        content_text = f"다음 프롬프트를 개선해주세요:\n\n{original_prompt}"

        # Gemini 2.0 Flash-Lite로 프롬프트 개선 요청
        response = client.models.generate_content(
            model="gemini-2.0-flash-lite",
            contents=[content_text],
            config=types.GenerateContentConfig(
                system_instruction=improvement_prompt,
                temperature=0.3,
                max_output_tokens=2048
            )
        )

        if not response.text:
            raise HTTPException(status_code=500, detail="Failed to improve prompt")

        improved_prompt = response.text.strip()
        
        return {
            "original_prompt": original_prompt,
            "improved_prompt": improved_prompt,
            "status": "success"
        }

    except Exception as e:
        logger.error(f"프롬프트 개선 실패: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"프롬프트 개선에 실패했습니다: {str(e)}"
        )
