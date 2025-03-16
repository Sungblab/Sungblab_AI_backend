from typing import List, Optional, Dict, Any, AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api import deps
from app.crud import crud_project, crud_stats, crud_subscription
from app.schemas.project import Project, ProjectCreate, ProjectUpdate
from app.schemas.chat import (
    ChatCreate, ChatUpdate, ChatMessage, 
    ChatMessageCreate, ChatRequest
)
from app.core.chat import get_chat_response
from app.models.user import User
import json
from anthropic import AsyncAnthropic
from app.core.config import settings
from datetime import datetime, timezone, timedelta
import io
import base64
import PyPDF2
from PIL import Image
from io import BytesIO
from openai import AsyncOpenAI
import google.generativeai as genai
import asyncio
import tempfile
import os

# 기본 시스템 프롬프트 (공통)
BRIEF_SYSTEM_PROMPT = {
    "type": "text",
    "text": """당신은 학생을 위한 'Sungblab AI' 교육 어시스턴트입니다.
답변은 적절한 마크다운을 적용해 주세요
답변 형식은 '설명적'으로 요약하지 말고 풀어서 종결어미로 답하세요.""",
    "cache_control": {"type": "ephemeral"}
}

# 수행평가용 상세 프롬프트
ASSIGNMENT_PROMPT = {
    "type": "text",
    "text": """[수행평가 도우미]
당신은 학생들의 수행평가를 돕는 도우미입니다.

1. 과제 요구사항 분석
   - 평가 기준표, 주제, 제출 방식, 기한 등을 명확히 파악
   - 실제 보고서/발표 자료 예시로 아이디어 확장 지원
   
2. 아이디어 & 피드백
   - 학생의 초기 생각을 존중, 발전 유도
   - COT로 단계별 사고 과정 안내
   
3. 평가 기준 고려
   - 루브릭 기반 구체적 조언
   
4. 친근한 소통
   - 전문용어는 필요시 쉽게 설명

※ 유의사항
- 필요시 수행평가-세특 연계 방법 제시
- 추가 고민을 유도하는 질문으로 마무리""",
    "cache_control": {"type": "ephemeral"}
}

# 생기부용 상세 프롬프트
RECORD_PROMPT = {
    "type": "text",
    "text": """[생기부(학교생활기록부) 도우미]
당신은 학교생활기록부 작성을 돕는 도우미입니다.

1. 작성 원칙
   - 음슴체 사용 ("~함", "~을 보임")
   - 구체적 사례 중심 서술
   - 교육부 지침 엄격 준수
   
2. 항목별 특징
   - 교과 세특: 수행평가/수업활동 중심
   - 창체: 자율/동아리/진로활동 구분
   - 행특: 학습/행동/인성 통합적 관찰
   
3. 분량 제한
   - 사용자가 요구한 바이트 수에 맞춰 작성 해야함
   
4. 금지사항
   - 특정 대학·기관,교외 수상 기재 금지
   - 추상적 표현 지양,구체적 표현 지향
   
※ 작성 후 체크사항
- 금지사항 포함 여부
- 음슴체 유지
- 바이트 제한 확인
- 구체적 근거 포함""",
    "cache_control": {"type": "ephemeral"}
}
# 프로젝트 타입별 기본 설정
PROJECT_DEFAULT_SETTINGS = {
    "assignment": {
        "max_tokens": 8192,  # 수행평가는 긴 설명이 필요할 수 있음
        "temperature": 0.7   # 창의적인 답변 허용
    },
    "record": {
        "max_tokens": 8192,  # 생기부는 비교적 짧고 명확하게
        "temperature": 0.3   # 보수적이고 안정적인 답변
    }
}

# 파일 업로드 관련 상수
ALLOWED_MODELS = [
    "claude-3-7-sonnet-20250219", 
    "claude-3-5-haiku-20241022",
    "sonar-pro",
    "sonar",
    "sonar-reasoning",
    "deepseek-reasoner",
    "gemini-2.0-flash",
]
MULTIMODAL_MODELS = ["claude-3-7-sonnet-20250219", "gemini-2.0-flash"]  # Gemini 모델 추가
MAX_FILE_SIZE = 32 * 1024 * 1024  # 32MB
MAX_PDF_PAGES = 100
MAX_IMAGE_DIMENSION = 8000

