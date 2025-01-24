from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api import deps
from app.crud import crud_project, crud_stats
from app.schemas.project import Project, ProjectCreate, ProjectUpdate
from app.schemas.chat import (
    ChatCreate, ChatUpdate, ChatMessage, 
    ChatMessageCreate, ChatRequest
)
from app.core.chat import get_chat_response
from app.models.user import User
import json
from anthropic import Anthropic
from app.core.config import settings
from datetime import datetime
import io
import base64
import PyPDF2
from PIL import Image
from io import BytesIO

# 기본 시스템 프롬프트 (공통)
BRIEF_SYSTEM_PROMPT = {
    "type": "text",
    "text": """당신은 중·고등학생을 위한 Sungblab AI 교육 도우미입니다.
- 친근하고 명확한 설명으로 학생의 자기주도적 학습을 돕습니다
- 단계별 사고과정을 안내하여 스스로 생각하도록 합니다
- 불확실한 내용은 추가 확인하고, 교육적 가치를 중시합니다""",
    "cache_control": {"type": "ephemeral"}
}

# 수행평가용 상세 프롬프트
ASSIGNMENT_PROMPT = {
    "type": "text",
    "text": """[수행평가 도우미]
당신은 학생들의 수행평가를 전문적으로 지원하는 AI 도우미입니다.

1. 과제 요구사항 분석
   - 평가 기준표, 주제, 제출 방식, 기한 등을 명확히 파악
   - 실제 보고서/발표 자료 예시로 아이디어 확장 지원
   
2. 아이디어 발전 & 피드백
   - 학생의 초기 생각을 존중하고 발전시키도록 유도
   - 사고연쇄(CoT)로 단계별 사고 과정 안내
   
3. 평가 기준 고려
   - 루브릭(창의성, 논리성, 발표력 등) 기반 구체적 조언
   - 최종 점수와 학생 역량 동시 성장 유도
   
4. 친근한 소통
   - 중·고등학생 수준의 언어 사용
   - 응원과 격려 표현
   - 전문용어는 필요시 쉽게 설명

※ 유의사항
- 학생이 직접 작성·실행하도록 안내 (표절 금지)
- 필요시 수행평가-생기부 연계 방법 제시
- 추가 고민을 유도하는 질문으로 마무리""",
    "cache_control": {"type": "ephemeral"}
}

