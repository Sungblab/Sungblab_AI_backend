from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from app.db.base_class import Base
from app.core.utils import generate_uuid

class Folder(Base):
    __tablename__ = "folders"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    parent_id = Column(String, ForeignKey("folders.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Relationships
    parent = relationship("Folder", remote_side=[id], backref="children")
    # projects = relationship("Project", back_populates="folder")  # TODO: Enable when folder_id is added to projects table
    user = relationship("User", back_populates="folders") 