#!/bin/sh

# Python 출력 버퍼링 비활성화
export PYTHONUNBUFFERED=1

# 데이터베이스 연결 대기
echo "Waiting for database..."
max_retries=60  # 30에서 60으로 증가
counter=0

# DATABASE_URL에서 호스트와 포트 추출
DB_HOST=$(echo "$DATABASE_URL" | sed -n 's/.*@\([^:]*\):.*/\1/p')
DB_PORT=$(echo "$DATABASE_URL" | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')
DB_USER=$(echo "$DATABASE_URL" | sed -n 's/.*:\/\/\([^:]*\):.*/\1/p')
DB_PASSWORD=$(echo "$DATABASE_URL" | sed -n 's/.*:\/\/[^:]*:\([^@]*\)@.*/\1/p')

while [ $counter -lt $max_retries ]
do
    PGPASSWORD="$DB_PASSWORD" pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres
    if [ $? -eq 0 ]; then
        echo "Database is ready!"
        break
    fi
    echo "Waiting for database... Attempt $((counter+1))/$max_retries"
    counter=$((counter+1))
    sleep 5  # 2초에서 5초로 증가
done

if [ $counter -eq $max_retries ]; then
    echo "Could not connect to database after $max_retries attempts"
    exit 1
fi

# 데이터베이스 마이그레이션 실행 (재시도 로직 추가)
echo "Running database migrations..."
migration_retries=3
migration_counter=0

while [ $migration_counter -lt $migration_retries ]
do
    alembic upgrade head
    if [ $? -eq 0 ]; then
        echo "Database migration successful!"
        break
    fi
    echo "Migration failed. Retrying... Attempt $((migration_counter+1))/$migration_retries"
    migration_counter=$((migration_counter+1))
    sleep 10
done

if [ $migration_counter -eq $migration_retries ]; then
    echo "Migration failed after $migration_retries attempts. Starting without migration."
fi

# FastAPI 애플리케이션 시작 (워커 수 줄이기)
echo "Starting FastAPI application..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --log-level warning 