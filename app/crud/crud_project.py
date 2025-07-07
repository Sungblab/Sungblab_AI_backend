from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models.project import Project, ProjectChat, ProjectMessage
from app.models.user import User
from app.models.subscription import Subscription
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectChatCreate, ProjectChatUpdate
from app.schemas.chat import ChatCreate, ChatUpdate, ChatMessageCreate
import uuid
from datetime import datetime
from app.core.models import get_model_config, ModelProvider

# 모델 그룹 매핑 (제미나이만)
MODEL_GROUP_MAPPING = {
    "gemini-2.5-pro": "gemini",
    "gemini-2.5-flash": "gemini",
}

# 모델별 프로바이더 매핑 - 제미나이만 사용
def get_model_provider_mapping():
    from app.core.models import ACTIVE_MODELS
    mapping = {}
    for model_name, config in ACTIVE_MODELS.items():
        if config.provider == ModelProvider.GOOGLE:
            mapping[model_name] = "gemini"
        else:
            mapping[model_name] = "unknown"
    return mapping

def create_with_owner(
    db: Session, *, obj_in: ProjectCreate, owner_id: str
) -> Project:
    obj_in_data = obj_in.dict()
    obj_in_data["user_id"] = owner_id
    obj_in_data["created_at"] = datetime.now()
    obj_in_data["updated_at"] = datetime.now()
    db_obj = Project(**obj_in_data)
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def get_multi_by_owner(
    db: Session, *, owner_id: str, skip: int = 0, limit: int = 100
) -> list[Project]:
    return (
        db.query(Project)
        .filter(Project.user_id == owner_id)
        .offset(skip)
        .limit(limit)
        .all()
    )

def create_chat(
    db: Session, *, project_id: str, obj_in: ProjectChatCreate, owner_id: str, chat_id: Optional[str] = None
) -> ProjectChat:
    # 프로젝트 소유권 확인
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == owner_id
    ).first()
    if not project:
        raise ValueError("Project not found or access denied")
    
    # 채팅 생성
    chat_data = obj_in.dict()
    chat_data["project_id"] = project_id
    chat_data["user_id"] = owner_id  # user_id 추가
    chat_data["created_at"] = datetime.now()
    chat_data["updated_at"] = datetime.now()
    
    # 특정 ID가 제공된 경우 사용
    if chat_id:
        chat_data["id"] = chat_id
    
    db_chat = ProjectChat(**chat_data)
    db.add(db_chat)
    db.commit()
    db.refresh(db_chat)
    return db_chat

def get_project_chats(
    db: Session, *, project_id: str, owner_id: str
) -> list[ProjectChat]:
    # 프로젝트 소유권 확인
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == owner_id
    ).first()
    if not project:
        return []
    
    return db.query(ProjectChat).filter(
        ProjectChat.project_id == project_id
    ).all()

def update_chat(
    db: Session, *, chat_id: str, obj_in: ProjectChatUpdate, project_id: str, owner_id: str
) -> ProjectChat:
    # 프로젝트 소유권 확인
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == owner_id
    ).first()
    if not project:
        raise ValueError("Project not found or access denied")
    
    # 채팅 업데이트
    chat = db.query(ProjectChat).filter(
        ProjectChat.id == chat_id,
        ProjectChat.project_id == project_id
    ).first()
    if not chat:
        raise ValueError("Chat not found")
    
    update_data = obj_in.dict(exclude_unset=True)
    update_data["updated_at"] = datetime.now()
    
    for field, value in update_data.items():
        setattr(chat, field, value)
    
    db.commit()
    db.refresh(chat)
    return chat

def delete_chat(
    db: Session, *, chat_id: str, project_id: str, owner_id: str
) -> bool:
    # 프로젝트 소유권 확인
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == owner_id
    ).first()
    if not project:
        return False
    
    # 채팅 삭제
    chat = db.query(ProjectChat).filter(
        ProjectChat.id == chat_id,
        ProjectChat.project_id == project_id
    ).first()
    if not chat:
        return False
    
    db.delete(chat)
    db.commit()
    return True

