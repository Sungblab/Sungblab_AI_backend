from fastapi import APIRouter
from app.api.api_v1.endpoints import auth, users, chat, projects, admin
from app.routers import health

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(health.router, tags=["health"])
 