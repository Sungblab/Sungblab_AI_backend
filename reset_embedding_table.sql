-- 임베딩 테이블 완전 초기화 스크립트
-- 기존 잘못된 인덱스와 테이블을 제거하고 올바른 구조로 재생성

-- 🔧 pgvector 설정 최적화
SET maintenance_work_mem = '512MB';
SET work_mem = '256MB';

-- 🗑️ 기존 테이블과 모든 관련 인덱스 완전 제거
DROP TABLE IF EXISTS project_embeddings CASCADE;

-- 🚀 올바른 pgvector 구조로 테이블 재생성
CREATE TABLE project_embeddings (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    project_id VARCHAR NOT NULL,
    file_id VARCHAR NOT NULL,
    file_name VARCHAR NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    -- 🔥 중요: pgvector Vector 타입 사용 (JSON이 아님)
    embedding_vector vector(768) NOT NULL,
    embedding_model VARCHAR NOT NULL DEFAULT 'text-embedding-004',
    task_type VARCHAR NOT NULL DEFAULT 'RETRIEVAL_DOCUMENT',
    chunk_size INTEGER NOT NULL,
    similarity_threshold FLOAT DEFAULT 0.7,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 🔗 외래키 제약조건 추가 (projects 테이블이 존재하는 경우)
-- ALTER TABLE project_embeddings 
-- ADD CONSTRAINT fk_project_embeddings_project_id 
-- FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;

-- 🚀 pgvector 최적화 인덱스 생성
-- 1. 프로젝트별 빠른 조회를 위한 복합 인덱스
CREATE INDEX idx_project_embeddings_project_file 
ON project_embeddings (project_id, file_id);

CREATE INDEX idx_project_embeddings_project_created 
ON project_embeddings (project_id, created_at);

-- 2. 벡터 유사도 검색을 위한 HNSW 인덱스 (고성능)
CREATE INDEX idx_project_embeddings_vector_hnsw 
ON project_embeddings 
USING hnsw (embedding_vector vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- 3. 백업용 IVFFlat 인덱스 (더 적은 메모리 사용)
CREATE INDEX idx_project_embeddings_vector_ivf 
ON project_embeddings 
USING ivfflat (embedding_vector vector_cosine_ops)
WITH (lists = 100);

-- 🔍 생성된 인덱스 확인
SELECT 
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes 
WHERE tablename = 'project_embeddings'
ORDER BY indexname;

-- 📊 테이블 통계 업데이트
ANALYZE project_embeddings;

-- 성공 메시지
\echo '✅ 임베딩 테이블 완전 초기화 완료!'
\echo '🔧 HNSW 인덱스: 고성능 벡터 검색 지원'
\echo '🔧 IVFFlat 인덱스: 메모리 효율적 벡터 검색'
\echo '📊 이제 pgvector Vector 타입을 올바르게 사용합니다!' 