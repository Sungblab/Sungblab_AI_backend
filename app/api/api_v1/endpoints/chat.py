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

async def count_gemini_tokens(text: str, model: str, client) -> dict:
    """정확한 Gemini 모델의 토큰 수를 계산합니다."""
    try:
        result = client.models.count_tokens(
            model=model,
            contents=text
        )
        return {
            "input_tokens": result.total_tokens,
            "output_tokens": 0
        }
    except Exception as e:
        logger.error(f"Gemini token counting error: {e}", exc_info=True)
        return {
            "input_tokens": len(text) // 4,  # 대략적인 토큰 계산
            "output_tokens": 0
        }

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

        # 토큰 기반 컨텍스트 관리
        # 모델의 최대 토큰 수 가져오기 (출력 토큰을 위한 여유 공간 확보)
        MAX_CONTEXT_TOKENS = config.max_tokens - 2048  # 출력을 위한 2048 토큰 예약
        
        # 메시지를 역순으로 처리하여 최근 메시지부터 포함
        valid_messages = []
        total_tokens = 0
        
        # 시스템 프롬프트 토큰 계산
        if config.system_prompt:
            system_tokens = await count_gemini_tokens(config.system_prompt, model, client)
            total_tokens += system_tokens.get("input_tokens", 0)
        
        # 파일 토큰 계산 (있는 경우)
        file_tokens = 0
        if file_data_list and file_types:
            # 이미지는 타일당 258 토큰, PDF는 페이지당 258 토큰
            for file_type in file_types:
                if file_type.startswith("image/"):
                    file_tokens += 258  # Gemini 2.5 기준
                elif file_type == "application/pdf":
                    file_tokens += 258 * 10  # 예상 페이지 수
        
        total_tokens += file_tokens
        
        # 메시지를 역순으로 검토하면서 토큰 예산 내에서 포함
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if msg.get("content") and msg["content"].strip():
                # 메시지 토큰 계산
                msg_tokens = await count_gemini_tokens(
                    f"{msg['role']}: {msg['content']}", 
                    model, 
                    client
                )
                msg_token_count = msg_tokens.get("input_tokens", 0)
                
                # 토큰 예산 확인
                if total_tokens + msg_token_count <= MAX_CONTEXT_TOKENS:
                    valid_messages.insert(0, msg)
                    total_tokens += msg_token_count
                else:
                    # 토큰 한계에 도달하면 중단
                    logger.info(f"Context window limit reached. Including {len(valid_messages)} messages out of {len(messages)}")
                    break
        
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
        input_token_count = await count_gemini_tokens(conversation_text, model, client)
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
            output_token_count = await count_gemini_tokens(accumulated_content, model, client)
            output_tokens = output_token_count.get("input_tokens", 0)
            
            # 사고 토큰 계산
            thinking_tokens = 0
            if accumulated_thinking:
                thinking_token_count = await count_gemini_tokens(accumulated_thinking, model, client)
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
            logger.warning("Gemini client not available, using fallback")
            return fallback_title
        
        # 개선된 프롬프트 템플릿
        prompt_template = """사용자 메시지를 분석해서 대화 주제를 나타내는 간결한 한국어 제목을 만드세요.

규칙:
- 3-5단어 + 이모지 1개
- 대화 주제나 질문 내용을 요약
- 단순한 인사말("안녕", "하이", "헬로", "hi" 등)은 반드시 "💬 일반 대화"로 처리
- 의미있는 내용이 있을 때만 구체적인 제목 생성
- JSON 형식으로만 응답

예시:
{{"title": "📚 파이썬 학습 질문"}}
{{"title": "🍕 요리 레시피 문의"}}
{{"title": "💻 프로그래밍 도움"}}
{{"title": "💬 일반 대화"}}

특별 처리:
- "안녕", "하이", "헬로", "hi", "hello" 등 → {{"title": "💬 일반 대화"}}
- 단순 인사 이외의 의미있는 내용 → 구체적인 제목 생성

사용자 메시지: {message}

JSON 응답:"""

        # 메시지 길이 제한 (토큰 절약)
        limited_message = first_message[:200] if len(first_message) > 200 else first_message
        
        # 프롬프트 생성
        prompt = prompt_template.format(message=limited_message)
        
        logger.info(f"Generating AI title for message: '{limited_message[:50]}...'")
        
        # Gemini API 호출
        logger.info(f"Final prompt being sent to Gemini: {repr(prompt)}")
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[prompt],
                config=types.GenerateContentConfig(
                    temperature=0.1,  # 일관된 결과를 위해 낮은 온도
                    max_output_tokens=100  # JSON 응답용
                )
            )
            logger.info(f"Gemini raw response: {repr(response.text)}")
            
            # JSON 응답 파싱 (마크다운 코드 블록 제거)
            if hasattr(response, 'text') and response.text:
                import json
                import re
                try:
                    # 마크다운 코드 블록 제거 (```json ... ``` 형태)
                    text = response.text.strip()
                    if text.startswith('```'):
                        # 코드 블록에서 JSON 부분만 추출
                        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
                        if json_match:
                            text = json_match.group(1).strip()
                    
                    result = json.loads(text)
                    if 'title' in result and result['title']:
                        ai_title = result['title'].strip()
                        # 길이 제한 확인
                        if len(ai_title) <= 25:
                            logger.info(f"✓ AI generated title: '{ai_title}'")
                            return ai_title
                        else:
                            logger.warning(f"AI title too long: '{ai_title}', using fallback")
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse JSON response: {e}, response: '{response.text}'")
            
            # candidates 구조 시도 (마크다운 코드 블록 제거)
            if hasattr(response, 'candidates') and response.candidates:
                for candidate in response.candidates:
                    if hasattr(candidate, 'content') and candidate.content:
                        if hasattr(candidate.content, 'parts') and candidate.content.parts:
                            for part in candidate.content.parts:
                                if hasattr(part, 'text') and part.text:
                                    try:
                                        import json
                                        import re
                                        # 마크다운 코드 블록 제거
                                        text = part.text.strip()
                                        if text.startswith('```'):
                                            json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
                                            if json_match:
                                                text = json_match.group(1).strip()
                                        
                                        result = json.loads(text)
                                        if 'title' in result and result['title']:
                                            ai_title = result['title'].strip()
                                            if len(ai_title) <= 25:
                                                logger.info(f"✓ AI generated title from candidates: '{ai_title}'")
                                                return ai_title
                                    except json.JSONDecodeError:
                                        continue
            
        except Exception as api_error:
            logger.warning(f"Gemini API call failed: {api_error}")
        
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
        # 채팅방 소유권 확인
        chat_room = crud_chat.get_chat_room(db, room_id, current_user.id)
        if not chat_room:
            raise HTTPException(status_code=404, detail="Chat room not found")
        
        # 채팅방 이름 생성
        generated_name = await generate_chat_room_name(message_content)
        
        # 채팅방 이름 업데이트
        from app.schemas.chat import ChatRoomCreate
        room_update = ChatRoomCreate(
            name=generated_name
        )
        
        updated_room = crud_chat.update_chat_room(db, room_id, room_update, current_user.id)
        
        return {
            "room_id": room_id,
            "generated_name": generated_name,
            "updated_room": updated_room
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Room name generation error: {e}", exc_info=True)
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
            crud_chat.create_message(db, room_id, user_message)

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
            if search_completed and accumulated_content:
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
        token_count = await count_gemini_tokens(msg["content"], model, client)
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
async def get_anonymous_usage(
    request: Request,
    session_id: str,
    db: Session = Depends(get_db)
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
