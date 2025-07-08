from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.api_v1.api import api_router
from app.db.init_db import init_db
from app.core.error_handlers import setup_error_handlers, ErrorMonitoringMiddleware
from app.core.error_tracking import init_sentry
from app.core.structured_logging import StructuredLogger
import logging
import pytz
from datetime import datetime
import os
import time
from fastapi import Response

# 한국 시간대 설정
os.environ['TZ'] = 'Asia/Seoul'
KST = pytz.timezone('Asia/Seoul')
datetime.now(KST)  # 시스템 전체 시간대 설정

# 로깅 설정
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("alembic").setLevel(logging.WARNING)

# 구조화된 로깅 초기화
structured_logger = StructuredLogger("sungblab_api")
logger = logging.getLogger("sungblab_api")
logger.setLevel(settings.LOG_LEVEL)

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

# 에러 모니터링 미들웨어 추가
app.add_middleware(ErrorMonitoringMiddleware)

# CORS 설정
# 클라우드타입 및 프로덕션 환경을 위한 강화된 CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,  # 24시간 캐시
)

# 추가 CORS 헤더를 위한 미들웨어
@app.middleware("http")
async def add_process_time_header(request, call_next):
    # OPTIONS 요청에 대한 빠른 응답
    if request.method == "OPTIONS":
        response = Response()
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, PATCH, OPTIONS, HEAD"
        response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Max-Age"] = "86400"
        return response
    
    # 일반 요청 처리
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    # 추가 CORS 헤더 보장
    if "Access-Control-Allow-Origin" not in response.headers:
        response.headers["Access-Control-Allow-Origin"] = "*"
    return response

@app.on_event("startup")
async def startup_event():
    print("startup_event", {"message": "Initializing database..."})
    try:
        init_db()
        print("startup_event", {"message": "Database initialization complete"})
    except Exception as e:
        structured_logger.log_error(
            error=e,
            context={"operation": "database_initialization"},
        )
        structured_logger.warning("startup_event", {
            "message": "Application will start without database initialization"
        })

app.include_router(api_router, prefix=settings.API_V1_STR.strip())

@app.get("/", tags=["root"])
def read_root():
    """
    API 루트 엔드포인트
    
    API 서버가 정상적으로 실행 중인지 확인하는 엔드포인트입니다.
    """
    print("Root endpoint accessed")
    return {
        "message": "Welcome to SungbLab AI API",
        "version": settings.VERSION,
        "docs_url": f"{settings.API_V1_STR}/docs",
        "redoc_url": f"{settings.API_V1_STR}/redoc"
    }

@app.get("/health", tags=["health"])
def health_check():
    """
    헬스 체크 엔드포인트
    
    API 서버의 상태를 확인하는 엔드포인트입니다.
    """
    return {"status": "healthy", "timestamp": datetime.now(KST).isoformat()} 