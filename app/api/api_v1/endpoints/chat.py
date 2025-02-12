from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.schemas.chat import (
    ChatRoom, ChatRoomCreate, ChatRoomList, 
    ChatMessageCreate, ChatMessage, ChatMessageList,
    ChatRequest, TokenUsage, PromptGenerateRequest
)
from app.crud import crud_chat, crud_stats, crud_project, crud_subscription
from app.db.session import get_db
from app.core.security import get_current_user
from app.models.user import User
import anthropic
import json
from anthropic import Anthropic, AsyncAnthropic
from app.core.config import settings
import logging
import asyncio
import base64
from typing import Optional, List, AsyncGenerator, Dict, Any, Sequence
import shutil
import tempfile
import os
from pydantic import BaseModel
import PyPDF2
from io import BytesIO
from PIL import Image
from datetime import datetime, timedelta
from app.models.subscription import Subscription
import httpx
from openai import AsyncOpenAI
import time
import tiktoken
from functools import lru_cache
import google.generativeai as genai
# LangGraph imports
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolExecutor
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from typing import TypedDict, Union

router = APIRouter()
client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

class ChatState(TypedDict):
    """채팅 상태를 정의하는 클래스"""
    messages: Sequence[BaseMessage]
    next: Optional[str]

class SharedChatMemory:
    """모든 모델이 공유하는 대화 메모리 클래스"""
    _instances: Dict[str, Dict[str, Any]] = {}  # 채팅방 ID별 상태 저장

    @classmethod
    def get_instance(cls, room_id: str) -> 'SharedChatMemory':
        """싱글톤 패턴: 채팅방별로 하나의 메모리 인스턴스만 생성"""
        if room_id not in cls._instances:
            cls._instances[room_id] = cls(room_id)
        return cls._instances[room_id]

    def __init__(self, room_id: str):
        self.room_id = room_id
        self.state: ChatState = {
            "messages": [],
            "next": None
        }
        
    def add_message(self, role: str, content: str):
        """메시지 추가"""
        if role == "user":
            message = HumanMessage(content=content)
        elif role == "assistant":
            message = AIMessage(content=content)
        else:
            return
        
        self.state["messages"] = list(self.state["messages"]) + [message]

    def get_messages(self) -> List[Dict[str, str]]:
        """현재 메모리의 모든 메시지 반환"""
        return [
            {
                "role": "user" if isinstance(msg, HumanMessage) else "assistant",
                "content": msg.content
            }
            for msg in self.state["messages"]
        ]

    def clear(self):
        """메모리 초기화"""
        self.state["messages"] = []
        self.state["next"] = None

# 토큰 관련 상수 정의
TOKEN_ENCODINGS = {
    "sonar-pro": "cl100k_base",
    "sonar": "cl100k_base",
    "sonar-reasoning-pro": "cl100k_base",
    "sonar-reasoning": "cl100k_base",
    "deepseek-reasoner": "cl100k_base",
    "deepseek-chat": "cl100k_base",
    "gemini-2.0-flash": "cl100k_base"  # Gemini 모델 토큰 인코딩 추가
}

# DeepSeek 관련 상수 추가
DEEPSEEK_MODELS = ["deepseek-reasoner", "deepseek-chat"]
DEEPSEEK_DEFAULT_CONFIG = {
    "deepseek-reasoner": {
        "temperature": 0.7,
        "max_tokens": 2048,
        "top_p": 0.95,
        "stream": True
    },
    "deepseek-chat": {
        "temperature": 0.7,
        "max_tokens": 2048,
        "top_p": 0.95,
        "stream": True
    }
}

# DeepSeek 토큰 제한
DEEPSEEK_MAX_TOKENS = {
    "deepseek-reasoner": {
        "max_total_tokens": 16384,
        "max_input_tokens": 8192,
        "max_output_tokens": 8192
    },
    "deepseek-chat": {
        "max_total_tokens": 16384,
        "max_input_tokens": 8192,
        "max_output_tokens": 8192
    }
}

def get_deepseek_client():
    """DeepSeek 클라이언트를 생성하는 함수"""
    api_key = settings.DEEPSEEK_API_KEY
    
    if not api_key:
        return None
        
    try:
        client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com"
        )
        return client
    except Exception as e:
        return None

# Gemini 관련 상수 업데이트
GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite-preview-02-05",
    "gemini-2.0-pro-exp-02-05",
    "gemini-2.0-flash-thinking-exp-01-21"
]

GEMINI_DEFAULT_CONFIG = {
    "gemini-2.0-flash": {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 40,
        "max_output_tokens": 8192,
    },
    "gemini-2.0-flash-lite-preview-02-05": {
        "temperature": 0.9,
        "top_p": 0.95,
        "top_k": 40,
        "max_output_tokens": 4096,
    },
    "gemini-2.0-pro-exp-02-05": {
        "temperature": 0.7,
        "top_p": 0.95,
        "top_k": 40,
        "max_output_tokens": 8192,
    },
    "gemini-2.0-flash-thinking-exp-01-21": {
        "temperature": 0.8,
        "top_p": 0.95,
        "top_k": 40,
        "max_output_tokens": 4096,
    }
}

