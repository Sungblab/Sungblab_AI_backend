from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.chat_room import ChatRoom, ChatMessage
from app.schemas.chat import ChatRoomCreate, ChatMessageCreate
from datetime import datetime
from typing import List
from fastapi import HTTPException

def find_smallest_available_id(db: Session) -> int:
    # 현재 사용 중인 모든 ID를 가져옴
    used_ids = set(id_tuple[0] for id_tuple in db.query(ChatRoom.id).all())
    
    # 1부터 시작해서 사용되지 않은 가장 작은 ID를 찾음
    smallest_id = 1
    while smallest_id in used_ids:
        smallest_id += 1
    
    return smallest_id

def create_chat_room(db: Session, room: ChatRoomCreate, user_id: str) -> ChatRoom:
    try:
        # ChatRoomCreate 스키마를 ChatRoom 모델로 변환
        db_room = ChatRoom(
            name=room.name,
            user_id=user_id,  # 사용자 ID 추가
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(db_room)
        db.flush()
        db.refresh(db_room)
        db.commit()
        return db_room
    except Exception as e:
        db.rollback()
        raise e

def get_chat_rooms(db: Session, user_id: str) -> list[ChatRoom]:
    return db.query(ChatRoom).filter(
        ChatRoom.user_id == str(user_id)
    ).order_by(ChatRoom.created_at.desc()).all()

def delete_chat_room(db: Session, room_id: str, user_id: str) -> bool:
    try:
        # 채팅방 조회
        room = db.query(ChatRoom).filter(
            ChatRoom.id == room_id,
            ChatRoom.user_id == str(user_id)
        ).first()
        
        if room:
            # 먼저 관련된 메시지들을 삭제
            db.query(ChatMessage).filter(ChatMessage.room_id == room_id).delete()
            
            # 그 다음 채팅방 삭제
            db.delete(room)
            db.commit()
            return True
        return False
    except Exception as e:
        db.rollback()
        print(f"채팅방 삭제 중 오류 발생: {str(e)}")
        raise

def create_message(db: Session, room_id: str, message: ChatMessageCreate) -> ChatMessage:
    db_message = ChatMessage(
        room_id=room_id,
        content=message.content,
        role=message.role,
        file=message.file.dict() if message.file else None
    )
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

def get_room_messages(db: Session, room_id: str, user_id: str) -> List[ChatMessage]:
    # 먼저 채팅방이 해당 사용자의 것인지 확인
    room = db.query(ChatRoom).filter(
        ChatRoom.id == room_id,
        ChatRoom.user_id == user_id
    ).first()
    
    if not room:
        raise HTTPException(status_code=404, detail="Chat room not found")
    
    return db.query(ChatMessage).filter(
        ChatMessage.room_id == room_id
    ).order_by(ChatMessage.created_at.asc()).all()

def update_chat_room(db: Session, room_id: str, room: ChatRoomCreate, user_id: str) -> ChatRoom:
    db_room = db.query(ChatRoom).filter(
        ChatRoom.id == room_id,
        ChatRoom.user_id == user_id
    ).first()
    if not db_room:
        raise HTTPException(status_code=404, detail="Chat room not found")
    
    db_room.name = room.name
    db_room.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_room)
    return db_room

def get_chat_room(db: Session, room_id: str, user_id: str) -> ChatRoom:
    return db.query(ChatRoom).filter(
        ChatRoom.id == room_id,
        ChatRoom.user_id == str(user_id)
    ).first() 

def get_message_count(db: Session, room_id: str) -> int:
    """특정 채팅방의 메시지 수를 반환합니다."""
    return db.query(func.count(ChatMessage.id)).filter(
        ChatMessage.room_id == room_id
    ).scalar() or 0