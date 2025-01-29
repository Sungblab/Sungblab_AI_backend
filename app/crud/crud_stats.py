from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from app.models.stats import TokenUsage
from app.models.project import ProjectChat, ProjectMessage
from app.models.chat_room import ChatRoom
from app.models.chat import ChatMessage
from app.models.user import User
from datetime import datetime
from typing import Optional, List, Dict
import uuid

def create_token_usage(
    db: Session,
    *,
    user_id: Optional[str],
    room_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    timestamp: datetime,
    chat_type: Optional[str] = None,
    cache_write_tokens: int = 0,
    cache_hit_tokens: int = 0
) -> TokenUsage:
    """토큰 사용량 기록을 생성합니다."""
    db_obj = TokenUsage(
        id=str(uuid.uuid4()),
        user_id=user_id,
        room_id=room_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        timestamp=timestamp,
        chat_type=chat_type,
        cache_write_tokens=cache_write_tokens,
        cache_hit_tokens=cache_hit_tokens
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def get_token_usage(
    db: Session,
    start_date: datetime,
    end_date: datetime,
    user_id: Optional[str] = None
) -> List[TokenUsage]:
    """토큰 사용량 통계를 조회합니다."""
    query = db.query(TokenUsage).filter(
        TokenUsage.timestamp >= start_date,
        TokenUsage.timestamp <= end_date
    )
    
    if user_id:
        query = query.filter(TokenUsage.user_id == user_id)
    
    return query.all()

def get_token_usage_history(
    db: Session,
    start: datetime,
    end: datetime,
    user_id: Optional[str] = None
) -> List[dict]:
    """토큰 사용 기록을 시간순으로 가져옵니다."""
    query = db.query(
        TokenUsage.timestamp,
        TokenUsage.model,
        TokenUsage.input_tokens,
        TokenUsage.output_tokens,
        TokenUsage.room_id,
        TokenUsage.chat_type,
        User.email.label('user_email'),
        User.full_name.label('user_name')
    ).join(
        User, TokenUsage.user_id == User.id
    ).filter(
        TokenUsage.timestamp.between(start, end)
    )

    if user_id:
        query = query.filter(TokenUsage.user_id == user_id)

    # 시간 역순으로 정렬
    query = query.order_by(desc(TokenUsage.timestamp))

    results = query.all()
    
    return [
        {
            "timestamp": usage.timestamp,
            "model": usage.model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "chat_type": "수행평가" if usage.chat_type == "project_assignment" else 
                        "생기부" if usage.chat_type == "project_record" else "Default",
            "user_email": usage.user_email,
            "user_name": usage.user_name
        }
        for usage in results
    ]

def get_chat_statistics(
    db: Session,
    start_date: datetime,
    end_date: datetime,
    user_id: Optional[str] = None
) -> Dict:
    """채팅 사용량 통계를 조회합니다."""
    
    try:
        # 사용자 정보 조회
        users = {
            str(user.id): {"email": user.email, "name": user.full_name or user.email.split('@')[0]}
            for user in db.query(User).all()
        }

        # 채팅방 수 쿼리 - 각각 별도로 실행
        project_chat_query = db.query(func.count(ProjectChat.id))
        chat_room_query = db.query(func.count(ChatRoom.id))
        
        if user_id:
            project_chat_query = project_chat_query.filter(ProjectChat.user_id == user_id)
            chat_room_query = chat_room_query.filter(ChatRoom.user_id == user_id)
        
        project_chat_count = project_chat_query.scalar() or 0
        chat_room_count = chat_room_query.scalar() or 0
        total_chats = project_chat_count + chat_room_count

        # 메시지 수 쿼리
        message_query = db.query(func.count(ChatMessage.id))
        project_message_query = db.query(func.count(ProjectMessage.id))
        
        if user_id:
            message_query = message_query.join(
                ChatRoom, ChatMessage.room_id == ChatRoom.id
            ).filter(ChatRoom.user_id == user_id)
            
            project_message_query = project_message_query.join(
                ProjectChat, ProjectMessage.room_id == ProjectChat.id
            ).filter(ProjectChat.user_id == user_id)
        
        message_count = message_query.scalar() or 0
        project_message_count = project_message_query.scalar() or 0
        total_messages = message_count + project_message_count

        # 사용자별 채팅방 수 쿼리
        user_chat_stats = db.query(
            ChatRoom.user_id,
            func.count(ChatRoom.id).label('chat_count')
        ).group_by(ChatRoom.user_id).all()

        user_project_stats = db.query(
            ProjectChat.user_id,
            func.count(ProjectChat.id).label('project_count')
        ).group_by(ProjectChat.user_id).all()

        # 사용자별 메시지 수 쿼리
        user_message_stats = db.query(
            ChatRoom.user_id,
            func.count(ChatMessage.id).label('message_count')
        ).join(
            ChatMessage, ChatMessage.room_id == ChatRoom.id
        ).group_by(ChatRoom.user_id).all()

        user_project_message_stats = db.query(
            ProjectChat.user_id,
            func.count(ProjectMessage.id).label('message_count')
        ).join(
            ProjectMessage, ProjectMessage.room_id == ProjectChat.id
        ).group_by(ProjectChat.user_id).all()

        # 사용자별 토큰 사용량 쿼리
        user_token_stats = db.query(
            TokenUsage.user_id,
            func.sum(TokenUsage.input_tokens).label('total_input_tokens'),
            func.sum(TokenUsage.output_tokens).label('total_output_tokens'),
            func.sum(TokenUsage.cache_write_tokens).label('total_cache_write_tokens'),
            func.sum(TokenUsage.cache_hit_tokens).label('total_cache_hit_tokens'),
            TokenUsage.chat_type
        ).group_by(TokenUsage.user_id, TokenUsage.chat_type).all()

        # 사용자별 통계 집계
        user_stats = {}
        
        # 채팅방 수 집계
        for stat in user_chat_stats:
            if stat.user_id not in user_stats:
                user_stats[stat.user_id] = {
                    'chat_count': 0,
                    'project_count': 0,
                    'message_count': 0,
                    'input_tokens': 0,
                    'output_tokens': 0,
                    'cache_write_tokens': 0,
                    'cache_hit_tokens': 0,
                    'chat_type_stats': {}
                }
            user_stats[stat.user_id]['chat_count'] = stat.chat_count

        for stat in user_project_stats:
            if stat.user_id not in user_stats:
                user_stats[stat.user_id] = {
                    'chat_count': 0,
                    'project_count': 0,
                    'message_count': 0,
                    'input_tokens': 0,
                    'output_tokens': 0
                }
            user_stats[stat.user_id]['project_count'] = stat.project_count

        # 메시지 수 집계
        for stat in user_message_stats:
            if stat.user_id not in user_stats:
                user_stats[stat.user_id] = {
                    'chat_count': 0,
                    'project_count': 0,
                    'message_count': 0,
                    'input_tokens': 0,
                    'output_tokens': 0
                }
            user_stats[stat.user_id]['message_count'] += stat.message_count

        for stat in user_project_message_stats:
            if stat.user_id not in user_stats:
                user_stats[stat.user_id] = {
                    'chat_count': 0,
                    'project_count': 0,
                    'message_count': 0,
                    'input_tokens': 0,
                    'output_tokens': 0
                }
            user_stats[stat.user_id]['message_count'] += stat.message_count

        # 토큰 사용량 집계
        for stat in user_token_stats:
            if stat.user_id not in user_stats:
                user_stats[stat.user_id] = {
                    'chat_count': 0,
                    'project_count': 0,
                    'message_count': 0,
                    'input_tokens': 0,
                    'output_tokens': 0,
                    'cache_write_tokens': 0,
                    'cache_hit_tokens': 0,
                    'chat_type_stats': {}
                }
            if stat.chat_type:
                if stat.chat_type not in user_stats[stat.user_id]['chat_type_stats']:
                    user_stats[stat.user_id]['chat_type_stats'][stat.chat_type] = {
                        'input_tokens': 0,
                        'output_tokens': 0,
                        'cache_write_tokens': 0,
                        'cache_hit_tokens': 0
                    }
                user_stats[stat.user_id]['chat_type_stats'][stat.chat_type].update({
                    'input_tokens': stat.total_input_tokens or 0,
                    'output_tokens': stat.total_output_tokens or 0,
                    'cache_write_tokens': stat.total_cache_write_tokens or 0,
                    'cache_hit_tokens': stat.total_cache_hit_tokens or 0
                })
            user_stats[stat.user_id].update({
                'input_tokens': (user_stats[stat.user_id]['input_tokens'] + (stat.total_input_tokens or 0)),
                'output_tokens': (user_stats[stat.user_id]['output_tokens'] + (stat.total_output_tokens or 0)),
                'cache_write_tokens': (user_stats[stat.user_id]['cache_write_tokens'] + (stat.total_cache_write_tokens or 0)),
                'cache_hit_tokens': (user_stats[stat.user_id]['cache_hit_tokens'] + (stat.total_cache_hit_tokens or 0))
            })

        # 프로젝트별 통계 쿼리
        project_query = db.query(
            ProjectChat.project_id,
            ProjectChat.user_id,
            func.count(ProjectMessage.id).label('message_count'),
            func.sum(TokenUsage.input_tokens).label('input_tokens'),
            func.sum(TokenUsage.output_tokens).label('output_tokens')
        ).join(
            ProjectMessage, ProjectMessage.room_id == ProjectChat.id
        ).outerjoin(
            TokenUsage, TokenUsage.room_id == ProjectChat.id
        ).group_by(
            ProjectChat.project_id, ProjectChat.user_id
        )
        if user_id:
            project_query = project_query.filter(ProjectChat.user_id == user_id)
        project_stats = project_query.all()

        # 전체 토큰 사용량 계산
        total_input_tokens = sum(stats['input_tokens'] for stats in user_stats.values())
        total_output_tokens = sum(stats['output_tokens'] for stats in user_stats.values())

        result = {
            'total_chats': total_chats,
            'total_messages': total_messages,
            'total_input_tokens': total_input_tokens,
            'total_output_tokens': total_output_tokens,
            'user_stats': [{
                'user_id': str(user_id),
                'email': users.get(str(user_id), {}).get('email', 'Unknown'),
                'name': users.get(str(user_id), {}).get('name', 'Unknown'),
                'chat_count': stats['chat_count'] + stats['project_count'],
                'message_count': stats['message_count'],
                'input_tokens': stats['input_tokens'],
                'output_tokens': stats['output_tokens']
            } for user_id, stats in user_stats.items()],
            'projects': [{
                'project_id': stat.project_id,
                'user_id': str(stat.user_id),
                'user_email': users.get(str(stat.user_id), {}).get('email', 'Unknown'),
                'user_name': users.get(str(stat.user_id), {}).get('name', 'Unknown'),
                'message_count': stat.message_count,
                'input_tokens': stat.input_tokens or 0,
                'output_tokens': stat.output_tokens or 0
            } for stat in project_stats]
        }

        return result
    except Exception as e:
        # 기본값 반환
        return {
            'total_chats': 0,
            'total_messages': 0,
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'user_stats': [],
            'projects': []
        } 