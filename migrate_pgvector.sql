-- pgvector 인덱스 마이그레이션 스크립트
-- 기존 btree 인덱스 문제 해결

-- 🔧 pgvector 설정 최적화
SET maintenance_work_mem = '512MB';
SET work_mem = '256MB';

-- 🗑️ 기존 문제 인덱스 제거
DROP INDEX IF EXISTS idx_project_embeddings_project_vector;

-- 🚀 pgvector 최적화 인덱스 생성
-- 1. 프로젝트별 빠른 조회를 위한 복합 인덱스
CREATE INDEX IF NOT EXISTS idx_project_embeddings_project_file 
ON project_embeddings (project_id, file_id);

CREATE INDEX IF NOT EXISTS idx_project_embeddings_project_created 
ON project_embeddings (project_id, created_at);

-- 2. 벡터 유사도 검색을 위한 HNSW 인덱스 (고성능)
CREATE INDEX IF NOT EXISTS idx_project_embeddings_vector_hnsw 
ON project_embeddings 
USING hnsw (embedding_vector vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- 3. 백업용 IVFFlat 인덱스 (더 적은 메모리 사용)
CREATE INDEX IF NOT EXISTS idx_project_embeddings_vector_ivf 
ON project_embeddings 
USING ivfflat (embedding_vector vector_cosine_ops)
WITH (lists = 100);

-- 🔍 인덱스 생성 확인
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
\echo '✅ pgvector 인덱스 마이그레이션 완료!'
\echo '🔧 HNSW 인덱스: 고성능 벡터 검색 지원'
\echo '🔧 IVFFlat 인덱스: 메모리 효율적 벡터 검색'
\echo '📊 벡터 검색 성능이 크게 향상됩니다!' 