def create(db: Session, *, obj_in: ProjectCreate, user_id: str) -> Project:
    db_obj = Project(
        id=str(uuid.uuid4()),
        name=obj_in.name,
        type=obj_in.type,
        description=obj_in.description,
        system_instruction=obj_in.system_instruction,
        settings=obj_in.settings,
        user_id=user_id
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def get(db: Session, id: str) -> Optional[Project]:
    return db.query(Project).filter(Project.id == id).first()

def get_multi(db: Session, *, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
    projects = db.query(Project).offset(skip).limit(limit).all()
    return [project.to_dict(include_chats=True) for project in projects]

def get_multi_by_user(
    db: Session, *, user_id: str, skip: int = 0, limit: int = 100
) -> List[Dict[str, Any]]:
    projects = (
        db.query(Project)
        .filter(Project.user_id == user_id)
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [project.to_dict(include_chats=True) for project in projects]

def update(db: Session, *, db_obj: Project, obj_in: ProjectUpdate) -> Project:
    update_data = obj_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_obj, field, value)
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def remove(db: Session, *, id: str) -> Project:
    obj = db.query(Project).get(id)
    db.delete(obj)
    db.commit()
    return obj

# 프로젝트 채팅 관련 CRUD 작업
def get_chat(db: Session, *, project_id: str, chat_id: str) -> Optional[ProjectChat]:
    return db.query(ProjectChat).filter(
        ProjectChat.project_id == project_id,
        ProjectChat.id == chat_id
    ).first()

def update_chat_by_id(
    db: Session, *, project_id: str, chat_id: str, obj_in: ChatUpdate
) -> Dict[str, Any]:
    db_obj = get_chat(db, project_id=project_id, chat_id=chat_id)
    if not db_obj:
        raise ValueError("Chat not found")
        
    update_data = obj_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_obj, field, value)
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj.to_dict()

def get_chat_messages(db: Session, *, project_id: str, chat_id: str) -> List[Dict[str, Any]]:
    chat = get_chat(db, project_id=project_id, chat_id=chat_id)
    if not chat:
        return []
    
    # 메시지 직접 쿼리
    messages = db.query(ProjectMessage).filter(
        ProjectMessage.room_id == chat_id
    ).order_by(ProjectMessage.created_at.asc()).all()
    
    result = [
        {
            "id": str(message.id),
            "content": message.content,
            "role": message.role,
            "room_id": message.room_id,
            "created_at": message.created_at.isoformat() if message.created_at else None,
            "updated_at": message.updated_at.isoformat() if message.updated_at else None,
            "files": message.files,
            "citations": message.citations,
            "reasoning_content": message.reasoning_content
        }
        for message in messages
    ]
    
    return result

def create_chat_message(
    db: Session, *, project_id: str, chat_id: str, obj_in: ChatMessageCreate
) -> Dict[str, Any]:
    chat = get_chat(db, project_id=project_id, chat_id=chat_id)
    if not chat:
        raise ValueError("Chat not found")
    
    try:
        current_time = datetime.now()
        db_message = ProjectMessage(
            content=obj_in.content,
            role=obj_in.role,
            room_id=chat_id,
            files=[file if isinstance(file, dict) else file.__dict__ for file in obj_in.files] if obj_in.files else None,
            citations=obj_in.citations,
            reasoning_content=obj_in.reasoning_content,
            thought_time=obj_in.thought_time,
            created_at=current_time,
            updated_at=current_time
        )
        
        # 채팅과 메시지 연결
        chat.messages.append(db_message)
        
        # 메시지 카운트 증가 (수정된 부분)
        user = db.query(User).filter(User.id == chat.user_id).first()
        if user and obj_in.role == "assistant":
            # obj_in에서 model 속성이 있는지 확인
            model = getattr(obj_in, 'model', None)
            if model:
                model_group = MODEL_GROUP_MAPPING.get(model)
                if model_group:
                    user.message_counts[model_group] = user.message_counts.get(model_group, 0) + 1
                    db.add(user)
        
        db.add(db_message)
        db.commit()
        db.refresh(db_message)
        
        return db_message.to_dict()
    except Exception as e:
        db.rollback()
        raise 

def get_project_by_chat_id(db: Session, chat_id: str) -> Optional[Project]:
    """채팅 ID로 프로젝트를 찾는 함수"""
    chat = db.query(ProjectChat).filter(ProjectChat.id == chat_id).first()
    if not chat:
        return None
    return db.query(Project).filter(Project.id == chat.project_id).first() 