# 생기부용 상세 프롬프트
RECORD_PROMPT = {
    "type": "text",
    "text": """[생기부(학교생활기록부) 도우미]
당신은 학교생활기록부 작성을 전문적으로 지원하는 AI 도우미입니다.

1. 작성 원칙
   - 음슴체 사용 ("~함", "~을 보임")
   - 구체적 사례 중심 서술
   - 교육부 지침 엄격 준수
   
2. 항목별 특징
   - 교과 세특: 수행평가/수업활동 중심
   - 창체: 자율/동아리/진로활동 구분
   - 행특: 학습/행동/인성 통합적 관찰
   
3. 분량 제한
   - 일반교과: 1500바이트
   - 진로과목: 2100바이트
   - 창체영역: 500자
   
4. 금지사항
   - 교외 수상, 공인어학시험 성적 기재 금지
   - 사교육 유발 요소 배제
   - 추상적 표현 지양
   
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
        "max_tokens": 4096,  # 수행평가는 긴 설명이 필요할 수 있음
        "temperature": 0.7   # 창의적인 답변 허용
    },
    "record": {
        "max_tokens": 8192,  # 생기부는 비교적 짧고 명확하게
        "temperature": 0.3   # 보수적이고 안정적인 답변
    }
}

# 파일 업로드 관련 상수
ALLOWED_MODELS = ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"]
MULTIMODAL_MODELS = ["claude-3-5-sonnet-20241022"]  # 멀티모달을 지원하는 모델 리스트
MAX_FILE_SIZE = 32 * 1024 * 1024  # 32MB
MAX_PDF_PAGES = 100
MAX_IMAGE_DIMENSION = 8000

class ChatRequest(BaseModel):
    model: str
    messages: List[Dict[str, Any]]
    project_type: Optional[str] = None

class FileInfo(BaseModel):
    type: str
    name: str
    data: str

class ChatMessageCreate(BaseModel):
    content: str
    role: str
    file: Optional[FileInfo] = None

def count_tokens(request: ChatRequest) -> dict:
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
            # 토큰 계산 (동기 방식)
            response = client.messages.count_tokens(
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
            
            print(f"Token calculation details:")
            print(f"  Is first message: {is_first_message}")
            print(f"  Project type: {request.project_type}")
            print(f"  System blocks: {len(system)}")
            print(f"  Message count: {len(messages)}")
            print(f"  Base tokens: {result['base_input_tokens']}")
            
            return result
            
        except Exception as e:
            print(f"Token counting API error: {str(e)}")
            raise
            
    except Exception as e:
        print(f"Error counting tokens: {str(e)}")
        return {"base_input_tokens": 0, "cache_write_tokens": 0, "cache_hit_tokens": 0}

router = APIRouter()
client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

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
        print(f"Starting to process file: {file.filename}")
        contents = await file.read()
        base64_data = base64.b64encode(contents).decode('utf-8')
        print(f"File processed successfully, size: {len(contents)} bytes")
        return base64_data, file.content_type
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        raise

@router.post("/{project_id}/chats/{chat_id}/chat")
async def stream_project_chat(
    *,
    db: Session = Depends(deps.get_db),
    project_id: str,
    chat_id: str,
    request: str = Form(...),
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """Stream chat response in project."""
    try:
        project = crud_project.get(db=db, id=project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        chat = crud_project.get_chat(db=db, project_id=project_id, chat_id=chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")

        request_data = json.loads(request)
        if request_data["model"] not in ALLOWED_MODELS:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid model specified. Allowed models: {ALLOWED_MODELS}"
            )

        # 파일이 있고 선택된 모델이 멀티모달을 지원하지 않는 경우
        if file and request_data["model"] not in MULTIMODAL_MODELS:
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

        async def generate_response():
            try:
                # 사용자 메시지 저장 (파일 처리 포함)
                user_message = request_data["messages"][-1]
                
                # 파일 정보 구성
                file_info = None
                if file_data:
                    file_info = FileInfo(
                        type=file_type,
                        name=file.filename,
                        data=file_data
                    )
                
                # 메시지 저장
                crud_project.create_chat_message(
                    db=db,
                    project_id=project_id,
                    chat_id=chat_id,
                    obj_in=ChatMessageCreate(
                        content=user_message["content"],
                        role="user",
                        file=file_info
                    )
                )

                # 토큰 카운팅
                token_counts = count_tokens(
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
                is_first_message = len(request_data["messages"]) <= 1
                
                if is_first_message:
                    if project.type == "assignment":
                        system.append(ASSIGNMENT_PROMPT)
                    elif project.type == "record":
                        system.append(RECORD_PROMPT)

                # 프로젝트 설정
                default_settings = PROJECT_DEFAULT_SETTINGS.get(project.type, {
                    "max_tokens": 4096,
                    "temperature": 0.7
                })
                
                max_tokens = project.settings.get('max_tokens', default_settings["max_tokens"]) if project.settings else default_settings["max_tokens"]
                temperature = project.settings.get('temperature', default_settings["temperature"]) if project.settings else default_settings["temperature"]

                # 파일이 있는 경우 메시지 구성
                messages = []
                if file_data and file_type and request_data["model"] in MULTIMODAL_MODELS:
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
                    
                    if request_data["messages"] and request_data["messages"][-1]["content"]:
                        user_message["content"].append({
                            "type": "text",
                            "text": request_data["messages"][-1]["content"]
                        })
                    
                    messages = request_data["messages"][:-1] if request_data["messages"] else []
                    messages.append(user_message)
                else:
                    messages = recent_messages

                # AI 응답 생성 및 스트리밍
                accumulated_content = ""
                response = client.messages.create(
                    model=request_data["model"],
                    system=system,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=True
                )

                for chunk in response:
                    if hasattr(chunk, 'type') and chunk.type == "content_block_delta":
                        text = chunk.delta.text
                        accumulated_content += text
                        yield f"data: {json.dumps({'content': text})}\n\n"

                # AI 응답 메시지 저장
                if accumulated_content:
                    crud_project.create_chat_message(
                        db=db,
                        project_id=project_id,
                        chat_id=chat_id,
                        obj_in=ChatMessageCreate(
                            content=accumulated_content,
                            role="assistant"
                        )
                    )

                # 토큰 사용량 저장
                output_token_response = client.messages.count_tokens(
                    model=request_data["model"],
                    messages=[{"role": "assistant", "content": accumulated_content}]
                )
                output_tokens = output_token_response.input_tokens

                if current_user:
                    chat_type = f"project_{project.type}" if project and project.type else None
                    crud_stats.create_token_usage(
                        db=db,
                        user_id=str(current_user.id),
                        room_id=chat_id,
                        model=request_data["model"],
                        input_tokens=token_counts['base_input_tokens'],
                        cache_write_tokens=token_counts['cache_write_tokens'],
                        cache_hit_tokens=token_counts['cache_hit_tokens'],
                        output_tokens=output_tokens,
                        timestamp=datetime.now(),
                        chat_type=chat_type
                    )

                print(f"Token usage saved - Project chat:")
                print(f"  Project type: {project.type}")
                print(f"  Chat type: {chat_type}")
                print(f"  Input tokens: {token_counts['base_input_tokens']}")
                print(f"  Cache write: {token_counts['cache_write_tokens']}")
                print(f"  Cache hit: {token_counts['cache_hit_tokens']}")
                print(f"  Output tokens: {output_tokens}")

            except Exception as e:
                error_message = f"Error in streaming response: {str(e)}"
                print(error_message)
                yield f"data: {json.dumps({'error': error_message})}\n\n"

        return StreamingResponse(
            generate_response(),
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