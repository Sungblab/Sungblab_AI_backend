from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.schemas.chat import (
    ChatRoom, ChatRoomCreate, ChatRoomList, 
    ChatMessageCreate, ChatMessage, ChatMessageList,
    ChatRequest, TokenUsage
)
from app.crud import crud_chat, crud_stats
from app.db.session import get_db
from app.core.security import get_current_user
from app.models.user import User
import anthropic
import json
from anthropic import Anthropic
from app.core.config import settings
import logging
import asyncio
import base64
from typing import Optional, List
import shutil
import tempfile
import os
from pydantic import BaseModel
import PyPDF2
from io import BytesIO
from PIL import Image
from datetime import datetime, timedelta
from app.models.subscription import Subscription

print(f"Anthropic version: {anthropic.__version__}")

router = APIRouter()
client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
ALLOWED_MODELS = ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"]
MULTIMODAL_MODELS = ["claude-3-5-sonnet-20241022"]  # 멀티모달을 지원하는 모델 리스트

MAX_FILE_SIZE = 32 * 1024 * 1024  # 32MB
MAX_PDF_PAGES = 100
MAX_IMAGE_DIMENSION = 8000

# 시스템 프롬프트 상수 정의
BRIEF_SYSTEM_PROMPT = """당신은 중·고등학생을 위한 'Sungblab AI' 교육 어시스턴트입니다.
주요 역할: 수행평가/생기부/학습 지원을 통한 자기주도적 학습 향상
핵심 원칙: 1)친근한 교육자 톤, 2)단계적 설명과 예시 제공, 3)불확실할 때는 추가 확인"""

DETAILED_SYSTEM_PROMPT = """[역할 & 목적]
- 수행평가 과제(보고서/발표) 작성 지원
- 생기부(세특) 작성 가이드
- 학습 관련 질문 해결 및 심화 학습 유도

[주요 기능]
1. 수행평가 지원
   - 보고서/발표 구조화 및 작성법
   - 자료 조사 및 분석 방법
   - 창의적 접근 방식 제안

2. 생기부 작성 도움
   - 음슴체 작성 요령
   - 구체적 활동 사례 작성법
   - 진로 연계 방안

3. 학습 Q&A
   - 교과 개념의 체계적 설명
   - 효율적인 학습 방법 제시
   - 심화 학습 자료 추천

[행동 지침]
- 친근하고 격려하는 선배같은 톤 유지
- 학생 수준에 맞춘 설명과 예시
- 단계적 사고과정 (CoT) 활용
- 자기주도적 탐구 유도
- 교육적 가치 있는 피드백 제공
- 부적절한 내용 답변 제한
- 불확실한 내용은 추가 확인 권장(환각주의)"""

async def process_file_to_base64(file: UploadFile) -> tuple[str, str]:
    try:
        print(f"Starting to process file: {file.filename}")
        # 파일 내용을 메모리에 읽기
        contents = await file.read()
        base64_data = base64.b64encode(contents).decode('utf-8')
        print(f"File processed successfully, size: {len(contents)} bytes")
        return base64_data, file.content_type
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        raise

