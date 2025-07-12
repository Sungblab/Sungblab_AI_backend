FROM python:3.9-slim

WORKDIR /app

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y     netcat-traditional     postgresql-client     build-essential     libpq-dev     && rm -rf /var/lib/apt/lists/*

# 타임존 설정
ENV TZ=Asia/Seoul
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 전체 소스 코드 복사
COPY . .

# 시작 스크립트 권한 설정 및 줄바꿈 문자 변경
RUN chmod +x start.sh && \
    sed -i 's/\r$//' start.sh

# Python 패키지 경로 설정
ENV PYTHONPATH=/app

# 로그 디렉토리 생성
RUN mkdir -p /app/logs && chmod 777 /app/logs

CMD ["./start.sh"] 