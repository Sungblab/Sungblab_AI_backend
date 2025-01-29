from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, DateTime
from datetime import datetime
from app.core.utils import get_kr_time

class Base(DeclarativeBase):
    created_at = Column(DateTime, default=get_kr_time)
    updated_at = Column(DateTime, default=get_kr_time, onupdate=get_kr_time)
    pass 