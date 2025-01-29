FROM python:3.9-slim

WORKDIR /app

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y \
    netcat-traditional \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# 타임존 설정
ENV TZ=Asia/Seoul
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Python 패키지 경로 설정
ENV PYTHONPATH=/app

# 시작 스크립트 추가
COPY start.sh .
RUN chmod +x start.sh

# 로그 디렉토리 생성
RUN mkdir -p /app/logs && chmod 777 /app/logs

CMD ["./start.sh"] 