# 허용된 모델 리스트 업데이트
ALLOWED_MODELS = [
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    "sonar-pro",
    "sonar",
    "sonar-reasoning-pro", 
    "sonar-reasoning",
    "deepseek-reasoner",
    "deepseek-chat",
    "gemini-2.0-flash"  # Gemini 모델 추가
]
MULTIMODAL_MODELS = ["claude-3-5-sonnet-20241022"]  # 멀티모달을 지원하는 모델 리스트

# Sonar 관련 상수 추가
SONAR_MODELS = ["sonar-pro", "sonar", "sonar-reasoning-pro", "sonar-reasoning"]
SONAR_API_URL = "https://api.perplexity.ai/chat/completions"
ALL_ALLOWED_MODELS = ALLOWED_MODELS + SONAR_MODELS

# Sonar 기본 설정
SONAR_DEFAULT_CONFIG = {
    "temperature": 0.5,
    "top_p": 0.9,
    "frequency_penalty": 1,
    "presence_penalty": 0,
    "return_images": False,
    "return_related_questions": False
}

MAX_FILE_SIZE = 32 * 1024 * 1024  # 32MB
MAX_PDF_PAGES = 100
MAX_IMAGE_DIMENSION = 8000

# 시스템 프롬프트 상수 정의
BRIEF_SYSTEM_PROMPT = """당신은 학생을 위한 'Sungblab AI' 교육 어시스턴트입니다.
답변은 적절한 마크다운을 적용해 주세요
답변 형식은 '설명적'으로 요약하지 말고 풀어서 종결어미로 답하세요."""

DETAILED_SYSTEM_PROMPT = """[역할 & 목적]
- 수행평가 과제(보고서/발표) 작성 지원
- 생기부(세특) 작성 가이드
- 학습 관련 질문 해결 및 심화 학습 유도
[행동 지침]
- 학생 수준에 따라 설명과 예시
- 자기주도적 탐구 유도
- 교육적인 피드백 제공
"""

# DeepSeek Chat 모델용 시스템 프롬프트
DEEPSEEK_CHAT_SYSTEM_PROMPT = """당신은 학생을 위한 'Sungblab AI' 교육 어시스턴트입니다.
LaTeX 사용시 무조건 모든 수학 수식마다 빠지지 않고 달러 기호($)로 감싸서 표현하세요."""

# Gemini 모델용 시스템 프롬프트 추가
GEMINI_SYSTEM_PROMPT = """당신은 학생을 위한 'Sungblab AI' 교육 어시스턴트입니다.

[답변 지침]
1. 마크다운 형식 사용
2. 수학 수식은 LaTeX로 표현 ($로 감싸기)
"""

# 토큰 카운팅 관련 함수들
@lru_cache(maxsize=1000)
def count_tokens_cached(text: str, model: str) -> int:
    """캐시된 토큰 카운팅"""
    return count_tokens_for_model(text, model)

def count_tokens_for_model(text: str, model: str) -> int:
    """모델별 토큰 수 계산"""
    try:
        if model in TOKEN_ENCODINGS:
            encoding = tiktoken.get_encoding(TOKEN_ENCODINGS[model])
            tokens = len(encoding.encode(text))
            
            # DeepSeek 모델의 경우 토큰 제한 확인
            if model in DEEPSEEK_MODELS:
                max_tokens = DEEPSEEK_MAX_TOKENS[model]["max_total_tokens"]
                if tokens > max_tokens:
                    print(f"Warning: Token count {tokens} exceeds model limit {max_tokens}")
            
            return tokens
        else:
            return 0  # Claude 모델은 자체 카운팅 사용
            
    except Exception as e:
        return 0

def count_messages_tokens(messages: list, model: str) -> int:
    """메시지 리스트의 전체 토큰 수 계산"""
    try:
        return sum(count_tokens_cached(msg["content"], model) for msg in messages if msg.get("content"))
    except Exception as e:
        return 0

async def process_file_to_base64(file: UploadFile) -> tuple[str, str]:
    try:
        # 파일 내용을 메모리에 읽기
        contents = await file.read()
        base64_data = base64.b64encode(contents).decode('utf-8')
        return base64_data, file.content_type
    except Exception as e:
        raise

