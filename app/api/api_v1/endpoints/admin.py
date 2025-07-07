from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.api import deps
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.admin import UserResponse, UserUpdate, AdminOverviewResponse
from app.crud import crud_user, crud_admin
from app.crud import crud_project
from app.crud import crud_subscription
from app.models.subscription import Subscription, SubscriptionPlan, KST, PLAN_LIMITS
from datetime import datetime, timedelta
from pydantic import BaseModel
from app.core.utils import get_kr_time

router = APIRouter()

def get_current_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="관리자 권한이 필요합니다."
        )
    return current_user

@router.get("/users", response_model=List[UserResponse])
def get_users(
    db: Session = Depends(deps.get_db),
    _: User = Depends(get_current_admin),
    skip: int = 0,
    limit: int = 100
):
    """
    모든 사용자 목록을 조회합니다.
    """
    users = crud_user.get_users(db, skip=skip, limit=limit)
    return users

@router.patch("/users/{user_id}/admin-status")
def toggle_admin_status(
    user_id: str,
    db: Session = Depends(deps.get_db),
    _: User = Depends(get_current_admin)
):
    """
    사용자의 관리자 권한을 토글합니다.
    """
    user = crud_user.get_user(db, id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    
    # 자기 자신의 관리자 권한은 변경할 수 없음
    if user.id == _.id:
        raise HTTPException(status_code=400, detail="자신의 관리자 권한은 변경할 수 없습니다.")
    
    user.is_superuser = not user.is_superuser
    db.commit()
    return {"is_admin": user.is_superuser}

@router.patch("/users/{user_id}/status")
def toggle_user_status(
    user_id: str,
    db: Session = Depends(deps.get_db),
    _: User = Depends(get_current_admin)
):
    """
    사용자의 활성화 상태를 토글합니다.
    """
    user = crud_user.get_user(db, id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    
    # 자기 자신은 비활성화할 수 없음
    if user.id == _.id:
        raise HTTPException(status_code=400, detail="자신의 계정은 비활성화할 수 없습니다.")
    
    user.is_active = not user.is_active
    db.commit()
    return {"is_active": user.is_active}

@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    db: Session = Depends(deps.get_db),
    _: User = Depends(get_current_admin)
):
    """
    사용자를 삭제합니다. 토큰 사용량 데이터는 보존됩니다.
    """
    try:
        user = crud_user.get_user(db, id=user_id)
        if not user:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
        
        # 자기 자신은 삭제할 수 없음
        if user.id == _.id:
            raise HTTPException(status_code=400, detail="자신의 계정은 삭제할 수 없습니다.")
        
        # 구독 정보에서 user_id만 None으로 설정하고 토큰 사용량은 보존
        subscription = db.query(Subscription).filter(
            Subscription.user_id == str(user.id)
        ).first()
        if subscription:
            subscription.user_id = None
            db.flush()
        
        # 사용자 삭제
        db.delete(user)
        db.commit()
        return {"message": "사용자가 삭제되었습니다."}
    except Exception as e:
        db.rollback()
        print(f"사용자 삭제 중 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"사용자 삭제 중 오류가 발생했습니다: {str(e)}"
        )

@router.get("/subscriptions", response_model=List[dict])
def get_subscriptions(
    db: Session = Depends(deps.get_db),
    _: User = Depends(get_current_admin)
):
    """모든 구독 정보를 조회합니다."""
    subscriptions = db.query(Subscription).all()
    return [sub.to_dict() for sub in subscriptions]

# 요청 데이터 모델 추가
class SubscriptionUpdate(BaseModel):
    plan: SubscriptionPlan
    update_limits: bool = True

@router.patch("/subscriptions/{user_id}")
def update_subscription(
    user_id: str,
    update_data: SubscriptionUpdate,
    db: Session = Depends(deps.get_db),
    _: User = Depends(get_current_admin)
):
    """사용자의 구독 플랜을 변경합니다."""
    updated_subscription = crud_subscription.update_subscription_plan(
        db=db,
        user_id=user_id,
        plan=update_data.plan,
        update_limits=update_data.update_limits
    )
    
    if not updated_subscription:
        raise HTTPException(status_code=404, detail="구독 정보를 찾을 수 없습니다.")
    
    return updated_subscription.to_dict()

@router.post("/users/{user_id}/reset-usage")
def reset_usage(
    user_id: str,
    db: Session = Depends(deps.get_db),
    _: User = Depends(get_current_admin)
):
    """사용자의 사용량을 초기화합니다."""
    updated_subscription = crud_subscription.reset_usage(db=db, user_id=user_id)
    if not updated_subscription:
        raise HTTPException(status_code=404, detail="구독 정보를 찾을 수 없습니다.")
    
    return updated_subscription.to_dict()

@router.get("/overview", response_model=AdminOverviewResponse)
def get_admin_overview(
    db: Session = Depends(deps.get_db),
    current_admin: User = Depends(get_current_admin)
):
    """
    관리자 대시보드의 Overview 데이터를 반환합니다.
    """
    try:
        # 사용자 통계
        user_stats = crud_admin.get_user_stats(db)
        
        # 구독 통계
        subscription_stats = crud_admin.get_subscription_stats(db)
        
        # 최근 가입자
        recent_users = crud_admin.get_recent_users(db)
        
        # AI 모델 사용량
        model_usage_stats = crud_admin.get_model_usage_stats(db)
        
        return {
            "user_stats": user_stats,
            "subscription_stats": subscription_stats,
            "recent_users": recent_users,
            "model_usage_stats": model_usage_stats
        }
        
    except Exception as e:
        print(f"Overview 데이터 조회 중 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Overview 데이터를 불러오는데 실패했습니다: {str(e)}"
        )

@router.post("/subscriptions/renew-expired")
def renew_expired_subscriptions(
    db: Session = Depends(deps.get_db),
    _: User = Depends(get_current_admin)
):
    """만료된 모든 구독을 갱신합니다."""
    try:
        current_time = get_kr_time()
        
        # 만료된 구독 조회
        expired_subscriptions = db.query(Subscription).filter(
            Subscription.end_date < current_time
        ).all()
        
        renewed_count = 0
        for subscription in expired_subscriptions:
            # 구독 갱신
            subscription.start_date = current_time
            subscription.end_date = current_time + timedelta(days=30)
            subscription.renewal_date = subscription.end_date
            subscription.status = "active"
            
            # 무료 플랜으로 설정 (유료 플랜이었다면)
            if subscription.plan != SubscriptionPlan.FREE:
                subscription.plan = SubscriptionPlan.FREE
                subscription.group_limits = PLAN_LIMITS[SubscriptionPlan.FREE]
            
            # 사용량 초기화
            subscription.reset_usage()
            
            renewed_count += 1
        
        db.commit()
        
        return {
            "message": f"{renewed_count}개의 만료된 구독이 갱신되었습니다.",
            "renewed_count": renewed_count
        }
    except Exception as e:
        db.rollback()
        print(f"구독 갱신 중 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"구독 갱신 중 오류가 발생했습니다: {str(e)}"
        )

# 채팅 데이터 조회 API 추가
@router.get("/chat/overview")
def get_chat_overview(
    db: Session = Depends(deps.get_db),
    _: User = Depends(get_current_admin)
):
    """채팅 데이터 개요를 조회합니다."""
    from app.models.chat import ChatMessage
    from app.models.chat_room import ChatRoom
    from app.models.project import Project, ProjectChat, ProjectMessage
    from sqlalchemy import func, distinct
    
    # 일반 채팅 통계
    regular_chat_stats = db.query(
        func.count(distinct(ChatRoom.id)).label('total_rooms'),
        func.count(ChatMessage.id).label('total_messages'),
        func.count(distinct(ChatRoom.user_id)).label('total_users')
    ).join(ChatMessage, ChatRoom.id == ChatMessage.room_id).first()
    
    # 프로젝트 채팅 통계
    project_chat_stats = db.query(
        func.count(distinct(ProjectChat.id)).label('total_rooms'),
        func.count(ProjectMessage.id).label('total_messages'),
        func.count(distinct(Project.user_id)).label('total_users')
    ).join(ProjectMessage, ProjectChat.id == ProjectMessage.room_id)\
     .join(Project, ProjectChat.project_id == Project.id).first()
    
    # 최근 활동 (최근 24시간)
    recent_cutoff = datetime.now() - timedelta(hours=24)
    recent_regular = db.query(func.count(ChatMessage.id)).filter(
        ChatMessage.created_at >= recent_cutoff
    ).scalar() or 0
    
    recent_project = db.query(func.count(ProjectMessage.id)).filter(
        ProjectMessage.created_at >= recent_cutoff
    ).scalar() or 0
    
    return {
        "regular_chat": {
            "total_rooms": regular_chat_stats.total_rooms or 0,
            "total_messages": regular_chat_stats.total_messages or 0,
            "total_users": regular_chat_stats.total_users or 0,
            "recent_messages": recent_regular
        },
        "project_chat": {
            "total_rooms": project_chat_stats.total_rooms or 0,
            "total_messages": project_chat_stats.total_messages or 0,
            "total_users": project_chat_stats.total_users or 0,
            "recent_messages": recent_project
        }
    }

@router.get("/chat/messages")
def get_chat_messages(
    db: Session = Depends(deps.get_db),
    _: User = Depends(get_current_admin),
    chat_type: str = "regular",  # regular, project, all
    user_id: str = None,
    skip: int = 0,
    limit: int = 50
):
    """채팅 메시지를 조회합니다."""
    from app.models.chat import ChatMessage
    from app.models.chat_room import ChatRoom
    from app.models.project import Project, ProjectChat, ProjectMessage
    from app.models.user import User
    
    messages = []
    
    if chat_type in ["regular", "all"]:
        # 일반 채팅 메시지
        query = db.query(
            ChatMessage.id,
            ChatMessage.content,
            ChatMessage.role,
            ChatMessage.created_at,
            ChatMessage.updated_at,
            ChatMessage.files,
            ChatMessage.citations,
            ChatMessage.reasoning_content,
            ChatMessage.thought_time,
            ChatRoom.name.label('room_name'),
            ChatRoom.user_id,
            User.email.label('user_email'),
            User.full_name.label('user_name')
        ).join(ChatRoom, ChatMessage.room_id == ChatRoom.id)\
         .join(User, ChatRoom.user_id == User.id)
        
        if user_id:
            query = query.filter(ChatRoom.user_id == user_id)
        
        regular_messages = query.order_by(ChatMessage.created_at.desc())\
                               .offset(skip).limit(limit).all()
        
        for msg in regular_messages:
            messages.append({
                "id": msg.id,
                "content": msg.content,
                "role": msg.role,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "updated_at": msg.updated_at.isoformat() if msg.updated_at else None,
                "files": msg.files,
                "citations": msg.citations,
                "reasoning_content": msg.reasoning_content,
                "thought_time": msg.thought_time,
                "room_name": msg.room_name,
                "user_id": msg.user_id,
                "user_email": msg.user_email,
                "user_name": msg.user_name,
                "chat_type": "regular"
            })
    
    if chat_type in ["project", "all"]:
        # 프로젝트 채팅 메시지
        query = db.query(
            ProjectMessage.id,
            ProjectMessage.content,
            ProjectMessage.role,
            ProjectMessage.created_at,
            ProjectMessage.updated_at,
            ProjectMessage.files,
            ProjectMessage.citations,
            ProjectMessage.reasoning_content,
            ProjectMessage.thought_time,
            ProjectChat.name.label('room_name'),
            Project.name.label('project_name'),
            Project.user_id,
            User.email.label('user_email'),
            User.full_name.label('user_name')
        ).join(ProjectChat, ProjectMessage.room_id == ProjectChat.id)\
         .join(Project, ProjectChat.project_id == Project.id)\
         .join(User, Project.user_id == User.id)
        
        if user_id:
            query = query.filter(Project.user_id == user_id)
        
        project_messages = query.order_by(ProjectMessage.created_at.desc())\
                               .offset(skip).limit(limit).all()
        
        for msg in project_messages:
            messages.append({
                "id": msg.id,
                "content": msg.content,
                "role": msg.role,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "updated_at": msg.updated_at.isoformat() if msg.updated_at else None,
                "files": msg.files,
                "citations": msg.citations,
                "reasoning_content": msg.reasoning_content,
                "thought_time": msg.thought_time,
                "room_name": msg.room_name,
                "project_name": msg.project_name,
                "user_id": msg.user_id,
                "user_email": msg.user_email,
                "user_name": msg.user_name,
                "chat_type": "project"
            })
    
    # 시간순 정렬 (None 값 처리)
    messages.sort(key=lambda x: x['created_at'] or '', reverse=True)
    
    return {
        "messages": messages[:limit],
        "total": len(messages)
    }

@router.get("/chat/rooms")
def get_chat_rooms(
    db: Session = Depends(deps.get_db),
    _: User = Depends(get_current_admin),
    chat_type: str = "regular",  # regular, project, all
    user_id: str = None,
    skip: int = 0,
    limit: int = 50
):
    """채팅방을 조회합니다."""
    from app.models.chat import ChatMessage
    from app.models.chat_room import ChatRoom
    from app.models.project import Project, ProjectChat, ProjectMessage
    from app.models.user import User
    from sqlalchemy import func
    
    rooms = []
    
    if chat_type in ["regular", "all"]:
        # 일반 채팅방
        query = db.query(
            ChatRoom.id,
            ChatRoom.name,
            ChatRoom.created_at,
            ChatRoom.updated_at,
            ChatRoom.user_id,
            User.email.label('user_email'),
            User.full_name.label('user_name'),
            func.count(ChatMessage.id).label('message_count')
        ).join(User, ChatRoom.user_id == User.id)\
         .outerjoin(ChatMessage, ChatRoom.id == ChatMessage.room_id)\
         .group_by(ChatRoom.id, ChatRoom.name, ChatRoom.created_at, 
                   ChatRoom.updated_at, ChatRoom.user_id, User.email, User.full_name)
        
        if user_id:
            query = query.filter(ChatRoom.user_id == user_id)
        
        regular_rooms = query.order_by(ChatRoom.created_at.desc())\
                            .offset(skip).limit(limit).all()
        
        for room in regular_rooms:
            rooms.append({
                "id": room.id,
                "name": room.name,
                "created_at": room.created_at.isoformat() if room.created_at else None,
                "updated_at": room.updated_at.isoformat() if room.updated_at else None,
                "user_id": room.user_id,
                "user_email": room.user_email,
                "user_name": room.user_name,
                "message_count": room.message_count or 0,
                "chat_type": "regular"
            })
    
    if chat_type in ["project", "all"]:
        # 프로젝트 채팅방
        query = db.query(
            ProjectChat.id,
            ProjectChat.name,
            ProjectChat.created_at,
            ProjectChat.updated_at,
            Project.name.label('project_name'),
            Project.user_id,
            User.email.label('user_email'),
            User.full_name.label('user_name'),
            func.count(ProjectMessage.id).label('message_count')
        ).join(Project, ProjectChat.project_id == Project.id)\
         .join(User, Project.user_id == User.id)\
         .outerjoin(ProjectMessage, ProjectChat.id == ProjectMessage.room_id)\
         .group_by(ProjectChat.id, ProjectChat.name, ProjectChat.created_at,
                   ProjectChat.updated_at, Project.name, Project.user_id, 
                   User.email, User.full_name)
        
        if user_id:
            query = query.filter(Project.user_id == user_id)
        
        project_rooms = query.order_by(ProjectChat.created_at.desc())\
                            .offset(skip).limit(limit).all()
        
        for room in project_rooms:
            rooms.append({
                "id": room.id,
                "name": room.name,
                "created_at": room.created_at.isoformat() if room.created_at else None,
                "updated_at": room.updated_at.isoformat() if room.updated_at else None,
                "project_name": room.project_name,
                "user_id": room.user_id,
                "user_email": room.user_email,
                "user_name": room.user_name,
                "message_count": room.message_count or 0,
                "chat_type": "project"
            })
    
    # 시간순 정렬 (None 값 처리)
    rooms.sort(key=lambda x: x['created_at'] or '', reverse=True)
    
    return {
        "rooms": rooms[:limit],
        "total": len(rooms)
    }

@router.get("/chat/users")
def get_chat_users(
    db: Session = Depends(deps.get_db),
    _: User = Depends(get_current_admin)
):
    """채팅을 사용하는 사용자 목록을 조회합니다."""
    from app.models.chat_room import ChatRoom
    from app.models.project import Project
    from app.models.user import User
    from sqlalchemy import distinct, func
    
    # 일반 채팅 사용자
    regular_users = db.query(
        User.id,
        User.email,
        User.full_name,
        func.count(distinct(ChatRoom.id)).label('room_count')
    ).join(ChatRoom, User.id == ChatRoom.user_id)\
     .group_by(User.id, User.email, User.full_name).all()
    
    # 프로젝트 채팅 사용자
    project_users = db.query(
        User.id,
        User.email,
        User.full_name,
        func.count(distinct(Project.id)).label('project_count')
    ).join(Project, User.id == Project.user_id)\
     .group_by(User.id, User.email, User.full_name).all()
    
    # 사용자 정보 병합
    users_dict = {}
    
    for user in regular_users:
        users_dict[user.id] = {
            "id": user.id,
            "email": user.email,
            "name": user.full_name,
            "regular_rooms": user.room_count,
            "project_rooms": 0
        }
    
    for user in project_users:
        if user.id in users_dict:
            users_dict[user.id]["project_rooms"] = user.project_count
        else:
            users_dict[user.id] = {
                "id": user.id,
                "email": user.email,
                "name": user.full_name,
                "regular_rooms": 0,
                "project_rooms": user.project_count
            }
    
    return list(users_dict.values()) 