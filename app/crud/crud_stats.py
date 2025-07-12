from sqlalchemy.orm import Session
from sqlalchemy import func, desc, text
from app.models.stats import TokenUsage
from app.models.project import ProjectChat, ProjectMessage
from app.models.chat_room import ChatRoom
from app.models.chat import ChatMessage
from app.models.user import User
from datetime import datetime, timezone
from typing import Optional, List, Dict
import uuid
import logging

logger = logging.getLogger(__name__)

def create_token_usage(
    db: Session,
    *,
    user_id: Optional[str],
    room_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    timestamp: datetime = datetime.now(timezone.utc),
    chat_type: Optional[str] = None,
    cache_write_tokens: int = 0,
    cache_hit_tokens: int = 0
) -> TokenUsage:
    """토큰 사용량 기록을 생성합니다."""
    # Gemini 모델의 경우 토큰 수는 API에서 제공하는 값 사용
    if model.startswith("gemini-"):
        # 이미 정확한 토큰 수가 계산되어 전달되었으므로 추가 처리 불필요
        pass
    
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
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    user_id: Optional[str] = None
) -> List[TokenUsage]:
    """토큰 사용량 통계를 조회합니다."""
    query = db.query(TokenUsage)
    
    # 날짜 필터링을 선택적으로 적용
    if start_date is not None and end_date is not None:
        query = query.filter(TokenUsage.timestamp.between(start_date, end_date))
    elif start_date is not None:
        query = query.filter(TokenUsage.timestamp >= start_date)
    elif end_date is not None:
        query = query.filter(TokenUsage.timestamp <= end_date)
    # 날짜 필터링이 없으면 모든 데이터 조회
    
    if user_id:
        query = query.filter(TokenUsage.user_id == user_id)
    
    return query.all()

def get_token_usage_history(
    db: Session,
    start: Optional[datetime],
    end: Optional[datetime],
    user_id: Optional[str] = None
) -> List[dict]:
    """토큰 사용 기록을 시간순으로 가져옵니다."""
    
    # 디버깅 로그 추가
    logger.debug(f"get_token_usage_history 호출됨:")
    logger.debug(f"  - start: {start}")
    logger.debug(f"  - end: {end}")
    logger.debug(f"  - user_id: {user_id}")
    
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
    )
    
    # 날짜 필터링을 선택적으로 적용
    if start is not None and end is not None:
        query = query.filter(TokenUsage.timestamp.between(start, end))
        logger.debug(f"날짜 필터링 적용: {start} ~ {end}")
    elif start is not None:
        query = query.filter(TokenUsage.timestamp >= start)
        logger.debug(f"시작 날짜 필터링 적용: >= {start}")
    elif end is not None:
        query = query.filter(TokenUsage.timestamp <= end)
        logger.debug(f"종료 날짜 필터링 적용: <= {end}")
    else:
        logger.debug(f"날짜 필터링 없음 - 전체 데이터 조회")

    if user_id:
        query = query.filter(TokenUsage.user_id == user_id)

    # 시간 역순으로 정렬
    query = query.order_by(desc(TokenUsage.timestamp))

    results = query.all()
    
    logger.debug(f"조회 결과: {len(results)}개 레코드")
    
    # 처음 5개 레코드의 timestamp 출력
    if results:
        logger.debug(f"처음 5개 레코드 timestamp:")
        for i, usage in enumerate(results[:5]):
            logger.debug(f"  {i+1}. {usage.timestamp}")
    
    return [
        {
            "timestamp": usage.timestamp.isoformat() if usage.timestamp else None,
            "model": usage.model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "chat_type": "수행평가" if usage.chat_type == "project_assignment" else 
                        "생기부" if usage.chat_type == "project_record" else "Default",
            "user_email": usage.user_email,
            "user_name": usage.user_name,
            "status": "completed"  # 기본값으로 완료 상태 설정
        }
        for usage in results
    ]

