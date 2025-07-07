from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, func, text
from app.models.embedding import ProjectEmbedding
from pydantic import BaseModel
from datetime import datetime
import numpy as np


class ProjectEmbeddingCreate(BaseModel):
    project_id: str
    file_id: str
    file_name: str
    chunk_index: int
    chunk_text: str
    embedding_vector: List[float]
    embedding_model: str = "text-embedding-004"
    task_type: str = "RETRIEVAL_DOCUMENT"
    chunk_size: int
    similarity_threshold: float = 0.7


class ProjectEmbeddingUpdate(BaseModel):
    file_name: Optional[str] = None
    chunk_text: Optional[str] = None
    embedding_vector: Optional[List[float]] = None
    similarity_threshold: Optional[float] = None


def create(db: Session, *, obj_in: ProjectEmbeddingCreate) -> ProjectEmbedding:
    """임베딩 생성 (pgvector Vector 타입)"""
    # 🔥 Vector 타입으로 직접 전달 (정규화하지 않음)
    embedding_vector = obj_in.embedding_vector
    
    db_obj = ProjectEmbedding(
        project_id=obj_in.project_id,
        file_id=obj_in.file_id,
        file_name=obj_in.file_name,
        chunk_index=obj_in.chunk_index,
        chunk_text=obj_in.chunk_text,
        embedding_vector=embedding_vector,  # List[float] -> Vector(768) 자동 변환
        embedding_model=obj_in.embedding_model,
        task_type=obj_in.task_type,
        chunk_size=obj_in.chunk_size,
        similarity_threshold=obj_in.similarity_threshold
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def create_embedding(
    db: Session,
    *,
    project_id: str,
    file_id: str,
    file_name: str,
    chunk_index: int,
    chunk_text: str,
    embedding_vector: List[float],
    embedding_model: str = "text-embedding-004",
    task_type: str = "RETRIEVAL_DOCUMENT",
    chunk_size: int,
    similarity_threshold: float = 0.7
) -> ProjectEmbedding:
    """임베딩 생성"""
    embedding_data = ProjectEmbeddingCreate(
        project_id=project_id,
        file_id=file_id,
        file_name=file_name,
        chunk_index=chunk_index,
        chunk_text=chunk_text,
        embedding_vector=embedding_vector,
        embedding_model=embedding_model,
        task_type=task_type,
        chunk_size=chunk_size,
        similarity_threshold=similarity_threshold
    )
    return create(db, obj_in=embedding_data)


def get_by_project(db: Session, project_id: str) -> List[ProjectEmbedding]:
    """프로젝트별 모든 임베딩 조회"""
    return db.query(ProjectEmbedding).filter(
        ProjectEmbedding.project_id == project_id
    ).order_by(ProjectEmbedding.file_name, ProjectEmbedding.chunk_index).all()


def get_by_file(db: Session, project_id: str, file_id: str) -> List[ProjectEmbedding]:
    """특정 파일의 모든 임베딩 조회"""
    return db.query(ProjectEmbedding).filter(
        and_(
            ProjectEmbedding.project_id == project_id,
            ProjectEmbedding.file_id == file_id
        )
    ).order_by(ProjectEmbedding.chunk_index).all()


def delete_by_file(db: Session, project_id: str, file_id: str) -> int:
    """파일별 임베딩 삭제"""
    deleted = db.query(ProjectEmbedding).filter(
        and_(
            ProjectEmbedding.project_id == project_id,
            ProjectEmbedding.file_id == file_id
        )
    ).delete()
    db.commit()
    return deleted


def delete_by_project(db: Session, project_id: str) -> int:
    """프로젝트별 모든 임베딩 삭제"""
    deleted = db.query(ProjectEmbedding).filter(
        ProjectEmbedding.project_id == project_id
    ).delete()
    db.commit()
    return deleted


def get_embedding_stats(db: Session, project_id: str) -> Dict[str, Any]:
    """임베딩 통계 조회"""
    stats = db.query(
        func.count(ProjectEmbedding.id).label('total_embeddings'),
        func.count(func.distinct(ProjectEmbedding.file_id)).label('unique_files'),
        func.avg(ProjectEmbedding.chunk_size).label('avg_chunk_size'),
        func.sum(ProjectEmbedding.chunk_size).label('total_chars')
    ).filter(
        ProjectEmbedding.project_id == project_id
    ).first()
    
    return {
        'total_embeddings': stats.total_embeddings or 0,
        'unique_files': stats.unique_files or 0,
        'avg_chunk_size': float(stats.avg_chunk_size) if stats.avg_chunk_size else 0,
        'total_chars': stats.total_chars or 0
    }


# 🔍 pgvector 네이티브 벡터 검색 (고성능)
def search_similar(
    db: Session,
    project_id: str,
    query_embedding: List[float],
    top_k: int = 5,
    threshold: float = 0.4
) -> List[Dict[str, Any]]:
    """
    pgvector 네이티브 벡터 유사도 검색
    - 코사인 유사도 계산 (pgvector 최적화)
    - HNSW 인덱스 활용으로 고성능 검색
    """
    try:
        print(f"🔍 지식베이스 검색 시작 (pgvector 네이티브): top_k={top_k}, threshold={threshold}")
        print(f"   프로젝트 ID: {project_id}")
        
        # pgvector 네이티브 코사인 유사도 검색
        results = db.query(
            ProjectEmbedding.id,
            ProjectEmbedding.project_id,
            ProjectEmbedding.file_id,
            ProjectEmbedding.file_name,
            ProjectEmbedding.chunk_index,
            ProjectEmbedding.chunk_text,
            ProjectEmbedding.embedding_model,
            ProjectEmbedding.task_type,
            ProjectEmbedding.chunk_size,
            ProjectEmbedding.created_at,
            # pgvector 코사인 유사도 연산 (1 - 코사인 거리)
            (1 - ProjectEmbedding.embedding_vector.cosine_distance(query_embedding)).label('similarity')
        ).filter(
            ProjectEmbedding.project_id == project_id
        ).filter(
            # 임계값 필터링 (코사인 거리 기준)
            ProjectEmbedding.embedding_vector.cosine_distance(query_embedding) < (1 - threshold)
        ).order_by(
            ProjectEmbedding.embedding_vector.cosine_distance(query_embedding)
        ).limit(top_k).all()
        
        # 결과 변환
        search_results = []
        for result in results:
            search_results.append({
                "id": result.id,
                "project_id": result.project_id,
                "file_id": result.file_id,
                "file_name": result.file_name,
                "chunk_index": result.chunk_index,
                "content": result.chunk_text,
                "similarity": float(result.similarity),
                "embedding_model": result.embedding_model,
                "task_type": result.task_type,
                "chunk_size": result.chunk_size,
                "created_at": result.created_at.isoformat() if result.created_at else None
            })
        
        print(f"✅ pgvector 네이티브 검색 완료: {len(search_results)}개 결과")
        for i, result in enumerate(search_results):
            print(f"   [{i+1}] 유사도: {result['similarity']:.3f}, 파일: {result['file_name']}")
        
        return search_results
        
    except Exception as e:
        print(f"❌ pgvector 네이티브 검색 실패: {e}")
        print("   폴백 검색 모드로 전환...")
        return _fallback_search_similar(db, project_id, query_embedding, top_k, threshold)


def _normalize_embedding_vector(embedding_vector: List[float]) -> List[float]:
    """임베딩 벡터 정규화"""
    try:
        # numpy 배열로 변환
        vec = np.array(embedding_vector, dtype=np.float32)
        
        # 정규화 (L2 norm)
        norm = np.linalg.norm(vec)
        if norm == 0:
            return vec.tolist()
        
        normalized = vec / norm
        return normalized.tolist()
        
    except Exception as e:
        print(f"벡터 정규화 오류: {e}")
        return embedding_vector


def _fallback_search_similar(
    db: Session,
    project_id: str,
    query_embedding: List[float],
    top_k: int = 5,
    threshold: float = 0.7
) -> List[Dict[str, Any]]:
    """폴백: 기존 방식의 유사도 검색"""
    print("⚠️  폴백 검색 모드 사용 (성능 저하)")
    
    embeddings = get_by_project(db, project_id)
    
    if not embeddings:
        return []
    
    # 유사도 계산
    similarities = []
    for embedding in embeddings:
        similarity = _calculate_cosine_similarity_fallback(
            query_embedding, 
            embedding.embedding_vector
        )
        
        if similarity >= threshold:
            similarities.append({
                "id": embedding.id,
                "project_id": embedding.project_id,
                "file_id": embedding.file_id,
                "file_name": embedding.file_name,
                "chunk_index": embedding.chunk_index,
                "content": embedding.chunk_text,
                "similarity": similarity,
                "embedding_model": embedding.embedding_model,
                "task_type": embedding.task_type,
                "chunk_size": embedding.chunk_size,
                "created_at": embedding.created_at.isoformat() if embedding.created_at else None
            })
    
    # 유사도 순으로 정렬하고 상위 k개 반환
    similarities.sort(key=lambda x: x["similarity"], reverse=True)
    return similarities[:top_k]


def _calculate_cosine_similarity_fallback(vec1: List[float], vec2: List[float]) -> float:
    """폴백: 코사인 유사도 계산"""
    try:
        # numpy 사용
        v1 = np.array(vec1, dtype=np.float32)
        v2 = np.array(vec2, dtype=np.float32)
        
        # 코사인 유사도 계산
        dot_product = np.dot(v1, v2)
        norm_v1 = np.linalg.norm(v1)
        norm_v2 = np.linalg.norm(v2)
        
        if norm_v1 == 0 or norm_v2 == 0:
            return 0.0
        
        similarity = dot_product / (norm_v1 * norm_v2)
        return float(similarity)
        
    except Exception as e:
        print(f"유사도 계산 오류: {e}")
        return 0.0


def batch_create_embeddings(
    db: Session,
    embeddings_data: List[ProjectEmbeddingCreate]
) -> List[ProjectEmbedding]:
    """배치 임베딩 생성 (pgvector Vector 타입 최적화)"""
    embeddings = []
    
    try:
        # 배치 처리로 성능 향상
        for data in embeddings_data:
            # 🔥 중요: Vector 타입으로 직접 전달 (정규화하지 않음)
            # pgvector가 자동으로 처리하도록 List[float] 그대로 전달
            embedding_vector = data.embedding_vector
            
            embedding = ProjectEmbedding(
                project_id=data.project_id,
                file_id=data.file_id,
                file_name=data.file_name,
                chunk_index=data.chunk_index,
                chunk_text=data.chunk_text,
                embedding_vector=embedding_vector,  # List[float] -> Vector(768) 자동 변환
                embedding_model=data.embedding_model,
                task_type=data.task_type,
                chunk_size=data.chunk_size,
                similarity_threshold=data.similarity_threshold
            )
            embeddings.append(embedding)
        
        # 배치 insert
        db.add_all(embeddings)
        db.commit()
        
        # refresh 모든 객체
        for embedding in embeddings:
            db.refresh(embedding)
        
        print(f"✅ 배치 임베딩 생성 완료: {len(embeddings)}개")
        return embeddings
        
    except Exception as e:
        print(f"❌ 배치 임베딩 생성 실패: {e}")
        db.rollback()
        return [] 