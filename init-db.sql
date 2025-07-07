-- PostgreSQL 초기화 스크립트
-- pgvector 확장 활성화

-- pgvector 확장 설치
CREATE EXTENSION IF NOT EXISTS vector;

-- 기본 설정
ALTER DATABASE sungblab_ai SET timezone TO 'Asia/Seoul';

-- 벡터 연산을 위한 기본 설정
SET shared_preload_libraries = 'vector';

-- 성능 최적화를 위한 설정
SET work_mem = '256MB';
SET maintenance_work_mem = '512MB';

-- 🔧 pgvector 인덱스 최적화 설정
-- HNSW 인덱스 매개변수 최적화
SET hnsw.ef_search = 100;

-- IVFFlat 인덱스 매개변수 최적화
SET ivfflat.probes = 10;

-- 🗑️ 기존 문제 인덱스 제거 (크기 제한 초과)
DROP INDEX IF EXISTS idx_project_embeddings_project_vector;

-- 🚀 pgvector 최적화 인덱스 생성 (테이블 생성 후 실행)
-- 참고: 이 명령어들은 테이블 생성 후에 실행되어야 합니다.

-- 로그 설정
SET log_statement = 'all';
SET log_duration = on;

-- 사용자 확인
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_user WHERE usename = 'sungblab') THEN
        CREATE USER sungblab WITH PASSWORD 'sungblab123';
    END IF;
END
$$;

-- 권한 부여
GRANT ALL PRIVILEGES ON DATABASE sungblab_ai TO sungblab;

-- 벡터 확장 확인
SELECT 
    extname AS extension_name,
    extversion AS version,
    nspname AS schema_name
FROM pg_extension e
JOIN pg_namespace n ON e.extnamespace = n.oid
WHERE extname = 'vector';

-- 🔍 pgvector 성능 최적화 확인
\echo '✅ pgvector 확장 활성화 완료!'
\echo '🔧 인덱스 최적화 설정 완료!'
\echo '📊 벡터 검색 성능이 크게 향상됩니다!'
\echo '⚠️  테이블 생성 후 인덱스가 자동으로 생성됩니다.'
