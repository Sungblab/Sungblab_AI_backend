from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.api_v1.api import api_router
from app.db.init_db import init_db
from app.core.error_handlers import setup_error_handlers, ErrorMonitoringMiddleware
from app.core.error_tracking import init_sentry
from app.core.logging_config import init_logging
from app.core.scheduled_tasks import scheduled_tasks
from app.core.health_monitor import health_monitor
from app.core.memory_manager import memory_manager
import logging
import pytz
from datetime import datetime
import os

# 한국 시간대 설정
os.environ['TZ'] = 'Asia/Seoul'
KST = pytz.timezone('Asia/Seoul')
datetime.now(KST)  # 시스템 전체 시간대 설정

logger = logging.getLogger(__name__)

# OpenAPI 메타데이터 설정
description = """
## SungbLab AI API

이 API는 SungbLab AI 서비스를 위한 백엔드 API입니다.

### 주요 기능

* **인증 (Authentication)**: 사용자 회원가입, 로그인, 소셜 로그인 지원
* **사용자 관리 (Users)**: 사용자 정보 조회 및 관리
* **채팅 (Chat)**: AI 모델과의 대화 인터페이스
* **프로젝트 관리 (Projects)**: 프로젝트 생성, 수정, 삭제
* **관리자 (Admin)**: 시스템 관리 및 통계

### 인증 방식

API는 Bearer 토큰 인증을 사용합니다. 로그인 후 받은 토큰을 Authorization 헤더에 포함하여 요청하세요.

```
Authorization: Bearer <your-token>
```

### 응답 형식

모든 API 응답은 JSON 형식으로 제공됩니다.

### 오류 처리

API는 표준 HTTP 상태 코드를 사용하여 오류를 표시합니다:

* **200**: 성공
* **400**: 잘못된 요청
* **401**: 인증 필요
* **403**: 권한 없음
* **404**: 리소스 없음
* **500**: 서버 오류
"""

tags_metadata = [
    {
        "name": "auth",
        "description": "사용자 인증 관련 API입니다. 회원가입, 로그인, 소셜 로그인 등을 지원합니다."
    },
    {
        "name": "users",
        "description": "사용자 정보 관리 API입니다. 사용자 프로필 조회, 수정 등을 지원합니다."
    },
    {
        "name": "chat",
        "description": "AI 채팅 관련 API입니다. 다양한 AI 모델과의 대화를 지원합니다."
    },
    {
        "name": "projects",
        "description": "프로젝트 관리 API입니다. 프로젝트 생성, 수정, 삭제, 조회를 지원합니다."
    },
    {
        "name": "admin",
        "description": "관리자 전용 API입니다. 시스템 관리 및 통계 조회를 지원합니다."
    }
]

app = FastAPI(
    title=settings.PROJECT_NAME,
    description=description,
    version=settings.VERSION,
    terms_of_service="https://sungblab.com/terms",
    contact={
        "name": "SungbLab Support",
        "url": "https://sungblab.com/contact",
        "email": "support@sungblab.com"
    },
    license_info={
        "name": "MIT License",
        "url": "https://opensource.org/licenses/MIT"
    },
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    openapi_tags=tags_metadata,
    debug=settings.DEBUG
)

# 에러 추적 초기화 (Sentry)
init_sentry()

# 글로벌 에러 핸들러 설정
setup_error_handlers(app)

# 성능 모니터링 미들웨어 추가 (선택적)
if settings.ENABLE_PERFORMANCE_MONITORING:
    from app.middleware.performance import PerformanceMonitoringMiddleware
    app.add_middleware(PerformanceMonitoringMiddleware, slow_request_threshold=2.0)

# 에러 모니터링 미들웨어 추가
app.add_middleware(ErrorMonitoringMiddleware)

# CORS 설정
origins = [
    "http://localhost:3000",
    "https://sungblab.com",
    "https://www.sungblab.com",
    "https://sungblab-ai-frontend.vercel.app"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    # 로깅 시스템 초기화
    init_logging()
    
    try:
        init_db()
        
        # 데이터베이스 최적화 적용
        try:
            from app.core.db_optimization import db_optimizer
            db_optimizer.optimize_database_settings()
            logger.info("✅ 데이터베이스 최적화 설정 완료")
        except Exception as e:
            logger.warning(f"⚠️  데이터베이스 최적화 실패: {e}")
        
        # 메모리 관리자 시작 (선택적)
        if settings.ENABLE_MEMORY_MANAGER:
            memory_manager.start()
        
        # 헬스 모니터 시작 (선택적)
        if settings.ENABLE_HEALTH_MONITOR:
            health_monitor.start()
        
        # 데이터베이스 연결 상태 모니터링 시작
        try:
            from app.db.retry_session import monitor_connection_health
            import asyncio
            asyncio.create_task(monitor_connection_health())
            logger.info("✅ 데이터베이스 연결 모니터링 시작")
        except Exception as e:
            logger.warning(f"⚠️  데이터베이스 모니터링 시작 실패: {e}")
        
        # 스케줄링 태스크 시작 (선택적)
        if settings.ENABLE_SCHEDULED_TASKS:
            scheduled_tasks.start()
            # 시작 시 로그 정리 실행
            scheduled_tasks.force_cleanup_logs()
        
        logger.info("SungbLab API server started successfully (optimized mode)")
        
    except Exception as e:
        logger.critical(f"Warning: Application started with limited functionality - {e}", exc_info=True)

@app.on_event("shutdown")
async def shutdown_event():
    """애플리케이션 종료 시 정리 작업"""
    
    
    # 헬스 모니터 중지 (선택적)
    if settings.ENABLE_HEALTH_MONITOR:
        health_monitor.stop()
    
    # 스케줄링 태스크 중지 (선택적)
    if settings.ENABLE_SCHEDULED_TASKS:
        scheduled_tasks.stop()
    
    logger.info("SungbLab API server stopped")

app.include_router(api_router, prefix=settings.API_V1_STR.strip())

@app.get("/", tags=["root"])
def read_root():
    """
    API 루트 엔드포인트
    
    API 서버가 정상적으로 실행 중인지 확인하는 엔드포인트입니다.
    """
    logger.info("Root endpoint accessed")
    return {
        "message": "Welcome to SungbLab AI API",
        "version": settings.VERSION,
        "docs_url": f"{settings.API_V1_STR}/docs",
        "redoc_url": f"{settings.API_V1_STR}/redoc"
    }

 