from fastapi import APIRouter, Depends
from datetime import datetime
from app.core.utils import KST
from app.core.health_monitor import get_health_status, health_monitor

router = APIRouter()

@router.get("/health", tags=["health"])
def health_check():
    """
    헬스 체크 엔드포인트
    
    API 서버의 상태를 확인하는 엔드포인트입니다.
    """
    return {"status": "healthy", "timestamp": datetime.now(KST).isoformat()}

@router.get("/health/detailed", tags=["health"])
def detailed_health_check():
    """
    상세 헬스 체크 엔드포인트
    
    시스템의 상세한 상태 정보를 반환합니다.
    """
    health_status = get_health_status()
    return health_status

@router.get("/health/current_metrics", tags=["health"])
def current_health_metrics():
    """
    현재 헬스 메트릭 엔드포인트
    
    시스템의 현재 메트릭을 반환합니다.
    """
    return {
        "current_metrics": health_monitor.get_current_metrics(),
        "timestamp": datetime.now(KST).isoformat()
    } 