# DeepSeek 관련 설정 추가
DEEPSEEK_MODELS = ["deepseek-reasoner"]
DEEPSEEK_DEFAULT_CONFIG = {
    "deepseek-reasoner": {
        "temperature": 0.7,
        "max_tokens": 8192,
        "top_p": 0.95,
        "stream": True
    },

}

# Gemini 관련 설정 추가
GEMINI_MODELS = ["gemini-2.0-flash"]
GEMINI_DEFAULT_CONFIG = {
    "gemini-2.0-flash": {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 40,
        "max_output_tokens": 8192,
    },
}

class ChatRequest(BaseModel):
    model: str
    messages: List[Dict[str, Any]]
    project_type: Optional[str] = None

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

class ChatMessageCreate(BaseModel):
    content: str
    role: str
    files: Optional[List[FileInfo]] = None  # 다중 파일 지원
    citations: Optional[List[Dict[str, str]]] = None  # 인용 정보 추가
    reasoning_content: Optional[str] = None  # 추론 내용
    thought_time: Optional[float] = None  # 사고 시간

async def count_tokens(request: ChatRequest) -> dict:
    """토큰 수를 계산하고 과금 유형별로 분류합니다."""
    try:
        # 메시지 변환
        messages = []
        if request.messages:
            messages = [{"role": msg["role"], "content": msg["content"]} for msg in request.messages]
        
        # 첫 메시지 여부 확인
        is_first_message = len(messages) <= 1
        
        # 시스템 프롬프트 설정
        system = [BRIEF_SYSTEM_PROMPT]
        if is_first_message and request.project_type:
            if request.project_type == "assignment":
                system.append(ASSIGNMENT_PROMPT)
            elif request.project_type == "record":
                system.append(RECORD_PROMPT)

        try:
            # 토큰 계산 (비동기 방식)
            response = await client.messages.count_tokens(
                model=request.model,
                messages=messages,
                system=system
            )
            
            # 토큰 분류
            result = {
                "base_input_tokens": response.input_tokens,  # 기본 입력 토큰
                "cache_write_tokens": response.input_tokens * 0.25 if is_first_message else 0,  # 캐시 쓰기 (25% 추가)
                "cache_hit_tokens": 0 if is_first_message else response.input_tokens * 0.1,  # 캐시 히트 (90% 할인)
            }
            
            return result
            
        except Exception as e:
            raise
            
    except Exception as e:
        return {"base_input_tokens": 0, "cache_write_tokens": 0, "cache_hit_tokens": 0}

router = APIRouter()
client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

class ProjectResponse(BaseModel):
    id: str
    name: str
    type: str
    description: Optional[str] = None
    system_instruction: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None
    chats: List[dict] = []

# PDF 변환 요청 모델 추가
class HTMLToPDFRequest(BaseModel):
    html_content: str

@router.post("", response_model=ProjectResponse)
def create_project(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
    project_in: ProjectCreate
) -> Any:
    """
    Create new project.
    """
    project = crud_project.create(db=db, obj_in=project_in, user_id=current_user.id)
    return project

