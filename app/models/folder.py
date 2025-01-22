from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base

class Folder(Base):
    name = Column(String, nullable=False)
    parent_id = Column(Integer, ForeignKey("folder.id"))
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    
    # Relationships
    parent = relationship("Folder", remote_side=[id], backref="children")
    projects = relationship("Project", back_populates="folder")
    user = relationship("User", back_populates="folders") 