async def count_tokens(
    request: ChatRequest,
    file_data_list: Optional[List[str]] = None,
    file_types: Optional[List[str]] = None,
) -> int:
    try:
        # Sonar 모델인 경우 토큰 계산 하지 않음
        if request.model in SONAR_MODELS:
            return 0

        # Claude 모델인 경우 기존 로직 사용
        messages = []
        if file_data_list and file_types and request.model in MULTIMODAL_MODELS:
            content = []
            for file_data, file_type in zip(file_data_list, file_types):
                content_type = "image" if file_type.startswith("image/") else "document"
                content.append({
                    "type": content_type,
                    "source": {
                        "type": "base64",
                        "media_type": file_type,
                        "data": file_data,
                    },
                })
            
            user_message = {
                "role": "user",
                "content": content
            }
            
            if request.messages and request.messages[-1].content:
                user_message["content"].append({
                    "type": "text",
                    "text": request.messages[-1].content
                })
            
            messages = request.messages[:-1] if request.messages else []
            messages.append(user_message)
        else:
            messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]

        # 시스템 메시지 구성 - 간단한 버전만 포함
        system_blocks = [
            {
                "type": "text",
                "text": BRIEF_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"}
            }
        ]

        # 비동기 호출을 await로 처리
        response = await client.messages.count_tokens(
            model=request.model,
            messages=messages,
            system=system_blocks
        )
        return response.input_tokens
    except Exception as e:
        return 0

async def generate_sonar_stream_response(
    messages: list,
    model: str,
    room_id: str,
    db: Session,
    user_id: str
) -> AsyncGenerator[str, None]:
    try:
        # 입력 토큰 계산
        input_tokens = count_messages_tokens(messages, model)

        headers = {
            "Authorization": f"Bearer {settings.SONAR_API_KEY}",
            "Content-Type": "application/json"
        }

        formatted_messages = []
        for i, msg in enumerate(messages):
            if i == 0 and msg["role"] == "assistant":
                continue
            if i > 0 and msg["role"] == messages[i-1]["role"]:
                continue
            formatted_messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

        payload = {
            "model": model,
            "messages": formatted_messages,
            "stream": True,
            **SONAR_DEFAULT_CONFIG
        }

        accumulated_content = ""
        citations = []
        
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", SONAR_API_URL, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Sonar API Error: {error_text}"
                    )

                async for line in response.aiter_lines():
                    if line.strip():
                        if line.startswith("data: "):
                            try:
                                data = json.loads(line[6:])
                                if "choices" in data and len(data["choices"]) > 0:
                                    delta = data["choices"][0].get("delta", {})
                                    if "content" in delta:
                                        content_chunk = delta["content"]
                                        accumulated_content += content_chunk
                                        yield f"data: {json.dumps({'content': content_chunk})}\n\n"

                                if "citations" in data:
                                    citations = [{"url": url} for url in data["citations"]]
                                    if citations:
                                        yield f"data: {json.dumps({'citations': citations})}\n\n"

                            except json.JSONDecodeError:
                                continue

        # 출력 토큰 계산 및 저장
        output_tokens = count_tokens_cached(accumulated_content, model)

        # 토큰 사용량 저장
        crud_stats.create_token_usage(
            db=db,
            user_id=user_id,
            room_id=room_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            timestamp=datetime.now()
        )

        # AI 응답 메시지 저장
        if accumulated_content:
            message_create = ChatMessageCreate(
                content=accumulated_content,
                role="assistant",
                room_id=room_id,
                citations=citations
            )
            crud_chat.create_message(db, room_id, message_create)

    except Exception as e:
        error_message = f"Sonar API Error: {str(e)}"
        yield f"data: {json.dumps({'error': error_message})}\n\n"

async def generate_deepseek_stream_response(
    messages: list,
    model: str,
    room_id: str,
    db: Session,
    user_id: str
) -> AsyncGenerator[str, None]:
    try:
        # 입력 토큰 계산
        input_tokens = count_messages_tokens(messages, model)

        client = get_deepseek_client()
        if not client:
            raise HTTPException(
                status_code=500,
                detail="DeepSeek API key is not configured"
            )

        request_start_time = time.time()
        content = ""
        reasoning_content = ""

        # 시스템 프롬프트를 첫 번째 메시지로 추가
        formatted_messages = [
            {"role": "system", "content": DEEPSEEK_CHAT_SYSTEM_PROMPT}
        ]
        formatted_messages.extend(messages)

        stream = await client.chat.completions.create(
            model=model,
            messages=formatted_messages,
            **DEEPSEEK_DEFAULT_CONFIG[model]
        )

        async for chunk in stream:
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                
                if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                    reasoning_content += delta.reasoning_content
                    
                    response_data = {
                        "role": "assistant",
                        "reasoning_content": reasoning_content,
                        "thought_time": time.time() - request_start_time
                    }
                    yield f"data: {json.dumps(response_data)}\n\n"
                
                elif hasattr(delta, 'content') and delta.content:
                    content += delta.content
                    
                    response_data = {
                        "role": "assistant",
                        "content": content
                    }
                    yield f"data: {json.dumps(response_data)}\n\n"

        # 출력 토큰 계산
        output_tokens = count_tokens_cached(content, model)
        if reasoning_content:
            output_tokens += count_tokens_cached(reasoning_content, model)

        # 토큰 사용량 저장
        crud_stats.create_token_usage(
            db=db,
            user_id=user_id,
            room_id=room_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            timestamp=datetime.now()
        )

        # 메시지 저장
        if reasoning_content:
            reasoning_message = ChatMessageCreate(
                content="",
                role="assistant",
                room_id=room_id,
                reasoning_content=reasoning_content,
                thought_time=time.time() - request_start_time
            )
            crud_chat.create_message(db, room_id, reasoning_message)

        if content:
            content_message = ChatMessageCreate(
                content=content,
                role="assistant",
                room_id=room_id
            )
            crud_chat.create_message(db, room_id, content_message)

    except Exception as e:
        error_message = f"DeepSeek API Error: {str(e)}"
        yield f"data: {json.dumps({'error': error_message})}\n\n"

