# SungbLab AI 백엔드

SungbLab AI 백엔드는 FastAPI 기반의 RESTful API 서버로, 도커 환경에서 실행되도록 설계되었습니다.

## 오픈소스 프로젝트

이 프로젝트는 오픈소스로 운영되며, 커뮤니티의 기여를 적극적으로 환영합니다. 코드 개선, 버그 수정, 새로운 기능 추가 등 어떤 형태의 기여도 가능합니다. 특히 코드 리팩토링에 관심 있는 개발자분들의 참여를 기다리고 있습니다.

## 기술 스택

- **프레임워크**: FastAPI
- **데이터베이스**: PostgreSQL
- **ORM**: SQLAlchemy
- **마이그레이션**: Alembic
- **인증**: JWT, OAuth2 (Google)
- **AI 통합**: Anthropic, DeepSeek, Gemini, Sonar
- **컨테이너화**: Docker, Docker Compose

## 시스템 요구사항

- Docker
- Docker Compose

## 설치 및 실행 방법

### 1. 저장소 클론

```bash
git clone https://github.com/yourusername/Sungblab_AI_backend.git
cd Sungblab_AI_backend
```

### 2. 환경 변수 설정

`.env` 파일을 프로젝트 루트 디렉토리에 생성하고 필요한 환경 변수를 설정합니다:

```
DATABASE_URL=postgresql://username:password@db:5432/dbname
SECRET_KEY=your_secret_key
ACCESS_TOKEN_EXPIRE_MINUTES=30
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=your_email@example.com
SMTP_PASSWORD=your_email_password
SMTP_TLS=True
EMAILS_FROM_EMAIL=your_email@example.com
EMAILS_FROM_NAME=Your Name
FRONTEND_URL=https://your-frontend-url.com
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
GOOGLE_REDIRECT_URI=https://your-backend-url.com/api/v1/auth/google/callback
ANTHROPIC_API_KEY=your_anthropic_api_key
DEEPSEEK_API_KEY=your_deepseek_api_key
GEMINI_API_KEY=your_gemini_api_key
SONAR_API_KEY=your_sonar_api_key
BACKEND_CORS_ORIGINS=["http://localhost:3000","https://sungblab.com"]
ADMIN_EMAIL=admin@example.com
ADMIN_NAME=Admin
ADMIN_INITIAL_PASSWORD=admin_password
CREATE_INITIAL_ADMIN=True
```

### 3. Docker Compose로 실행

```bash
docker-compose up -d
```

이 명령어는 다음 작업을 수행합니다:

- 필요한 Docker 이미지 빌드
- 컨테이너 실행
- 데이터베이스 연결 대기
- 데이터베이스 마이그레이션 실행
- FastAPI 애플리케이션 시작

### 4. API 접근

애플리케이션이 실행되면 다음 URL로 접근할 수 있습니다:

- API: http://localhost:8000

## 프로젝트 구조

```
.
├── alembic/                  # 데이터베이스 마이그레이션
├── app/
│   ├── api/                  # API 엔드포인트
│   ├── core/                 # 핵심 설정 및 유틸리티
│   ├── crud/                 # CRUD 작업
│   ├── db/                   # 데이터베이스 관련 코드
│   ├── models/               # SQLAlchemy 모델
│   ├── schemas/              # Pydantic 스키마
│   └── main.py               # 애플리케이션 진입점
├── .env                      # 환경 변수
├── .dockerignore             # Docker 빌드 제외 파일
├── .gitignore                # Git 제외 파일
├── Dockerfile                # Docker 이미지 정의
├── docker-compose.yml        # Docker Compose 설정
├── requirements.txt          # Python 의존성
├── alembic.ini               # Alembic 설정
└── start.sh                  # 시작 스크립트
```

## 개발 환경 설정

로컬 개발 환경을 설정하려면:

1. Python 3.9 설치
2. 가상 환경 생성 및 활성화
3. 의존성 설치: `pip install -r requirements.txt`
4. 로컬 PostgreSQL 데이터베이스 설정
5. `.env` 파일에서 `DATABASE_URL`을 로컬 데이터베이스로 설정
6. 마이그레이션 실행: `alembic upgrade head`
7. 애플리케이션 실행: `uvicorn app.main:app --reload`

## 로깅

로그는 `app/logs/` 디렉토리에 저장됩니다. 로그 레벨은 환경 변수를 통해 설정할 수 있습니다.

## 기여 방법

이 프로젝트에 기여하고 싶으시다면:

1. 이슈 트래커를 확인하여 해결할 문제를 찾거나 새로운 기능을 제안하세요.
2. 저장소를 포크하고 변경사항을 위한 새 브랜치를 만드세요.
3. 코드를 작성하고 테스트하세요.
4. 변경사항을 커밋하고 푸시하세요.
5. 풀 리퀘스트를 제출하세요.

특히 다음 영역에서의 기여를 환영합니다:

- 코드 리팩토링 및 구조 개선
- 성능 최적화
- 테스트 커버리지 향상
- 문서화 개선
- 새로운 기능 구현

## 연락처

프로젝트에 관한 질문이나 제안이 있으시면 다음 이메일로 연락해주세요:

- 이메일: sungblab@gmail.com

## 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다.
