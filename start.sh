#!/bin/sh

# Python 출력 버퍼링 비활성화
export PYTHONUNBUFFERED=1

# 데이터베이스 연결 대기
echo "Waiting for database..."
max_retries=30
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
    sleep 2
done

if [ $counter -eq $max_retries ]; then
    echo "Could not connect to database after $max_retries attempts"
    exit 1
fi

# 데이터베이스 마이그레이션 실행
echo "Running database migrations..."
alembic upgrade head

# FastAPI 애플리케이션 시작
echo "Starting FastAPI application..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --log-level info 