@router.get("", response_model=List[ProjectResponse])
def read_projects(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Retrieve projects.
    """
    projects = crud_project.get_multi_by_user(
        db=db, user_id=current_user.id, skip=skip, limit=limit
    )
    return [ProjectResponse(**project) for project in projects]

@router.get("/{project_id}", response_model=ProjectResponse)
def read_project(
    *,
    db: Session = Depends(deps.get_db),
    project_id: str,
) -> Any:
    """
    Get project by ID.
    """
    project = crud_project.get(db=db, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse(**project.to_dict(include_chats=True))

@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    *,
    db: Session = Depends(deps.get_db),
    project_id: str,
    project_in: ProjectUpdate,
) -> Any:
    """
    Update project.
    """
    project = crud_project.get(db=db, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = crud_project.update(db=db, db_obj=project, obj_in=project_in)
    
    # 응답 데이터 직렬화
    response_data = project.to_dict()
    if hasattr(project, 'chats'):
        response_data['chats'] = [chat.to_dict() for chat in project.chats]
    
    return response_data

@router.delete("/{project_id}")
def delete_project(
    *,
    db: Session = Depends(deps.get_db),
    project_id: str,
) -> Any:
    """
    Delete project.
    """
    project = crud_project.get(db=db, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    crud_project.remove(db=db, id=project_id)
    return {"status": "success"}

# 프로젝트 채팅 관련 엔드포인트
@router.post("/{project_id}/chats", response_model=dict)
def create_project_chat(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
    project_id: str,
    chat_in: ChatCreate,
) -> Any:
    """
    Create new chat in project.
    """
    project = crud_project.get(db=db, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    chat = crud_project.create_chat(
        db=db, 
        project_id=project_id, 
        obj_in=chat_in,
        user_id=current_user.id
    )
    return chat.to_dict()

@router.get("/{project_id}/chats/{chat_id}", response_model=dict)
def read_project_chat(
    *,
    db: Session = Depends(deps.get_db),
    project_id: str,
    chat_id: str,
) -> Any:
    """
    Get chat by ID in project.
    """
    project = crud_project.get(db=db, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    chat = crud_project.get_chat(db=db, project_id=project_id, chat_id=chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat

@router.patch("/{project_id}/chats/{chat_id}", response_model=dict)
def update_project_chat(
    *,
    db: Session = Depends(deps.get_db),
    project_id: str,
    chat_id: str,
    chat_in: ChatUpdate,
) -> Any:
    """
    Update chat in project.
    """
    project = crud_project.get(db=db, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    chat = crud_project.get_chat(db=db, project_id=project_id, chat_id=chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    chat = crud_project.update_chat(
        db=db, project_id=project_id, chat_id=chat_id, obj_in=chat_in
    )
    return chat

@router.get("/{project_id}/chats/{chat_id}/messages", response_model=dict)
def read_project_chat_messages(
    *,
    db: Session = Depends(deps.get_db),
    project_id: str,
    chat_id: str,
) -> Any:
    """
    Get messages in project chat.
    """
    project = crud_project.get(db=db, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    chat = crud_project.get_chat(db=db, project_id=project_id, chat_id=chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    messages = crud_project.get_chat_messages(
        db=db, project_id=project_id, chat_id=chat_id
    )
    return {"messages": messages}

@router.post("/{project_id}/chats/{chat_id}/messages", response_model=ChatMessage)
def create_project_chat_message(
    *,
    db: Session = Depends(deps.get_db),
    project_id: str,
    chat_id: str,
    message_in: ChatMessageCreate,
) -> Any:
    """
    Create message in project chat.
    """
    project = crud_project.get(db=db, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    chat = crud_project.get_chat(db=db, project_id=project_id, chat_id=chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    message = crud_project.create_chat_message(
        db=db, project_id=project_id, chat_id=chat_id, obj_in=message_in
    )
    return message

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

async def process_file_to_base64(file: UploadFile) -> tuple[str, str]:
    try:
        contents = await file.read()
        base64_data = base64.b64encode(contents).decode('utf-8')
        return base64_data, file.content_type
    except Exception as e:
        raise

@router.post("/{project_id}/chats/{chat_id}/chat")
async def stream_project_chat(
    *,
    db: Session = Depends(deps.get_db),
    project_id: str,
    chat_id: str,
    request: str = Form(...),
    files: List[UploadFile] = File([]),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    try:
        request_data = json.loads(request)
        
        # DeepSeek 모델인 경우
        if request_data["model"] in DEEPSEEK_MODELS:
            # 프로젝트 정보 가져오기
            project = crud_project.get(db=db, id=project_id)
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
            
            # 첫 메시지 여부 확인
            is_first_message = len(request_data["messages"]) <= 1
            
            # 시스템 프롬프트 생성
            system_prompt = get_system_prompts(project.type, is_first_message)
            
            # 메시지 리스트의 시작에 시스템 프롬프트 추가
            messages = [
                {"role": "system", "content": system_prompt}
            ] + request_data["messages"]
            
            # 사용자 메시지 저장
            user_message = {
                "content": messages[-1]["content"] if messages else "",
                "role": "user",
                "files": None,
                "citations": None,
                "reasoning_content": None,
                "thought_time": None
            }
            
            crud_project.create_chat_message(
                db=db,
                project_id=project_id,
                chat_id=chat_id,
                obj_in=ChatMessageCreate(**user_message)
            )
            
            return StreamingResponse(
                generate_deepseek_stream_response(
                    messages=messages,  # 시스템 프롬프트가 포함된 메시지 전달
                    model=request_data["model"],
                    room_id=chat_id,
                    db=db,
                    user_id=current_user.id
                ),
                media_type="text/event-stream"
            )

        # Gemini 모델인 경우
        elif request_data["model"] in GEMINI_MODELS:
            # 프로젝트 정보 가져오기
            project = crud_project.get(db=db, id=project_id)
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
            
            # 파일 처리
            file_data_list = []
            file_types = []
            file_info_list = []
            if files:
                if request_data["model"] not in MULTIMODAL_MODELS:
                    raise HTTPException(
                        status_code=400,
                        detail="Selected model does not support file attachments. Please use Claude 3 Sonnet or Gemini 2.0 Flash for files."
                    )
                
                if len(files) > 3:
                    raise HTTPException(
                        status_code=400,
                        detail="Maximum 3 files can be uploaded at once."
                    )
                
                for file in files:
                    try:
                        await validate_file(file)
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
            
            # 사용자 메시지 저장
            user_message = {
                "content": request_data["messages"][-1]["content"] if request_data["messages"] else "",
                "role": "user",
                "files": file_info_list if file_info_list else None,
                "citations": None,
                "reasoning_content": None,
                "thought_time": None
            }
            
            crud_project.create_chat_message(
                db=db,
                project_id=project_id,
                chat_id=chat_id,
                obj_in=ChatMessageCreate(**user_message)
            )
            
            # 전체 메시지 이력 전달
            messages = [
                {"role": msg["role"], "content": msg["content"]}
                for msg in request_data["messages"]
                if msg["content"] and msg["content"].strip()
            ]
            
            return StreamingResponse(
                generate_gemini_stream_response(
                    messages=messages,
                    model=request_data["model"],
                    room_id=chat_id,
                    db=db,
                    user_id=current_user.id,
                    file_data_list=file_data_list,
                    file_types=file_types,
                    file_names=[f.filename for f in files] if files else None
                ),
                media_type="text/event-stream"
            )

        # Sonar 모델인 경우
        elif request_data["model"] in ["sonar-pro", "sonar"]:
            # 사용자 메시지 먼저 저장
            user_message = {
                "content": request_data["messages"][-1]["content"] if request_data["messages"] else "",
                "role": "user",
                "files": None,
                "citations": None,
                "reasoning_content": None,
                "thought_time": None
            }
            
            # 프로젝트 채팅용 메시지 생성
            crud_project.create_chat_message(
                db=db,
                project_id=project_id,
                chat_id=chat_id,
                obj_in=ChatMessageCreate(**user_message)
            )
            
            # Sonar 응답 생성 및 스트리밍
            from app.api.api_v1.endpoints.chat import generate_project_sonar_stream_response
            return StreamingResponse(
                generate_project_sonar_stream_response(
                    messages=request_data["messages"],
                    model=request_data["model"],
                    project_id=project_id,
                    chat_id=chat_id,
                    db=db,
                    current_user=current_user
                ),
                media_type="text/event-stream"
            )

        # 프로젝트 확인
        project = crud_project.get(db=db, id=project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # 구독 사용량 체크 및 업데이트
        updated_subscription = crud_subscription.update_model_usage(
            db=db,
            user_id=str(current_user.id),
            model_name=request_data["model"]
        )
        
        if not updated_subscription:
            raise HTTPException(
                status_code=403,
                detail="Failed to update usage or usage limit exceeded"
            )

        # 기존의 파일 처리 및 메시지 생성 로직...
        if request_data["model"] not in ALLOWED_MODELS:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid model specified. Allowed models: {ALLOWED_MODELS}"
            )

        # 파일 처리
        file_data_list = []
        file_types = []
        file_info_list = []
        if files:
            for file in files:
                try:
                    await validate_file(file)
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

        # 사용자 메시지 저장
        user_message = {
            "content": request_data["messages"][-1]["content"] if request_data["messages"] else "",
            "role": "user",
            "files": file_info_list if file_info_list else None,
            "citations": None,
            "reasoning_content": None,
            "thought_time": None
        }

        crud_project.create_chat_message(
            db=db,
            project_id=project_id,
            chat_id=chat_id,
            obj_in=ChatMessageCreate(**user_message)
        )

        async def generate_stream_response(current_user=current_user, db=db):
            try:
                # 세션 새로고침을 위해 프로젝트 객체를 다시 조회
                project = crud_project.get(db=db, id=project_id)
                if not project:
                    raise HTTPException(status_code=404, detail="Project not found")

                # 토큰 카운팅 (비동기 호출)
                token_counts = await count_tokens(
                    ChatRequest(
                        model=request_data["model"],
                        messages=request_data["messages"],
                        project_type=project.type
                    )
                )

                # 메시지 이력 관리 (최근 5개만 유지)
                MAX_MESSAGES = 5
                recent_messages = request_data["messages"][-MAX_MESSAGES:]

                # 시스템 프롬프트 설정
                system = [BRIEF_SYSTEM_PROMPT]
                
                # 프로젝트의 추가 시스템 프롬프트가 있다면 항상 추가
                if project.system_instruction:
                    system.append({
                        "type": "text",
                        "text": project.system_instruction,
                        "cache_control": {"type": "ephemeral"}
                    })

                # 첫 메시지인 경우 프로젝트 타입별 프롬프트 추가
                is_first_message = len(request_data["messages"]) <= 1
                if is_first_message:
                    if project.type == "assignment":
                        system.append(ASSIGNMENT_PROMPT)
                    elif project.type == "record":
                        system.append(RECORD_PROMPT)

                # 프로젝트 설정
                default_settings = PROJECT_DEFAULT_SETTINGS.get(project.type, {
                    "max_tokens": 8192,
                    "temperature": 0.7
                })
                
                max_tokens = project.settings.get('max_tokens', default_settings["max_tokens"]) if project.settings else default_settings["max_tokens"]
                temperature = project.settings.get('temperature', default_settings["temperature"]) if project.settings else default_settings["temperature"]

                # 메시지 구성
                messages = []
                if file_data_list and file_types and request_data["model"] in MULTIMODAL_MODELS:
                    user_message = {
                        "role": "user",
                        "content": []
                    }
                    
                    for file_data, file_type in zip(file_data_list, file_types):
                        content_type = "image" if file_type.startswith("image/") else "document"
                        user_message["content"].append({
                            "type": content_type,
                            "source": {
                                "type": "base64",
                                "media_type": file_type,
                                "data": file_data,
                            }
                        })
                    
                    if request_data["messages"] and request_data["messages"][-1]["content"]:
                        user_message["content"].append({
                            "type": "text",
                            "text": request_data["messages"][-1]["content"]
                        })
                    
                    messages = request_data["messages"][:-1] if request_data["messages"] else []
                    messages.append(user_message)
                else:
                    messages = [{"role": msg["role"], "content": msg["content"]} for msg in recent_messages]

                # AI 응답 생성 및 스트리밍
                accumulated_content = ""
                async with client.messages.stream(
                    model=request_data["model"],
                    system=system,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature
                ) as stream:
                    async for text in stream.text_stream:
                        accumulated_content += text
                        yield f"data: {json.dumps({'content': text})}\n\n"

                    # 출력 토큰 수 계산
                    output_tokens = stream.usage.output_tokens if hasattr(stream, 'usage') else int(len(accumulated_content.split()) * 4.5)

                    # 토큰 사용량 저장
                    if token_counts['base_input_tokens'] > 0 or output_tokens > 0:
                        try:
                            # 세션 새로고침
                            if current_user and db:
                                current_user = db.merge(current_user)
                                db.refresh(current_user)

                            chat_type = f"project_{project.type}" if project and project.type else None
                            
                            # 토큰 사용량 저장
                            crud_stats.create_token_usage(
                                db=db,
                                user_id=str(current_user.id),
                                room_id=chat_id,  # chat_id 직접 사용
                                model=request_data["model"],
                                input_tokens=token_counts['base_input_tokens'],
                                output_tokens=output_tokens,
                                timestamp=datetime.now(),
                                chat_type=chat_type,
                                cache_write_tokens=token_counts['cache_write_tokens'],
                                cache_hit_tokens=token_counts['cache_hit_tokens']
                            )

                        except Exception as e:
                            print(f"Error saving token usage: {str(e)}")
                            print(f"Project ID: {project_id}, Chat ID: {chat_id}")
                            db.rollback()  # 에러 발생 시 롤백

                # AI 응답 메시지 저장
                if accumulated_content:
                    try:
                        crud_project.create_chat_message(
                            db=db,
                            project_id=project_id,
                            chat_id=chat_id,
                            obj_in=ChatMessageCreate(
                                content=accumulated_content,
                                role="assistant",
                                citations=None,
                                reasoning_content=None,
                                thought_time=None
                            )
                        )
                    except Exception as e:
                        print(f"Error saving AI response: {str(e)}")
                        db.rollback()  # 에러 발생 시 롤백

            except Exception as e:
                db.rollback()  # 에러 발생 시 롤백
                error_message = f"Error in streaming response: {str(e)}"
                print(error_message)
                yield f"data: {json.dumps({'error': error_message})}\n\n"

        return StreamingResponse(
            generate_stream_response(current_user=current_user, db=db),
            media_type="text/event-stream"
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process chat: {str(e)}"
        )

@router.delete("/{project_id}/chats/{chat_id}")
def delete_project_chat(
    *,
    db: Session = Depends(deps.get_db),
    project_id: str,
    chat_id: str,
) -> Any:
    """
    Delete chat from project.
    """
    project = crud_project.get(db=db, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    chat = crud_project.get_chat(db=db, project_id=project_id, chat_id=chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    db.delete(chat)
    db.commit()
    
    return {"message": "Chat deleted successfully"}

def get_kr_time() -> datetime:
    """한국 시간을 반환하는 함수"""
    utc_time = datetime.now(timezone.utc)
    kr_timezone = timezone(timedelta(hours=9))
    return utc_time.astimezone(kr_timezone)

def create_message(db: Session, room_id: str, message: ChatMessageCreate) -> ChatMessage:
    try:
        current_time = get_kr_time()
        # 현재 시간을 밀리초 단위로 변환하여 ID로 사용
        message_id = int(current_time.timestamp() * 1000)
        
        db_message = ChatMessage(
            id=message_id,  # ID 필드 추가
            room_id=room_id,
            content=message.content,
            role=message.role,
            files=message.files,
            citations=message.citations,
            reasoning_content=message.reasoning_content,
            thought_time=message.thought_time,
            created_at=current_time,
            updated_at=current_time
        )
        db.add(db_message)
        db.commit()
        db.refresh(db_message)
        return db_message
    except Exception as e:
        db.rollback()
        raise

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

# 시스템 프롬프트 처리 함수 추가
def get_system_prompts(project_type: str = None, is_first_message: bool = False) -> str:
    """프로젝트 타입과 메시지 순서에 따른 시스템 프롬프트 생성"""
    prompts = [BRIEF_SYSTEM_PROMPT["text"]]
    
    if is_first_message and project_type:
        if project_type == "assignment":
            prompts.append(ASSIGNMENT_PROMPT["text"])
        elif project_type == "record":
            prompts.append(RECORD_PROMPT["text"])
            
    return "\n\n".join(prompts)

# count_gemini_tokens 함수 추가
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

# Gemini 스트리밍 응답 생성 함수 수정
async def generate_gemini_stream_response(
    messages: list,
    model: str,
    room_id: str,
    db: Session,
    user_id: str,
    file_data_list: Optional[List[str]] = None,
    file_types: Optional[List[str]] = None,
    file_names: Optional[List[str]] = None
) -> AsyncGenerator[str, None]:
    try:
        # Gemini 클라이언트 생성
        gemini_model = get_gemini_client()
        if not gemini_model:
            raise HTTPException(
                status_code=500,
                detail="Gemini API key is not configured"
            )

        # 프로젝트 정보 가져오기
        project = crud_project.get_project_by_chat_id(db, room_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        project_id = project.id
        chat_id = room_id

        # 전체 대화 컨텍스트 구성
        conversation_history = []
        for msg in messages:
            role = "시스템" if msg["role"] == "system" else "사용자" if msg["role"] == "user" else "어시스턴트"
            conversation_history.append(f"{role}: {msg['content']}")
        
        # 시스템 프롬프트와 대화 내용 결합
        system_prompt = BRIEF_SYSTEM_PROMPT["text"]
        if project.type == "assignment":
            system_prompt += "\n\n" + ASSIGNMENT_PROMPT["text"]
        elif project.type == "record":
            system_prompt += "\n\n" + RECORD_PROMPT["text"]

        # 프로젝트의 추가 시스템 프롬프트가 있다면 추가
        if project.system_instruction:
            system_prompt += "\n\n" + project.system_instruction

        # 최종 프롬프트 구성
        prompt = f"{system_prompt}\n\n"
        prompt += "\n".join(conversation_history)
        
        # 파일 처리
        file_refs = []
        contents = []
        
        # 대화 컨텍스트를 첫 번째 콘텐츠로 추가
        contents.append(prompt)
        
        # 텍스트 프롬프트 추출 (마지막 메시지)
        text_prompt = ""
        if messages and len(messages) > 0:
            text_prompt = messages[-1].get("content", "")
        
        # 파일 처리
        if file_data_list and file_types:
            for i, (file_data, file_type) in enumerate(zip(file_data_list, file_types)):
                file_name = file_names[i] if file_names and i < len(file_names) else f"file_{i}.{file_type.split('/')[-1]}"
                
                # 파일 크기 확인
                file_size = len(base64.b64decode(file_data))
                
                if file_size > 20 * 1024 * 1024:  # 20MB 이상인 경우 File API 사용
                    file_ref = await upload_file_to_gemini(
                        base64.b64decode(file_data),
                        file_type,
                        file_name
                    )
                    file_refs.append(file_ref)
                    contents.append(file_ref)
                else:
                    # 이미지 파일이나 PDF 파일인 경우
                    if file_type.startswith("image/") or file_type == "application/pdf":
                        # 파일 데이터 디코딩
                        file_data_bytes = base64.b64decode(file_data)
                        
                        if file_type == "application/pdf":
                            try:
                                # PDF를 직접 처리 - Gemini API의 새로운 방식 사용
                                import io
                                
                                # 파일 객체 생성
                                file_obj = io.BytesIO(file_data_bytes)
                                
                                # 파일 객체를 직접 contents에 추가
                                contents.append({
                                    "inline_data": {
                                        "data": base64.b64encode(file_data_bytes).decode('utf-8'),
                                        "mime_type": file_type
                                    }
                                })
                            except Exception as e:
                                print(f"PDF 처리 중 오류 발생: {e}")
                                # 오류 발생 시 텍스트로 처리
                                contents.append(f"[PDF 파일: {file_name}]")
                        else:
                            # 일반 이미지 처리
                            try:
                                img = Image.open(BytesIO(file_data_bytes))
                                contents.append(img)
                            except Exception as e:
                                print(f"이미지 처리 중 오류 발생: {e}")
                                contents.append(f"[이미지 파일: {file_name}]")
                    else:
                        # 다른 파일 타입 처리
                        try:
                            file_data_bytes = base64.b64decode(file_data)
                            
                            # 기타 문서 파일 처리
                            contents.append({
                                "inline_data": {
                                    "data": base64.b64encode(file_data_bytes).decode('utf-8'),
                                    "mime_type": file_type
                                }
                            })
                        except Exception as e:
                            print(f"파일 처리 중 오류 발생: {e}")
                            contents.append(f"[파일 처리 중 오류 발생: {file_name}]")
        
        # 입력 토큰 계산
        token_count = await count_gemini_tokens(text_prompt, model, gemini_model)
        input_tokens = token_count["input_tokens"]

        # 스트리밍 응답 생성
        response = gemini_model.generate_content(
            contents,
            generation_config=GEMINI_DEFAULT_CONFIG[model],
            stream=True
        )

        accumulated_content = ""
        start_time = datetime.now()
        
        # Gemini의 청크 처리
        try:
            for chunk in response:
                if hasattr(chunk, 'text'):
                    content_chunk = chunk.text
                    accumulated_content += content_chunk
                    yield f"data: {json.dumps({'content': content_chunk})}\n\n"
                    await asyncio.sleep(0.01)  # 비동기 컨텍스트 유지
        except Exception as e:
            error_message = f"Gemini 응답 처리 중 오류 발생: {str(e)}"
            print(error_message)
            yield f"data: {json.dumps({'error': error_message})}\n\n"

        # 응답 완료 후 메시지 저장
        if accumulated_content:
            end_time = datetime.now()
            thought_time = (end_time - start_time).total_seconds()

            # 토큰 사용량 계산 및 저장
            output_tokens = len(accumulated_content.split())
            crud_stats.create_token_usage(
                db=db,
                user_id=user_id,
                room_id=chat_id,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                timestamp=datetime.now(),
                chat_type=f"project_{project.type}" if project.type else None
            )

            # AI 응답 메시지 저장
            crud_project.create_chat_message(
                db=db,
                project_id=project_id,
                chat_id=chat_id,
                obj_in=ChatMessageCreate(
                    content=accumulated_content,
                    role="assistant",
                    reasoning_content=None,
                    thought_time=thought_time
                )
            )
            
        # 임시 파일 참조 정리
        for file_ref in file_refs:
            try:
                await delete_gemini_file(file_ref.name)
            except:
                pass

    except Exception as e:
        error_message = f"Error in Gemini streaming: {str(e)}"
        print(error_message)
        yield f"data: {json.dumps({'error': error_message})}\n\n"

# Gemini File API 관련 함수 추가 (chat.py에서 가져옴)
async def upload_file_to_gemini(file_data: bytes, file_type: str, file_name: str = None) -> dict:
    """Gemini File API를 사용하여 파일을 업로드합니다."""
    try:
        gemini_client = get_gemini_client()
        if not gemini_client:
            raise HTTPException(
                status_code=500,
                detail="Gemini API key is not configured"
            )
        
        # 임시 파일 생성
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_type.split('/')[-1]}") as temp_file:
            temp_file.write(file_data)
            temp_file_path = temp_file.name
        
        # Gemini File API를 사용하여 파일 업로드
        file_ref = gemini_client.files.upload(file=temp_file_path)
        
        # 임시 파일 삭제
        os.unlink(temp_file_path)
        
        return file_ref
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload file to Gemini: {str(e)}"
        )

async def delete_gemini_file(file_id: str) -> bool:
    """Gemini File API를 사용하여 파일을 삭제합니다."""
    try:
        gemini_client = get_gemini_client()
        if not gemini_client:
            raise HTTPException(
                status_code=500,
                detail="Gemini API key is not configured"
            )
        
        gemini_client.files.delete(name=file_id)
        return True
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete file from Gemini: {str(e)}"
        )