def generateUniqueId():
    return int(time.time() * 1000)

async def generate_stream_response(
    request: ChatRequest,
    file_data_list: Optional[List[str]] = None,
    file_types: Optional[List[str]] = None,
    room_id: str = None,
    db: Session = None,
    user_id: str = None,
    subscription: Subscription = None,
    file_names: Optional[List[str]] = None
):
    try:
        if db and user_id:
            subscription = db.query(Subscription).filter(
                Subscription.user_id == user_id
            ).first()

        # SharedChatMemory 인스턴스 가져오기
        chat_memory = SharedChatMemory.get_instance(room_id) if room_id else None
        
        # 새로운 사용자 메시지를 상태에 추가
        if chat_memory and request.messages:
            last_message = request.messages[-1]
            chat_memory.add_message(last_message.role, last_message.content)

        # 요청 시작 시간 기록
        request_start_time = time.time()
        
        # 모델별 클라이언트 초기화
        model_client = None
        if request.model not in (SONAR_MODELS + DEEPSEEK_MODELS + GEMINI_MODELS):
            model_client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            if not model_client:
                raise HTTPException(
                    status_code=500,
                    detail="Anthropic API key is not configured"
                )
        elif request.model in DEEPSEEK_MODELS:
            model_client = get_deepseek_client()
            if not model_client:
                raise HTTPException(
                    status_code=500,
                    detail="DeepSeek API key is not configured"
                )
        elif request.model in GEMINI_MODELS:
            model_client = get_gemini_client()
            if not model_client:
                raise HTTPException(
                    status_code=500,
                    detail="Gemini API key is not configured"
                )

        # 메시지 유효성 검사
        if not request.messages or len(request.messages) == 0:
            raise HTTPException(
                status_code=400,
                detail="At least one message is required"
            )

        # 상태에서 이전 대화 컨텍스트 가져오기
        if chat_memory:
            previous_messages = chat_memory.get_messages()
            # 기존 메시지와 새 메시지 결합
            messages = previous_messages + [{"role": msg.role, "content": msg.content} 
                                         for msg in request.messages[-1:]]
        else:
            messages = [{"role": msg.role, "content": msg.content} 
                      for msg in request.messages]

        # 모델 유효성 검사
        if request.model not in (ALLOWED_MODELS + SONAR_MODELS + GEMINI_MODELS):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid model specified. Allowed models: {ALLOWED_MODELS + SONAR_MODELS + GEMINI_MODELS}"
            )

        # 입력 토큰 카운팅
        input_tokens = await count_tokens(request, file_data_list, file_types)

        accumulated_content = ""
        citations = []
        output_tokens = 0

        # 모델별 처리
        if request.model in SONAR_MODELS:
            async for chunk in generate_sonar_stream_response(
                messages=messages,
                model=request.model,
                room_id=room_id,
                db=db,
                user_id=user_id
            ):
                yield chunk
            return
        elif request.model in DEEPSEEK_MODELS:
            async for chunk in generate_deepseek_stream_response(
                messages=messages,
                model=request.model,
                room_id=room_id,
                db=db,
                user_id=user_id
            ):
                yield chunk
            return
        elif request.model in GEMINI_MODELS:
            async for chunk in generate_gemini_stream_response(
                messages=messages,
                model=request.model,
                room_id=room_id,
                db=db,
                user_id=user_id
            ):
                yield chunk
            return
        else:
            # Claude 모델 처리
            # 파일이 있는 경우 멀티모달 메시지 구성
            if file_data_list and file_types and request.model in MULTIMODAL_MODELS:
                content = []
                
                # 각 파일에 대한 처리
                for file_data, file_type in zip(file_data_list, file_types):
                    content_type = "image" if file_type.startswith("image/") else "document"
                    content.append({
                        "type": content_type,
                        "source": {
                            "type": "base64",
                            "media_type": file_type,
                            "data": file_data
                        }
                    })
                
                # 텍스트 메시지가 있는 경우 추가
                if request.messages and request.messages[-1].content:
                    content.append({
                        "type": "text",
                        "text": request.messages[-1].content
                    })
                
                # 멀티모달 메시지 구성
                user_message = {
                    "role": "user",
                    "content": content
                }
                
                # 이전 메시지들과 결합
                messages = messages[:-1]  # 마지막 메시지 제외
                messages.append(user_message)  # 새로운 멀티모달 메시지 추가

            # 시스템 메시지 구성
            system_blocks = [
                {
                    "type": "text",
                    "text": BRIEF_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"}
                }
            ]

            # Claude API 호출
            async with model_client.messages.stream(
                model=request.model,
                max_tokens=2048,
                temperature=0.7,
                system=system_blocks,
                messages=messages
            ) as stream:
                async for text in stream.text_stream:
                    accumulated_content += text
                    yield f"data: {json.dumps({'content': text})}\n\n"
                
                output_tokens = stream.usage.output_tokens if hasattr(stream, 'usage') else int(len(accumulated_content.split()) * 4.5)

        # 토큰 사용량 저장
        if db and user_id and room_id:
            crud_stats.create_token_usage(
                db=db,
                user_id=user_id,
                room_id=room_id,
                model=request.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                timestamp=datetime.now()
            )
        
        # AI 응답 메시지 저장 및 상태 업데이트
        if accumulated_content:
            message_data = {
                "content": accumulated_content,
                "role": "assistant",
                "room_id": room_id,
                "citations": citations,
                "files": None
            }
            
            message_create = ChatMessageCreate(**message_data)
            crud_chat.create_message(db, room_id, message_create)
            
            # 응답을 상태에 추가
            if chat_memory:
                chat_memory.add_message("assistant", accumulated_content)

    except Exception as e:
        error_message = f"Error: {str(e)}"
        yield f"data: {json.dumps({'error': error_message})}\n\n"

