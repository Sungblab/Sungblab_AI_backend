from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.api_v1.api import api_router
from app.db.init_db import init_db
import logging

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
    "http://localhost:8000",
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
    init_db()
    logger.info("Database initialization complete")

app.include_router(api_router, prefix=settings.API_V1_STR.strip())

@app.get("/")
def read_root():
    logger.info("Root endpoint accessed")
    return {"message": "Welcome to SungbLab AI API"} 