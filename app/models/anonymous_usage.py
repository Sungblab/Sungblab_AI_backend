from sqlalchemy import Column, Integer, String, DateTime, func, Index
from app.db.base_class import Base


class AnonymousUsage(Base):
    """익명 사용자 채팅 사용량 추적 모델"""
    __tablename__ = "anonymous_usage"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(255), nullable=False, index=True)
    ip_address = Column(String(45), nullable=False, index=True)
    usage_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # 복합 인덱스 (세션 ID + IP 주소)
    __table_args__ = (
        Index('ix_anonymous_usage_session_ip', 'session_id', 'ip_address', unique=True),
    )
    
    def __repr__(self):
        return f"<AnonymousUsage(id={self.id}, session_id={self.session_id}, ip_address={self.ip_address}, usage_count={self.usage_count})>" 