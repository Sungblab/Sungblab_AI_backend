#!/bin/sh

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

# Redis 연결 대기 (클라우드 타입 환경)
echo "Waiting for Redis..."
redis_counter=0
redis_max_retries=30

# REDIS_URL에서 호스트와 포트 추출
REDIS_HOST=$(echo "$REDIS_URL" | sed -n 's/.*:\/\/\([^:]*\):.*/\1/p')
REDIS_PORT=$(echo "$REDIS_URL" | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')

# 기본값 설정
REDIS_HOST=${REDIS_HOST:-"localhost"}
REDIS_PORT=${REDIS_PORT:-"6379"}

while [ $redis_counter -lt $redis_max_retries ]
do
    if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping > /dev/null 2>&1; then
        echo "Redis is ready!"
        break
    fi
    echo "Waiting for Redis... Attempt $((redis_counter+1))/$redis_max_retries"
    echo "Trying to connect to Redis at $REDIS_HOST:$REDIS_PORT"
    redis_counter=$((redis_counter+1))
    sleep 2
done

if [ $redis_counter -eq $redis_max_retries ]; then
    echo "Could not connect to Redis after $redis_max_retries attempts"
    echo "Starting without Redis caching..."
fi

# 데이터베이스 초기화 (Supabase 환경)
echo "Initializing database..."
python -c "from app.db.init_db import init_db; init_db()"
if [ $? -eq 0 ]; then
    echo "Database initialization successful!"
else
    echo "Database initialization failed. Starting without initialization."
fi

# FastAPI 애플리케이션 시작 (워커 수 줄이기)
echo "Starting FastAPI application..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --log-level warning 