def get_chat_statistics(
    db: Session,
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    user_id: Optional[str] = None
) -> Dict:
    """채팅 사용량 통계를 최적화된 단일 쿼리로 조회합니다."""
    
    try:
        # 날짜 필터 조건 구성
        date_filter = []
        if start_date and end_date:
            date_filter.append("created_at BETWEEN :start_date AND :end_date")
        elif start_date:
            date_filter.append("created_at >= :start_date")
        elif end_date:
            date_filter.append("created_at <= :end_date")
        
        date_condition = f"WHERE {' AND '.join(date_filter)}" if date_filter else ""
        user_condition = "AND user_id = :user_id" if user_id else ""
        
        # 파라미터 준비
        params = {}
        if start_date:
            params['start_date'] = start_date
        if end_date:
            params['end_date'] = end_date
        if user_id:
            params['user_id'] = user_id

        # 단일 통합 쿼리로 모든 통계 조회
        query = text(f"""
        WITH 
        -- 사용자 정보
        users AS (
            SELECT id, email, COALESCE(full_name, SPLIT_PART(email, '@', 1)) as name
            FROM users
        ),
        -- 채팅방 통계
        chat_stats AS (
            SELECT 
                user_id,
                COUNT(*) as chat_count,
                0 as project_count,
                0 as message_count,
                'chat' as type
            FROM chatroom 
            {date_condition.replace('created_at', 'chatroom.created_at')} {user_condition.replace('user_id', 'chatroom.user_id')}
            GROUP BY user_id
            
            UNION ALL
            
            SELECT 
                user_id,
                0 as chat_count,
                COUNT(*) as project_count,
                0 as message_count,
                'project' as type
            FROM projectchat 
            {date_condition.replace('created_at', 'projectchat.created_at')} {user_condition.replace('user_id', 'projectchat.user_id')}
            GROUP BY user_id
        ),
        -- 메시지 통계
        message_stats AS (
            SELECT 
                cr.user_id,
                0 as chat_count,
                0 as project_count,
                COUNT(*) as message_count,
                'chat_message' as type
            FROM chat_messages cm
            JOIN chatroom cr ON cm.room_id = cr.id
            {date_condition.replace('created_at', 'cm.created_at')} {user_condition.replace('user_id', 'cr.user_id')}
            GROUP BY cr.user_id
            
            UNION ALL
            
            SELECT 
                pc.user_id,
                0 as chat_count,
                0 as project_count,
                COUNT(*) as message_count,
                'project_message' as type
            FROM project_messages pm
            JOIN projectchat pc ON pm.room_id = pc.id
            {date_condition.replace('created_at', 'pm.created_at')} {user_condition.replace('user_id', 'pc.user_id')}
            GROUP BY pc.user_id
        ),
        -- 토큰 사용량 통계 (사용자별로 집계)
        token_stats AS (
            SELECT 
                user_id,
                SUM(input_tokens) as total_input_tokens,
                SUM(output_tokens) as total_output_tokens,
                SUM(cache_write_tokens) as total_cache_write_tokens,
                SUM(cache_hit_tokens) as total_cache_hit_tokens
            FROM token_usage 
            {date_condition.replace('created_at', 'timestamp')} {user_condition}
            GROUP BY user_id
        ),
        -- 전체 통계 집계
        aggregated_stats AS (
            SELECT 
                user_id,
                SUM(chat_count) as total_chat_count,
                SUM(project_count) as total_project_count,
                SUM(message_count) as total_message_count
            FROM (
                SELECT * FROM chat_stats
                UNION ALL
                SELECT * FROM message_stats
            ) combined
            GROUP BY user_id
        ),
        -- 사용자별 집계된 데이터
        user_aggregated AS (
            SELECT 
                u.id as user_id,
                u.email,
                u.name,
                COALESCE(a.total_chat_count, 0) as chat_count,
                COALESCE(a.total_project_count, 0) as project_count,
                COALESCE(a.total_message_count, 0) as message_count,
                COALESCE(t.total_input_tokens, 0) as input_tokens,
                COALESCE(t.total_output_tokens, 0) as output_tokens,
                COALESCE(t.total_cache_write_tokens, 0) as cache_write_tokens,
                COALESCE(t.total_cache_hit_tokens, 0) as cache_hit_tokens
            FROM users u
            LEFT JOIN aggregated_stats a ON u.id = a.user_id
            LEFT JOIN token_stats t ON u.id = t.user_id
            {'WHERE u.id = :user_id' if user_id else ''}
        )
        
        SELECT 
            user_id,
            email,
            name,
            chat_count,
            project_count,
            message_count,
            input_tokens,
            output_tokens,
            cache_write_tokens,
            cache_hit_tokens,
            -- 전체 통계 계산을 위한 윈도우 함수
            SUM(chat_count) OVER () as grand_total_chats,
            SUM(project_count) OVER () as grand_total_projects,
            SUM(message_count) OVER () as grand_total_messages,
            SUM(input_tokens) OVER () as grand_total_input_tokens,
            SUM(output_tokens) OVER () as grand_total_output_tokens
        FROM user_aggregated
        ORDER BY (chat_count + project_count) DESC
        """)

        result = db.execute(query, params).fetchall()
        
        if not result:
            return {
                "total_chats": 0,
                "total_projects": 0,
                "total_messages": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "user_stats": []
            }

        # 결과 처리
        first_row = result[0]
        user_stats = []
        
        for row in result:
            if row.chat_count > 0 or row.project_count > 0 or row.message_count > 0:
                user_stats.append({
                    "user_id": row.user_id,
                    "email": row.email,
                    "name": row.name,
                    "chat_count": row.chat_count,
                    "project_count": row.project_count,
                    "message_count": row.message_count,
                    "input_tokens": row.input_tokens,
                    "output_tokens": row.output_tokens,
                    "cache_write_tokens": row.cache_write_tokens,
                    "cache_hit_tokens": row.cache_hit_tokens
                })

        return {
            "total_chats": first_row.grand_total_chats or 0,
            "total_projects": first_row.grand_total_projects or 0,
            "total_messages": first_row.grand_total_messages or 0,
            "total_input_tokens": first_row.grand_total_input_tokens or 0,
            "total_output_tokens": first_row.grand_total_output_tokens or 0,
            "user_stats": user_stats
        }

    except Exception as e:
        logger.error(f"채팅 통계 조회 중 오류 발생: {str(e)}", exc_info=True)
        # 기본값 반환
        return {
            "total_chats": 0,
            "total_projects": 0,
            "total_messages": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "user_stats": []
        } 