async def count_tokens(
    request: ChatRequest,
    file_data: Optional[str] = None,
    file_type: Optional[str] = None,
) -> int:
    try:
        messages = []
        if file_data and file_type and request.model in MULTIMODAL_MODELS:
            content_type = "image" if file_type.startswith("image/") else "document"
            user_message = {
                "role": "user",
                "content": [
                    {
                        "type": content_type,
                        "source": {
                            "type": "base64",
                            "media_type": file_type,
                            "data": file_data,
                        },
                    }
                ],
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

        response = client.messages.count_tokens(
            model=request.model,
            messages=messages,
            system=system_blocks
        )
        return response.input_tokens
    except Exception as e:
        print(f"Error counting tokens: {str(e)}")
        return 0

async def generate_stream_response(
    request: ChatRequest,
    file_data: Optional[str] = None,
    file_type: Optional[str] = None,
    room_id: str = None,
    db: Session = None,
    current_user: User = None,
    file_name: Optional[str] = None
):
    try:
        # 메시지 유효성 검사
        if not request.messages or len(request.messages) == 0:
            raise HTTPException(
                status_code=400,
                detail="At least one message is required"
            )

        # 메시지 내용 유효성 검사 및 최적화
        MAX_MESSAGES = 5  # 최근 5개의 메시지만 유지
        valid_messages = [
            msg for msg in request.messages[-MAX_MESSAGES:] 
            if msg.content and msg.content.strip()
        ]
        
        if len(valid_messages) == 0:
            raise HTTPException(
                status_code=400,
                detail="No valid message content found"
            )

        # 대화방의 첫 메시지인지 확인
        is_first_message = False
        if db and room_id:
            message_count = crud_chat.get_message_count(db, room_id)
            is_first_message = message_count == 0

        # 시스템 메시지 구성
        system_blocks = []
        
        # 첫 메시지일 때만 상세 프롬프트 포함
        if is_first_message:
            system_blocks = [
                {
                    "type": "text",
                    "text": BRIEF_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"}
                },
                {
                    "type": "text",
                    "text": DETAILED_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"}
                }
            ]
        else:
            # 후속 메시지에는 간단한 프롬프트만 포함
            system_blocks = [
                {
                    "type": "text",
                    "text": BRIEF_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"}
                }
            ]

        # 이전 메시지들 처리 (5개 초과분에 대해서만)
        if len(request.messages) > MAX_MESSAGES:
            older_messages = request.messages[:-MAX_MESSAGES]
            # 가장 최근의 중요한 컨텍스트만 요약
            recent_context = older_messages[-3:] if len(older_messages) > 3 else older_messages
            context_summary = " ".join([msg.content for msg in recent_context if msg.content])
            if context_summary:
                system_blocks.append({
                    "type": "text",
                    "text": f"직전 대화 컨텍스트: {context_summary}",
                    "cache_control": {"type": "ephemeral"}
                })

        request.messages = valid_messages[-MAX_MESSAGES:]  # 최근 5개 메시지만 유지

        # 입력 토큰 카운팅
        input_tokens = await count_tokens(request, file_data, file_type)
        print(f"Input tokens counted: {input_tokens}")

        # 기본 설정
        max_tokens = 2048
        temperature = 0.7

        messages = []
        if file_data and file_type and request.model in MULTIMODAL_MODELS:
            print(f"Preparing message with file, type: {file_type}")
            content_type = "image" if file_type.startswith("image/") else "document"
            user_message = {
                "role": "user",
                "content": [
                    {
                        "type": content_type,
                        "source": {
                            "type": "base64",
                            "media_type": file_type,
                            "data": file_data,
                        },
                    }
                ],
            }
            
            if request.messages and request.messages[-1].content:
                print(f"Adding text message: {request.messages[-1].content}")
                user_message["content"].append({
                    "type": "text",
                    "text": request.messages[-1].content
                })
            
            messages = request.messages[:-1] if request.messages else []
            messages.append(user_message)
            print("Message prepared for Anthropic API")
        else:
            messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]

        print(f"Using settings - max_tokens: {max_tokens}, temperature: {temperature}")
        print(f"Chat type: Regular")

        accumulated_content = ""
        with client.messages.stream(
            model=request.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_blocks,
            messages=messages
        ) as stream:
            for text in stream.text_stream:
                accumulated_content += text
                yield f"data: {json.dumps({'content': text})}\n\n"
            
            # 출력 토큰 수 계산 - 단어 수 기반으로 계산
            # Claude는 실제로 단어당 약 2.5~3.0 토큰을 사용하는 경향이 있음
            output_tokens = int(len(accumulated_content.split()) * 4.5)
            print(f"Output tokens counted: {output_tokens}")
            
            # 토큰 사용량 저장 - user_id와 함께 저장
            if db and room_id and current_user:
                print(f"Saving token usage - User: {current_user.id}, Room: {room_id}")
                crud_stats.create_token_usage(
                    db=db,
                    user_id=str(current_user.id),
                    room_id=room_id,
                    model=request.model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
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
        error_message = f"Error: {str(e)}"
        print(f"Error in generate_stream_response: {str(e)}")
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
async def get_chat_rooms(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all chat rooms for current user.
    """
    rooms = crud_chat.get_chat_rooms(db=db, user_id=current_user.id)
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
    return {"status": "success"}

@router.post("/rooms/{room_id}/messages")
async def create_message(
    room_id: str,
    message: ChatMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """메시지를 생성하기 전에 사용량을 체크합니다."""
    # 구독 정보 확인
    subscription = db.query(Subscription).filter(
        Subscription.user_id == str(current_user.id)
    ).first()
    
    if not subscription:
        raise HTTPException(
            status_code=403,
            detail="구독 정보를 찾을 수 없습니다."
        )
    
    # 메시지 제한 확인
    if subscription.message_count >= subscription.message_limit:
        raise HTTPException(
            status_code=403,
            detail="이번 달 메시지 사용량을 초과했습니다. 구독을 업그레이드하거나 다음 달까지 기다려주세요."
        )
    
    # 메시지 생성 로직
    subscription.message_count += 1
    db.commit()
    
    # 기존 메시지 생성 로직 실행
    return crud_chat.create_message(db, room_id, message)

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
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        # 채팅방 존재 여부 및 권한 확인
        chat_room = crud_chat.get_chat_room(db=db, room_id=room_id, user_id=str(current_user.id))
        if not chat_room:
            raise HTTPException(status_code=404, detail="Chat room not found")

        request_data = ChatRequest.parse_raw(request)
        if request_data.model not in ALLOWED_MODELS:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid model specified. Allowed models: {ALLOWED_MODELS}"
            )

        # 파일이 있고 선택된 모델이 멀티모달을 지원하지 않는 경우
        if file and request_data.model not in MULTIMODAL_MODELS:
            raise HTTPException(
                status_code=400,
                detail="Selected model does not support file attachments. Please use Claude 3 Sonnet for files."
            )

        # 파일이 있는 경우 처리
        file_data = None
        file_type = None
        if file:
            # 파일 유효성 검사
            await validate_file(file)
            try:
                file_data, file_type = await process_file_to_base64(file)
            except Exception as e:
                print(f"Error processing file: {str(e)}")
                raise HTTPException(status_code=400, detail="Failed to process file")

        return StreamingResponse(
            generate_stream_response(
                request_data, 
                file_data, 
                file_type, 
                room_id, 
                db, 
                current_user,  # current_user 전달
                file.filename if file else None
            ),
            media_type="text/event-stream"
        )
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

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

class ChatMessageCreate(BaseModel):
    content: str
    role: str
    room_id: Optional[str] = None
    file: Optional[FileInfo] = None 