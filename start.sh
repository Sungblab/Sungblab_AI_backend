#!/bin/sh

# 데이터베이스 연결 대기
echo "Waiting for database..."
max_retries=30
counter=0

while [ $counter -lt $max_retries ]
do
    PGPASSWORD=sungbin123 pg_isready -h postgresql -p 5432 -U postgres
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
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 