from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.api_v1.api import api_router
from app.db.init_db import init_db
import logging
import pytz
from datetime import datetime
import os

# 한국 시간대 설정
os.environ['TZ'] = 'Asia/Seoul'
KST = pytz.timezone('Asia/Seoul')
datetime.now(KST)  # 시스템 전체 시간대 설정

# 로깅 설정
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("alembic").setLevel(logging.WARNING)

logger = logging.getLogger("sungblab_api")
logger.setLevel(settings.LOG_LEVEL)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    debug=settings.DEBUG
)

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
    logger.info("Initializing database...")
    try:
        init_db()
        logger.info("Database initialization complete")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        logger.warning("Application will start without database initialization")

app.include_router(api_router, prefix=settings.API_V1_STR.strip())

@app.get("/")
def read_root():
    logger.info("Root endpoint accessed")
    return {"message": "Welcome to SungbLab AI API"} 