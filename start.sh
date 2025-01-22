#!/bin/sh

# 데이터베이스 연결 대기 함수
wait_for_db() {
    echo "Waiting for database..."
    while ! pg_isready -h db -p 5432 -U postgres > /dev/null 2>&1; do
        echo "Database is unavailable - sleeping"
        sleep 2
    done
    echo "Database is up and running!"
}

# 데이터베이스 연결 대기
wait_for_db

# 데이터베이스 마이그레이션 실행
echo "Running database migrations..."
alembic upgrade head

# FastAPI 애플리케이션 시작
echo "Starting FastAPI application..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 