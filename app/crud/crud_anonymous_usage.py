from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from app.models.anonymous_usage import AnonymousUsage
from datetime import datetime, timedelta, timezone


class CRUDAnonymousUsage:
    def get_or_create_usage(
        self, 
        db: Session, 
        session_id: str, 
        ip_address: str
    ) -> AnonymousUsage:
        """
        세션 ID와 IP 주소로 사용량 기록을 찾거나 새로 생성
        """
        # 기존 기록 조회
        usage = db.query(AnonymousUsage).filter(
            and_(
                AnonymousUsage.session_id == session_id,
                AnonymousUsage.ip_address == ip_address
            )
        ).first()
        
        if usage:
            return usage
        
        # 새로운 기록 생성
        usage = AnonymousUsage(
            session_id=session_id,
            ip_address=ip_address,
            usage_count=0
        )
        db.add(usage)
        db.commit()
        db.refresh(usage)
        return usage
    
    def increment_usage(
        self, 
        db: Session, 
        session_id: str, 
        ip_address: str
    ) -> AnonymousUsage:
        """
        사용량을 1 증가시킴 (원자적 업데이트)
        """
        # 데이터베이스 레벨에서 원자적으로 업데이트
        db.query(AnonymousUsage).filter(
            and_(
                AnonymousUsage.session_id == session_id,
                AnonymousUsage.ip_address == ip_address
            )
        ).update(
            {AnonymousUsage.usage_count: AnonymousUsage.usage_count + 1,
             AnonymousUsage.updated_at: datetime.now(timezone.utc)},
            synchronize_session=False
        )
        db.commit()
        
        # 업데이트된 객체를 다시 로드
        usage = db.query(AnonymousUsage).filter(
            and_(
                AnonymousUsage.session_id == session_id,
                AnonymousUsage.ip_address == ip_address
            )
        ).first()
        
        if not usage:
            # 레코드가 없으면 새로 생성 (경쟁 조건으로 인해 업데이트 실패 시)
            usage = AnonymousUsage(
                session_id=session_id,
                ip_address=ip_address,
                usage_count=1
            )
            db.add(usage)
            db.commit()
            db.refresh(usage)
        
        return usage
    
    def check_usage_limit(
        self, 
        db: Session, 
        session_id: str, 
        ip_address: str, 
        limit: int = 5
    ) -> bool:
        """
        사용량 한도 확인 (True: 한도 초과, False: 사용 가능)
        """
        usage = self.get_or_create_usage(db, session_id, ip_address)
        return usage.usage_count >= limit
    
    def get_usage_count(
        self, 
        db: Session, 
        session_id: str, 
        ip_address: str
    ) -> int:
        """
        현재 사용량 조회
        """
        usage = self.get_or_create_usage(db, session_id, ip_address)
        return usage.usage_count
    
    def reset_usage_by_ip(
        self, 
        db: Session, 
        ip_address: str
    ) -> int:
        """
        특정 IP의 모든 사용량 리셋 (관리자 기능)
        """
        count = db.query(AnonymousUsage).filter(
            AnonymousUsage.ip_address == ip_address
        ).update({
            AnonymousUsage.usage_count: 0,
            AnonymousUsage.updated_at: datetime.now(timezone.utc)
        })
        db.commit()
        return count
    
    def cleanup_old_records(
        self, 
        db: Session, 
        days_old: int = 30
    ) -> int:
        """
        오래된 기록 정리 (30일 이상 된 기록 삭제)
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)
        count = db.query(AnonymousUsage).filter(
            AnonymousUsage.created_at < cutoff_date
        ).delete()
        db.commit()
        return count
    
    def get_daily_stats(
        self, 
        db: Session, 
        date: Optional[datetime] = None
    ) -> dict:
        """
        일별 익명 사용자 통계 조회
        """
        if date is None:
            target_date = datetime.now(timezone.utc).date()
        else:
            target_date = date.date() if isinstance(date, datetime) else date
        
        # 당일 생성된 기록들
        start_date = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
        end_date = start_date + timedelta(days=1)
        
        records = db.query(AnonymousUsage).filter(
            and_(
                AnonymousUsage.created_at >= start_date,
                AnonymousUsage.created_at < end_date
            )
        ).all()
        
        total_sessions = len(records)
        total_usage = sum(record.usage_count for record in records)
        unique_ips = len(set(record.ip_address for record in records))
        
        return {
            "date": target_date.isoformat(),
            "total_sessions": total_sessions,
            "total_usage": total_usage,
            "unique_ips": unique_ips,
            "average_usage_per_session": total_usage / total_sessions if total_sessions > 0 else 0
        }


# 싱글톤 인스턴스 생성
crud_anonymous_usage = CRUDAnonymousUsage() 