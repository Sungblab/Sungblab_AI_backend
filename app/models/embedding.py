from sqlalchemy import Column, String, Integer, Float, Text, ForeignKey
from sqlalchemy.orm import relationship
from app.db.base_class import Base
from app.core.utils import generate_uuid
from pgvector.sqlalchemy import Vector

class ProjectEmbedding(Base):
    """프로젝트 파일 임베딩 저장 모델 (pgvector 사용)"""
    __tablename__ = "project_embeddings"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    file_id = Column(String, nullable=False)  # Gemini File API ID
    file_name = Column(String, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    
    # 🚀 pgvector Vector 타입 사용 - 올바른 정의
    embedding_vector = Column(Vector(768), nullable=False)  # Gemini text-embedding-004는 768차원
    
    embedding_model = Column(String, nullable=False, default="text-embedding-004")
    task_type = Column(String, nullable=False, default="RETRIEVAL_DOCUMENT")
    chunk_size = Column(Integer, nullable=False)
    similarity_threshold = Column(Float, nullable=True, default=None)
    
    # 관계 설정
    project = relationship("Project", back_populates="embeddings")
    
    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "file_id": self.file_id,
            "file_name": self.file_name,
            "chunk_index": self.chunk_index,
            "chunk_text": self.chunk_text,
            "embedding_model": self.embedding_model,
            "task_type": self.task_type,
            "chunk_size": self.chunk_size,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
    
    def calculate_similarity(self, other_embedding):
        """다른 임베딩과의 코사인 유사도 계산"""
        if not self.embedding_vector or not other_embedding:
            return 0.0
        
        vec1 = self.embedding_vector if isinstance(self.embedding_vector, list) else self.embedding_vector.get('values', [])
        vec2 = other_embedding if isinstance(other_embedding, list) else other_embedding.get('values', [])
        
        if len(vec1) != len(vec2) or len(vec1) == 0:
            return 0.0
        
        # 코사인 유사도 계산
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm_a = (sum(a * a for a in vec1)) ** 0.5
        norm_b = (sum(b * b for b in vec2)) ** 0.5
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return dot_product / (norm_a * norm_b) 