async def validate_file(file: UploadFile) -> bool:
    content = await file.read()
    await file.seek(0)  # 파일 포인터를 다시 처음으로

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="파일 크기는 32MB를 초과할 수 없습니다.")

    if file.content_type == "application/pdf":
        try:
            pdf = PyPDF2.PdfReader(BytesIO(content))
            if len(pdf.pages) > MAX_PDF_PAGES:
                raise HTTPException(status_code=400, detail="PDF는 100페이지를 초과할 수 없습니다.")
        except Exception as e:
            raise HTTPException(status_code=400, detail="유효하지 않은 PDF 파일입니다.")
    
    elif file.content_type.startswith("image/"):
        try:
            img = Image.open(BytesIO(content))
            if img.width > MAX_IMAGE_DIMENSION or img.height > MAX_IMAGE_DIMENSION:
                raise HTTPException(status_code=400, detail="이미지 크기는 8000x8000 픽셀을 초과할 수 없습니다.")
        except Exception as e:
            raise HTTPException(status_code=400, detail="유효하지 않은 이미지 파일입니다.")

    return True

@router.post("/rooms", response_model=ChatRoom)
def create_chat_room(
    room: ChatRoomCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create new chat room.
    """
    return crud_chat.create_chat_room(db=db, room=room, user_id=current_user.id)

@router.get("/rooms", response_model=ChatRoomList)
async def get_chatroom(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all chat rooms for current user.
    """
    rooms = crud_chat.get_chatroom(db=db, user_id=current_user.id)
    return ChatRoomList(rooms=rooms)

@router.delete("/rooms/{room_id}")
async def delete_chat_room(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete chat room.
    """
    success = crud_chat.delete_chat_room(db=db, room_id=room_id, user_id=current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Chat room not found")
    
    # 채팅방의 메모리 인스턴스 제거
    if room_id in SharedChatMemory._instances:
        SharedChatMemory._instances[room_id].clear()
        del SharedChatMemory._instances[room_id]
    
    return {"status": "success"}

@router.post("/rooms/{room_id}/messages")
async def create_message(
    room_id: str,
    message: ChatMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """메시지를 생성하기 전에 사용량을 체크합니다."""
    try:
        # 트랜잭션 시작
        db.begin_nested()  # savepoint 생성
        
        # 구독 정보 확인 (FOR UPDATE로 락 획득)
        subscription = db.query(Subscription).filter(
            Subscription.user_id == str(current_user.id)
        ).with_for_update().first()
        
        if not subscription:
            db.rollback()
            raise HTTPException(
                status_code=403,
                detail="구독 정보를 찾을 수 없습니다."
            )
        
        # 모델 사용량 증가 (한 번만 실행)
        model_name = message.request.model if message.request else None
        if model_name:
            
            if not subscription.increment_usage(model_name):
                db.rollback()
                raise HTTPException(
                    status_code=403,
                    detail=f"이번 달 {model_name} 모델 사용량을 초과했습니다."
                )
            
            # 변경사항 즉시 저장
            db.add(subscription)
            db.commit()
        
        # 메시지 생성 및 스트리밍 응답
        return StreamingResponse(
            generate_stream_response(
                request=message.request, 
                file_data_list=message.file_data_list, 
                file_types=message.file_types, 
                room_id=room_id, 
                db=db, 
                user_id=current_user.id,
                subscription=subscription,  # 이미 업데이트된 구독 정보 전달
                file_names=message.file_names if message.file_names else None
            ),
            media_type="text/event-stream"
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"메시지 생성 중 오류 발생: {str(e)}"
        )

@router.get("/rooms/{room_id}/messages", response_model=ChatMessageList)
async def get_chat_messages(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all messages in a chat room.
    """
    messages = crud_chat.get_room_messages(db=db, room_id=room_id, user_id=current_user.id)
    return ChatMessageList(messages=messages)

@router.post("/rooms/{room_id}/chat")
async def create_chat_message(
    room_id: str,
    request: str = Form(...),
    files: List[UploadFile] = File([]),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        request_data = ChatRequest.parse_raw(request)
        
        # 구독 정보 확인 및 사용량 업데이트
        updated_subscription = crud_subscription.update_model_usage(
            db=db,
            user_id=str(current_user.id),
            model_name=request_data.model
        )
        
        if not updated_subscription:
            raise HTTPException(
                status_code=403,
                detail="Failed to update usage or usage limit exceeded"
            )

        # 파일 처리
        file_data_list = []
        file_types = []
        file_info_list = []
        if files:
            if request_data.model not in MULTIMODAL_MODELS:
                raise HTTPException(
                    status_code=400,
                    detail="Selected model does not support file attachments. Please use Claude 3 Sonnet for files."
                )
            
            if len(files) > 3:
                raise HTTPException(
                    status_code=400,
                    detail="Maximum 3 files can be uploaded at once."
                )
            
            for file in files:
                try:
                    file_data, file_type = await process_file_to_base64(file)
                    file_data_list.append(file_data)
                    file_types.append(file_type)
                    file_info_list.append({
                        "type": file_type,
                        "name": file.filename,
                        "data": file_data
                    })
                except Exception as e:
                    raise HTTPException(status_code=400, detail=f"Failed to process file {file.filename}")

        # 사용자 메시지 생성
        user_message = {
            "content": request_data.messages[-1].content if request_data.messages else "",
            "role": "user",
            "room_id": room_id,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
            "files": file_info_list if file_info_list else None
        }
        
        # 메시지 저장
        message_create = ChatMessageCreate(**user_message)
        crud_chat.create_message(db, room_id, message_create)
        db.commit()

        return StreamingResponse(
            generate_stream_response(
                request_data,
                file_data_list,
                file_types,
                room_id,
                db,
                current_user.id,
                updated_subscription,
                [f.filename for f in files] if files else None
            ),
            media_type="text/event-stream"
        )

    except Exception as e:
        db.rollback()
        error_message = f"Error in chat message creation: {str(e)}"
        raise HTTPException(status_code=500, detail=error_message)

@router.patch("/rooms/{room_id}", response_model=ChatRoom)
async def update_chat_room(
    room_id: str,
    room: ChatRoomCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update chat room.
    """
    return crud_chat.update_chat_room(db=db, room_id=room_id, room=room, user_id=current_user.id)

@router.get("/rooms/{room_id}", response_model=ChatRoom)
async def get_chat_room(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    chat_room = crud_chat.get_chat_room(db=db, room_id=room_id, user_id=str(current_user.id))
    if not chat_room:
        raise HTTPException(status_code=404, detail="Chat room not found")
    return chat_room

@router.get("/stats/token-usage", response_model=List[TokenUsage])
async def get_token_usage(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """토큰 사용량 통계를 조회합니다."""
    try:
        # 날짜 파싱
        start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else datetime.now() - timedelta(days=30)
        end = datetime.strptime(end_date, "%Y-%m-%d") if end_date else datetime.now()
        
        # 관리자가 아닌 경우 자신의 통계만 조회 가능
        if not current_user.is_superuser:
            user_id = current_user.id
            
        return crud_stats.get_token_usage(db, start, end, user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stats/chat-usage")
async def get_chat_usage(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """채팅 사용량 통계를 조회합니다."""
    try:
        # 날짜 파싱
        start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else datetime.now() - timedelta(days=30)
        end = datetime.strptime(end_date, "%Y-%m-%d") if end_date else datetime.now()
        
        # 관리자가 아닌 경우 자신의 통계만 조회 가능
        if not current_user.is_superuser:
            user_id = current_user.id
            
        return crud_stats.get_chat_statistics(db, start, end, user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stats/token-usage-history")
async def get_token_usage_history(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """토큰 사용 기록을 조회합니다."""
    try:
        # 날짜 파싱
        start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else datetime.now() - timedelta(days=30)
        end = datetime.strptime(end_date, "%Y-%m-%d") if end_date else datetime.now()
        
        # 관리자가 아닌 경우 자신의 통계만 조회 가능
        if not current_user.is_superuser:
            user_id = current_user.id
            
        return crud_stats.get_token_usage_history(db, start, end, user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class FileInfo(BaseModel):
    type: str
    name: str
    data: str

    def dict(self, *args, **kwargs):
        return {
            "type": self.type,
            "name": self.name,
            "data": self.data
        }

class PromptGenerateRequest(BaseModel):
    task: str

@router.post("/prompt/generate")
async def generate_prompt(
    request: PromptGenerateRequest,
    current_user: User = Depends(get_current_user)
):
    """프롬프트 생성 엔드포인트"""
    try:
        # 시스템 프롬프트 구성
        system_message = {
            "type": "text",
            "text": """당신은 프롬프트 생성 전문가입니다. 
            사용자의 요청을 분석하여 구조화된 프롬프트를 생성하는 것이 목표입니다.
            프롬프트는 다음 구조를 따라야 합니다:
            1. 배경 설명 (과제/작업의 맥락)
            2. 주요 요구사항 (구체적인 요청사항)
            3. 제약조건 (고려해야 할 사항)
            4. 원하는 출력 형식
            응답은 명확하고 구조적이어야 하며, 사용자의 요청에 대한 맥락에 적합해야 합니다."""
        }

        # 사용자 메시지 구성
        user_message = {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"다음 작업을 위한 구조화된 프롬프트를 생성해주세요: {request.task}"
                }
            ]
        }

        try:
            # Claude API 호출
            response = await client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=1000,
                system=system_message["text"],
                messages=[
                    {
                        "role": "user",
                        "content": f"다음 작업을 위한 구조화된 프롬프트를 생성해주세요: {request.task}"
                    }
                ],
                temperature=0
            )

        except Exception as claude_error:
            raise HTTPException(status_code=500, detail=f"Claude API error: {str(claude_error)}")

        # 응답 구성
        result = {
            "generated_prompt": response.content[0].text,
            "structure": {
                "task": request.task,
                "sections": [
                    "Background",
                    "Requirements",
                    "Constraints",
                    "Output Format"
                ]
            }
        }
        return result

    except Exception as e:
        logging.error(f"Error generating prompt: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# 프로젝트 채팅용 Sonar 스트림 응답 생성 함수
async def generate_project_sonar_stream_response(
    messages: list,
    model: str,
    project_id: str,
    chat_id: str,
    db: Session,
    current_user: User
) -> AsyncGenerator[str, None]:
    try:
        
        # 세션에 User 객체 다시 바인딩
        current_user = db.merge(current_user)
        db.refresh(current_user)
        
        # 입력 토큰 계산
        input_tokens = count_messages_tokens(messages, model)
        
        # 프로젝트 정보 가져오기
        project = crud_project.get(db=db, id=project_id)
        chat_type = f"project_{project.type}" if project and project.type else None
        

        headers = {
            "Authorization": f"Bearer {settings.SONAR_API_KEY}",
            "Content-Type": "application/json"
        }

        formatted_messages = []
        for i, msg in enumerate(messages):
            if i == 0 and msg["role"] == "assistant":
                continue
            if i > 0 and msg["role"] == messages[i-1]["role"]:
                continue
            formatted_messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })
        

        payload = {
            "model": model,
            "messages": formatted_messages,
            "stream": True,
            **SONAR_DEFAULT_CONFIG
        }

        accumulated_content = ""
        citations = []
        
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", SONAR_API_URL, json=payload, headers=headers) as response:
                
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Sonar API Error: {error_text}"
                    )

                async for line in response.aiter_lines():
                    if line.strip():
                        if line.startswith("data: "):
                            try:
                                data = json.loads(line[6:])
                                
                                if "choices" in data and len(data["choices"]) > 0:
                                    delta = data["choices"][0].get("delta", {})
                                    if "content" in delta:
                                        content_chunk = delta["content"]
                                        accumulated_content += content_chunk
                                        yield f"data: {json.dumps({'content': content_chunk})}\n\n"

                                if "citations" in data:
                                    citations = [{"url": url} for url in data["citations"]]
                                    if citations:
                                        yield f"data: {json.dumps({'citations': citations})}\n\n"

                            except json.JSONDecodeError as e:
                                continue

        # 출력 토큰 계산 및 저장
        output_tokens = count_tokens_cached(accumulated_content, model)

        # 토큰 사용량 저장
        crud_stats.create_token_usage(
            db=db,
            user_id=str(current_user.id),
            room_id=chat_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            timestamp=datetime.now(),
            chat_type=chat_type,
            cache_write_tokens=0,
            cache_hit_tokens=0
        )

        # AI 응답 메시지 저장
        if accumulated_content:
            message_create = ChatMessageCreate(
                content=accumulated_content,
                role="assistant",
                files=None,
                citations=citations,
                reasoning_content=None,
                thought_time=None
            )
            
            crud_project.create_chat_message(
                db=db,
                project_id=project_id,
                chat_id=chat_id,
                obj_in=message_create
            )


    except Exception as e:
        error_message = f"Project Sonar API Error: {str(e)}"
        if hasattr(e, '__traceback__'):
            import traceback
        yield f"data: {json.dumps({'error': error_message})}\n\n"

@router.post("/projects/{project_id}/chats/{chat_id}/chat")
async def create_project_chat_message(
    project_id: str,
    chat_id: str,
    request: str = Form(...),
    files: List[UploadFile] = File([]),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        request_data = ChatRequest.parse_raw(request)
        
        # 구독 정보 확인 및 사용량 업데이트
        updated_subscription = crud_subscription.update_model_usage(
            db=db,
            user_id=str(current_user.id),
            model_name=request_data.model
        )
        
        if not updated_subscription:
            raise HTTPException(
                status_code=403,
                detail="Failed to update usage or usage limit exceeded"
            )

        # 파일 처리
        file_data_list = []
        file_types = []
        file_info_list = []
        if files:
            if request_data.model not in MULTIMODAL_MODELS:
                raise HTTPException(
                    status_code=400,
                    detail="Selected model does not support file attachments. Please use Claude 3 Sonnet for files."
                )
            
            if len(files) > 3:
                raise HTTPException(
                    status_code=400,
                    detail="Maximum 3 files can be uploaded at once."
                )
            
            for file in files:
                try:
                    file_data, file_type = await process_file_to_base64(file)
                    file_data_list.append(file_data)
                    file_types.append(file_type)
                    file_info_list.append({
                        "type": file_type,
                        "name": file.filename,
                        "data": file_data
                    })
                except Exception as e:
                    raise HTTPException(status_code=400, detail=f"Failed to process file {file.filename}")

        # 사용자 메시지 생성 - 프로젝트 채팅용으로 수정
        user_message = {
            "content": request_data.messages[-1].content if request_data.messages else "",
            "role": "user",
            "files": file_info_list if file_info_list else None,
            "citations": None,
            "reasoning_content": None,
            "thought_time": None
        }
        
        # 프로젝트 채팅용 메시지 저장으로 변경
        crud_project.create_chat_message(
            db=db,
            project_id=project_id,
            chat_id=chat_id,
            obj_in=ChatMessageCreate(**user_message)
        )

        return StreamingResponse(
            generate_stream_response(
                request_data,
                file_data_list,
                file_types,
                chat_id,
                db,
                current_user.id,
                updated_subscription,
                [f.filename for f in files] if files else None
            ),
            media_type="text/event-stream"
        )

    except Exception as e:
        db.rollback()
        error_message = f"Error in project chat: {str(e)}"
        raise HTTPException(status_code=500, detail=error_message)

def get_gemini_client():
    """Gemini 클라이언트를 생성하는 함수"""
    api_key = settings.GEMINI_API_KEY
    
    if not api_key:
        return None
        
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            generation_config=GEMINI_DEFAULT_CONFIG["gemini-2.0-flash"]
        )
        return model
    except Exception as e:
        return None

# Gemini 스트리밍 응답 생성 함수
async def generate_gemini_stream_response(
    messages: list,
    model: str,
    room_id: str,
    db: Session,
    user_id: str
) -> AsyncGenerator[str, None]:
    try:
        # Gemini 클라이언트 생성
        gemini_model = get_gemini_client()
        if not gemini_model:
            raise HTTPException(
                status_code=500,
                detail="Gemini API key is not configured"
            )

        # 최근 3개의 메시지만 선택
        recent_messages = messages[-3:] if len(messages) > 3 else messages

        # 시스템 프롬프트와 대화 내용 구성
        conversation = f"{GEMINI_SYSTEM_PROMPT}\n\n"
        for msg in recent_messages:
            role = "사용자" if msg["role"] == "user" else "어시스턴트"
            conversation += f"{role}: {msg['content']}\n"
        
        # 입력 토큰 계산
        token_count = await count_gemini_tokens(conversation, model, gemini_model)
        input_tokens = token_count["input_tokens"]

        # 스트리밍 응답 생성
        response = gemini_model.generate_content(
            conversation,
            generation_config=GEMINI_DEFAULT_CONFIG[model],
            stream=True
        )

        accumulated_content = ""
        
        # Gemini의 청크 처리
        for chunk in response:
            if hasattr(chunk, 'text'):
                content_chunk = chunk.text
                accumulated_content += content_chunk
                yield f"data: {json.dumps({'content': content_chunk})}\n\n"
                await asyncio.sleep(0.01)

        # 토큰 사용량 저장
        output_tokens = len(accumulated_content.split()) * 1.3
        crud_stats.create_token_usage(
            db=db,
            user_id=user_id,
            room_id=room_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=int(output_tokens),
            timestamp=datetime.now()
        )

        # AI 응답 메시지 저장
        if accumulated_content:
            message_create = ChatMessageCreate(
                content=accumulated_content,
                role="assistant",
                room_id=room_id
            )
            crud_chat.create_message(db, room_id, message_create)

    except Exception as e:
        error_message = f"Gemini API Error: {str(e)}"
        yield f"data: {json.dumps({'error': error_message})}\n\n"

# Gemini 토큰 카운팅 함수 추가
async def count_gemini_tokens(text: str, model: str, gemini_model) -> dict:
    """Gemini 모델의 토큰 수를 계산합니다."""
    try:
        # 입력 토큰 수 계산
        input_tokens = gemini_model.count_tokens(text).total_tokens
        return {
            "input_tokens": input_tokens,
            "total_tokens": input_tokens
        }
    except Exception as e:
        print(f"Error counting Gemini tokens: {e}")
        return {
            "input_tokens": 0,
            "total_tokens": 0
        }
