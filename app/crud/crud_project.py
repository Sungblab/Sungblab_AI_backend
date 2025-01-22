from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models.project import Project, ProjectChat, ProjectMessage
from app.models.user import User
from app.models.subscription import Subscription
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.schemas.chat import ChatCreate, ChatUpdate, ChatMessageCreate
import uuid
from datetime import datetime

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
        print(f"Chat not found for project_id: {project_id}, chat_id: {chat_id}")
        return []
    
    # 메시지 조회 전 채팅 정보 출력
    print(f"Found chat: {chat.id}, project_id: {chat.project_id}")
    
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
            "file": message.file
        }
        for message in messages
    ]
    
    print(f"Retrieved {len(result)} messages for chat {chat_id}")
    return result

def create_chat_message(
    db: Session, *, project_id: str, chat_id: str, obj_in: ChatMessageCreate
) -> Dict[str, Any]:
    chat = get_chat(db, project_id=project_id, chat_id=chat_id)
    if not chat:
        print(f"Failed to create message: Chat not found (project_id: {project_id}, chat_id: {chat_id})")
        raise ValueError("Chat not found")
    
    # 새 메시지 생성
    try:
        db_message = ProjectMessage(
            content=obj_in.content,
            role=obj_in.role,
            room_id=chat_id,
            file=obj_in.file.dict() if obj_in.file else None
        )
        
        # 채팅과 메시지 연결
        chat.messages.append(db_message)
        
        # 메시지 카운트 증가 (디버깅 로그 추가)
        print(f"Attempting to increment message count for user_id: {chat.user_id}")
        user = db.query(User).filter(User.id == chat.user_id).first()
        if user:
            print(f"Found user: {user.id}, current message count: {user.message_count}")
            if obj_in.role == "assistant":  # AI 응답일 때만 카운트
                user.message_count = (user.message_count or 0) + 1
                print(f"Incremented message count to: {user.message_count}")
                
                # 구독 정보의 메시지 카운트도 업데이트
                subscription = db.query(Subscription).filter(Subscription.user_id == chat.user_id).first()
                if subscription:
                    subscription.message_count = (subscription.message_count or 0) + 1
                    print(f"Incremented subscription message count to: {subscription.message_count}")
                    db.add(subscription)
                else:
                    print(f"Warning: Subscription not found for user_id: {chat.user_id}")
                
                db.add(user)
        else:
            print(f"Warning: User not found for user_id: {chat.user_id}")
        
        # 세션에 추가하고 커밋
        db.add(db_message)
        db.commit()
        db.refresh(db_message)
        
        print(f"Successfully created message for chat {chat_id}")
        
        # 응답 형식에 맞게 반환
        return db_message.to_dict()
    except Exception as e:
        print(f"Error creating message: {str(e)}")
        db.rollback()
        raise 