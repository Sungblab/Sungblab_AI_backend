from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models.project import Project, ProjectChat, ProjectMessage
from app.models.user import User
from app.models.subscription import Subscription
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.schemas.chat import ChatCreate, ChatUpdate, ChatMessageCreate
import uuid
from datetime import datetime

# 파일 상단에 MODEL_GROUP_MAPPING 추가
MODEL_GROUP_MAPPING = {
    "claude-3-5-sonnet-20241022": "claude",
    "claude-3-5-haiku-20241022": "claude",
    "sonar-pro": "sonar",
    "sonar": "sonar",
    "sonar-reasoning": "sonar",
    "deepseek-reasoner": "deepseek",
}

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
def create_chat(db: Session, *, project_id: str, obj_in: ChatCreate, user_id: str) -> ProjectChat:
    # 프로젝트 타입 가져오기
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError("Project not found")

    db_obj = ProjectChat(
        id=str(uuid.uuid4()),
        name=obj_in.name,
        project_id=project_id,
        user_id=user_id,  # 사용자 ID 추가
        type=project.type  # 항상 부모 프로젝트의 타입을 사용
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def get_chat(db: Session, *, project_id: str, chat_id: str) -> Optional[ProjectChat]:
    return db.query(ProjectChat).filter(
        ProjectChat.project_id == project_id,
        ProjectChat.id == chat_id
    ).first()

def update_chat(
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
    
    # 메시지 조회 전 채팅 정보 출력
    
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
            files=[file.dict() for file in obj_in.files] if obj_in.files else None,
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