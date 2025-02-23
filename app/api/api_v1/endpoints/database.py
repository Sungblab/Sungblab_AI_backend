from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text, func
from app.api import deps
from app.core.config import settings
from datetime import datetime, timedelta

router = APIRouter()

@router.get("/tables", response_model=List[str])
async def get_tables(
    db: Session = Depends(deps.get_db),
    current_user = Depends(deps.get_current_user)
):
    """
    데이터베이스의 모든 테이블 목록을 반환합니다.
    관리자 권한이 필요합니다.
    """
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
        
    try:
        inspector = inspect(db.bind)
        tables = inspector.get_table_names()
        return tables
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"데이터베이스 조회 중 오류 발생: {str(e)}")

@router.get("/tables/{table_name}", response_model=Dict[str, Any])
async def get_table_data(
    table_name: str, 
    db: Session = Depends(deps.get_db),
    current_user = Depends(deps.get_current_user)
):
    """
    특정 테이블의 구조와 데이터를 반환합니다.
    관리자 권한이 필요합니다.
    """
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
        
    try:
        # 테이블 구조 조회
        inspector = inspect(db.bind)
        if table_name not in inspector.get_table_names():
            raise HTTPException(status_code=404, detail=f"테이블 '{table_name}'을(를) 찾을 수 없습니다.")

        columns = []
        for column in inspector.get_columns(table_name):
            columns.append({
                "name": column["name"],
                "type": str(column["type"]),
                "nullable": column.get("nullable", True),
                "default": str(column.get("default", "")) if column.get("default") else None,
            })

        # 테이블 데이터 조회
        query = text(f"SELECT * FROM {table_name}")
        result = db.execute(query)
        rows = [dict(row._mapping) for row in result]

        return {
            "columns": columns,
            "rows": rows
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"테이블 데이터 조회 중 오류 발생: {str(e)}")

@router.get("/stats/overview", response_model=Dict[str, Any])
async def get_database_stats(
    db: Session = Depends(deps.get_db),
    current_user = Depends(deps.get_current_user)
):
    """
    데이터베이스 전반적인 통계 정보를 반환합니다.
    관리자 권한이 필요합니다.
    """
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
        
    try:
        # 현재 시간과 30일 전 시간
        now = datetime.utcnow()
        thirty_days_ago = now - timedelta(days=30)
        
        stats = {}
        
        # 사용자 통계
        user_stats = db.execute(text("""
            SELECT 
                COUNT(*) as total_users,
                SUM(CASE WHEN created_at >= :thirty_days_ago THEN 1 ELSE 0 END) as new_users,
                SUM(CASE WHEN last_login >= :thirty_days_ago THEN 1 ELSE 0 END) as active_users
            FROM users
        """), {"thirty_days_ago": thirty_days_ago}).fetchone()
        
        stats["user_stats"] = {
            "total": user_stats.total_users,
            "new_last_30_days": user_stats.new_users,
            "active_last_30_days": user_stats.active_users
        }
        
        # 채팅 통계
        chat_stats = db.execute(text("""
            SELECT 
                COUNT(*) as total_chats,
                COUNT(DISTINCT user_id) as unique_users,
                SUM(CASE WHEN created_at >= :thirty_days_ago THEN 1 ELSE 0 END) as recent_chats
            FROM chats
        """), {"thirty_days_ago": thirty_days_ago}).fetchone()
        
        stats["chat_stats"] = {
            "total": chat_stats.total_chats,
            "unique_users": chat_stats.unique_users,
            "last_30_days": chat_stats.recent_chats
        }
        
        # 모델별 사용량 통계
        model_stats = db.execute(text("""
            SELECT 
                model,
                COUNT(*) as usage_count,
                SUM(input_tokens) as total_input_tokens,
                SUM(output_tokens) as total_output_tokens
            FROM token_usage
            WHERE created_at >= :thirty_days_ago
            GROUP BY model
            ORDER BY usage_count DESC
        """), {"thirty_days_ago": thirty_days_ago}).fetchall()
        
        stats["model_stats"] = [
            {
                "model": row.model,
                "usage_count": row.usage_count,
                "input_tokens": row.total_input_tokens,
                "output_tokens": row.total_output_tokens
            }
            for row in model_stats
        ]
        
        # 일별 사용량 추이
        daily_stats = db.execute(text("""
            SELECT 
                DATE(created_at) as date,
                COUNT(*) as chat_count,
                COUNT(DISTINCT user_id) as user_count
            FROM chats
            WHERE created_at >= :thirty_days_ago
            GROUP BY DATE(created_at)
            ORDER BY date
        """), {"thirty_days_ago": thirty_days_ago}).fetchall()
        
        stats["daily_stats"] = [
            {
                "date": row.date.strftime("%Y-%m-%d"),
                "chat_count": row.chat_count,
                "user_count": row.user_count
            }
            for row in daily_stats
        ]
        
        return stats
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"통계 데이터 조회 중 오류 발생: {str(e)}") 