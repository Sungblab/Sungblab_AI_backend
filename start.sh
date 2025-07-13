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
echo "REDIS_URL: $REDIS_URL"
redis_counter=0
redis_max_retries=30

# 클라우드 타입 환경에서는 Redis가 내부적으로 6379 포트로 실행됨
# 외부 포트 30641은 포트 포워딩용이므로 내부 포트 6379 사용
REDIS_HOST="redis"
REDIS_PORT="6379"

echo "Using internal Redis connection: $REDIS_HOST:$REDIS_PORT"

while [ $redis_counter -lt $redis_max_retries ]
do
    echo "Attempting Redis connection to $REDIS_HOST:$REDIS_PORT (Attempt $((redis_counter+1))/$redis_max_retries)"
    
    # Python을 사용해서 Redis 연결 테스트
    if python -c "
import redis
import sys
try:
    r = redis.Redis(host='$REDIS_HOST', port=$REDIS_PORT, socket_timeout=5)
    r.ping()
    print('PONG')
    sys.exit(0)
except Exception as e:
    print(f'Redis connection failed: {e}')
    sys.exit(1)
" 2>/dev/null | grep -q "PONG"; then
        echo "Redis is ready!"
        break
    else
        echo "Redis connection failed. Retrying..."
    fi
    
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
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --log-level warning --timeout-keep-alive 120 --timeout-graceful-shutdown 30 