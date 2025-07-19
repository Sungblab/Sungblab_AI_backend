# SungbLab AI Backend

SungbLab AI Backend는 교육용 AI 플랫폼을 위한 고성능 백엔드 시스템으로, 다양한 AI 모델과의 대화, 프로젝트 기반 학습, 파일 분석 등을 지원합니다. Google Gemini AI를 중심으로 한 멀티모달 AI 서비스를 제공하며, 확장 가능한 아키텍처로 설계되었습니다.

## ✨ 주요 기능

### 🧠 AI 채팅 시스템
- **일반 채팅**: Google Gemini AI를 활용한 실시간 대화
- **프로젝트 채팅**: 파일 업로드 및 컨텍스트 기반 전문 상담
- **스트리밍 응답**: Server-Sent Events를 통한 실시간 응답
- **토큰 사용량 추적**: 정확한 비용 계산 및 사용량 모니터링

### 📁 프로젝트 관리 시스템
- **파일 업로드**: 다양한 형식 지원 (PDF, DOCX, TXT, 이미지 등)
- **벡터 검색**: pgvector를 활용한 임베딩 기반 유사도 검색
- **지식 베이스**: 업로드된 파일들을 기반으로 한 컨텍스트 제공
- **프롬프트 개선**: AI 기반 프롬프트 최적화

### 👥 사용자 및 인증 시스템
- **회원가입/로그인**: 이메일 기반 계정 관리
- **소셜 로그인**: Google OAuth2 연동
- **이메일 인증**: 안전한 계정 활성화
- **구독 관리**: 토큰 기반 사용량 제한 시스템

### 🔧 관리자 기능
- **사용자 관리**: 계정 활성화, 권한 부여, 사용량 초기화
- **구독 관리**: 플랜 변경, 만료 관리, 갱신 처리
- **시스템 모니터링**: 채팅 통계, 사용량 분석, 오버뷰 대시보드

### 🛡️ 고급 보안 및 성능 기능
- **JWT 토큰 인증**: 안전한 API 접근 제어
- **Redis 캐싱**: 반복 연산 최적화 및 응답 속도 향상
- **구조화된 로깅**: JSON 기반 로그 시스템으로 추적 및 디버깅 지원
- **에러 추적**: Sentry 연동으로 실시간 오류 모니터링
- **성능 모니터링**: 요청 처리 시간 및 시스템 리소스 추적

## 🛠️ 기술 스택

### 핵심 프레임워크
- **Backend**: Python 3.9+, FastAPI, Uvicorn
- **Database**: PostgreSQL + pgvector (벡터 검색)
- **Cache**: Redis (세션 및 응답 캐싱)
- **AI Integration**: Google Gemini API

### 주요 라이브러리
- **비동기 처리**: asyncio, aiofiles
- **데이터 검증**: Pydantic, pydantic-settings
- **인증 보안**: python-jose, passlib, OAuth2
- **데이터베이스**: SQLAlchemy, psycopg2-binary
- **모니터링**: Sentry, Prometheus, psutil
- **파일 처리**: Pillow, bleach
- **이메일**: emails, jinja2
- **배경 작업**: Celery, schedule
- **기타**: httpx, python-multipart, tiktoken

## 📂 프로젝트 구조

```
Sungblab_AI_backend/
├── app/
│   ├── api/                    # API 라우터 및 엔드포인트
│   │   ├── api_v1/
│   │   │   ├── api.py         # 메인 API 라우터
│   │   │   └── endpoints/     # 기능별 엔드포인트
│   │   │       ├── admin.py   # 관리자 기능 (사용자/구독 관리)
│   │   │       ├── auth.py    # 인증 (로그인/회원가입/소셜로그인)
│   │   │       ├── chat.py    # 일반 AI 채팅
│   │   │       ├── projects.py # 프로젝트 관리 및 전문 채팅
│   │   │       └── users.py   # 사용자 프로필 관리
│   │   └── deps.py            # 의존성 주입
│   ├── core/                   # 핵심 시스템 로직
│   │   ├── config.py          # 환경 설정 관리
│   │   ├── security.py        # 보안 및 인증
│   │   ├── cache.py           # Redis 캐싱 시스템
│   │   ├── chat.py            # AI 채팅 코어 로직
│   │   ├── logging_config.py  # 구조화된 로깅
│   │   ├── error_tracking.py  # Sentry 에러 추적
│   │   └── health_monitor.py  # 시스템 모니터링
│   ├── crud/                   # 데이터베이스 CRUD 연산
│   │   ├── crud_user.py       # 사용자 데이터 관리
│   │   ├── crud_chat.py       # 채팅 데이터 관리
│   │   ├── crud_project.py    # 프로젝트 데이터 관리
│   │   └── crud_subscription.py # 구독 관리
│   ├── models/                 # SQLAlchemy 데이터베이스 모델
│   │   ├── user.py            # 사용자 모델
│   │   ├── chat.py            # 채팅 관련 모델
│   │   ├── project.py         # 프로젝트 모델
│   │   └── subscription.py    # 구독 모델
│   ├── schemas/                # Pydantic 스키마 (요청/응답)
│   ├── utils/                  # 유틸리티 함수
│   └── main.py                # FastAPI 애플리케이션 진입점
├── docker-compose.yml          # Docker 컨테이너 설정
├── Dockerfile                 # 애플리케이션 Docker 이미지
├── requirements.txt           # Python 의존성
└── start.sh                  # 서버 시작 스크립트
```

## 🚀 시작하기

### 1. 사전 요구사항

- Python 3.9 이상
- Docker 및 Docker Compose
- Git

### 2. 설치

1. **저장소 클론:**
   ```bash
   git clone https://github.com/your-username/Sungblab_AI_backend.git
   cd Sungblab_AI_backend
   ```

2. **환경 변수 설정:**
   `.env.example` 파일을 복사하여 `.env` 파일을 생성하고, 환경에 맞게 변수들을 수정합니다.
   ```bash
   cp .env.example .env
   ```

   **필수 환경 변수:**
   ```env
   # 데이터베이스 및 캐시
   DATABASE_URL=postgresql://user:password@localhost:5432/sungblab_db
   REDIS_URL=redis://localhost:6379
   
   # JWT 인증
   SECRET_KEY=your-secret-key-here
   ALGORITHM=HS256
   ACCESS_TOKEN_EXPIRE_MINUTES=1440
   
   # AI API
   GEMINI_API_KEY=your-gemini-api-key
   
   # 이메일 설정
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=your-email@gmail.com
   SMTP_PASSWORD=your-app-password
   EMAILS_FROM_EMAIL=your-email@gmail.com
   EMAILS_FROM_NAME=SungbLab
   
   # Google OAuth
   GOOGLE_CLIENT_ID=your-google-client-id
   GOOGLE_CLIENT_SECRET=your-google-client-secret
   GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/social/google
   
   # 관리자 계정
   ADMIN_EMAIL=admin@sungblab.com
   ADMIN_NAME=Administrator
   ADMIN_INITIAL_PASSWORD=admin123
   CREATE_INITIAL_ADMIN=true
   
   # 기타
   FRONTEND_URL=http://localhost:3000
   ENVIRONMENT=development
   DEBUG=true
   
   # 보안 설정 (프로덕션 환경)
   # ENVIRONMENT=production
   # DEBUG=false
   # ENABLE_PERFORMANCE_MONITORING=true
   # ENABLE_HEALTH_MONITOR=true
   ```

3. **Docker를 이용한 실행:**
   ```bash
   # 개발 환경 실행 (Redis만 포함)
   docker-compose up --build
   
   # 또는 백그라운드 실행
   docker-compose up -d --build
   ```
   
   **로컬 개발 환경:**
   ```bash
   # 의존성 설치
   pip install -r requirements.txt
   
   # Redis 시작 (별도 터미널)
   docker run -d -p 6379:6379 redis:7-alpine
   
   # 애플리케이션 시작
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

### 3. API 문서 및 테스트

애플리케이션이 실행되면, 다음 주소에서 자동으로 생성된 API 문서를 확인할 수 있습니다.

- **Swagger UI**: [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs) (개발 환경에서만 접근 가능)
- **ReDoc**: [http://localhost:8000/api/v1/redoc](http://localhost:8000/api/v1/redoc) (개발 환경에서만 접근 가능)
- **Health Check**: [http://localhost:8000/](http://localhost:8000/)
- **Admin Docs**: [http://localhost:8000/admin/docs](http://localhost:8000/admin/docs) (관리자 전용)

## 🔒 보안 고려사항

### API 문서 보안
- **개발 환경**: Swagger/ReDoc 문서가 자동으로 생성되어 접근 가능
- **프로덕션 환경**: API 문서 접근이 자동으로 비활성화됨
- **관리자 전용**: `/admin/docs` 엔드포인트를 통한 제한적 문서 접근

### 환경별 설정
```env
# 개발 환경 (문서 접근 가능)
ENVIRONMENT=development
DEBUG=true

# 프로덕션 환경 (문서 접근 차단)
ENVIRONMENT=production
DEBUG=false
```

### 추가 보안 권장사항
1. **환경 변수 보호**: `.env` 파일을 `.gitignore`에 포함
2. **HTTPS 사용**: 프로덕션 환경에서는 반드시 HTTPS 사용
3. **API 키 관리**: 민감한 API 키는 환경 변수로 관리
4. **접근 제어**: 관리자 기능은 적절한 권한 검증 필요

## 📚 API 엔드포인트 가이드

### 🔐 인증 (Authentication)
```
POST /api/v1/auth/signup           # 회원가입
POST /api/v1/auth/login            # 로그인
POST /api/v1/auth/social/google    # 구글 소셜 로그인
POST /api/v1/auth/send-verification # 이메일 인증 발송
POST /api/v1/auth/verify-email     # 이메일 인증 확인
GET  /api/v1/auth/me              # 현재 사용자 정보
```

### 💬 일반 채팅
```
POST /api/v1/chat/rooms           # 채팅방 생성
GET  /api/v1/chat/rooms           # 채팅방 목록
POST /api/v1/chat/rooms/{id}/chat # AI와 채팅 (스트리밍)
GET  /api/v1/chat/stats/token-usage # 토큰 사용량 조회
POST /api/v1/chat/anonymous-chat  # 익명 채팅
```

### 📁 프로젝트 관리
```
POST /api/v1/projects             # 프로젝트 생성
GET  /api/v1/projects             # 프로젝트 목록
POST /api/v1/projects/{id}/files/upload # 파일 업로드
POST /api/v1/projects/{id}/chats/{chat_id}/chat # 전문 AI 채팅
POST /api/v1/projects/{id}/knowledge/search # 지식 검색
```

### 👤 사용자 관리
```
GET  /api/v1/users/me             # 내 정보 조회
GET  /api/v1/users/me/subscription # 구독 정보 조회
POST /api/v1/users/me/change-password # 비밀번호 변경
```

### 🛠️ 관리자 (Admin Only)
```
GET  /api/v1/admin/users          # 전체 사용자 목록
GET  /api/v1/admin/overview       # 시스템 개요
PATCH /api/v1/admin/users/{id}/status # 사용자 상태 변경
GET  /api/v1/admin/subscriptions  # 구독 관리
```

## 🔧 주요 특징

### 🏗️ 아키텍처 특징
- **모듈화된 설계**: 기능별로 명확하게 분리된 구조
- **의존성 주입**: FastAPI의 Depends를 활용한 깔끔한 의존성 관리
- **에러 핸들링**: 전역 에러 핸들러로 일관된 에러 응답
- **자동 문서화**: OpenAPI/Swagger 자동 생성

### 🛡️ 보안 기능
- **JWT 토큰 인증**: 안전한 사용자 인증 시스템
- **비밀번호 해싱**: bcrypt를 이용한 안전한 비밀번호 저장
- **CORS 설정**: 프론트엔드와의 안전한 통신
- **입력 검증**: Pydantic을 통한 강력한 데이터 검증

### ⚡ 성능 최적화
- **Redis 캐싱**: 반복적인 AI 연산 결과 캐싱
- **비동기 처리**: 높은 동시성을 위한 async/await 패턴
- **배치 처리**: 대용량 파일 처리를 위한 백그라운드 작업
- **데이터베이스 최적화**: 인덱싱 및 쿼리 최적화

### 📊 모니터링 및 관찰성
- **구조화된 로깅**: JSON 형태의 일관된 로그 포맷
- **에러 추적**: Sentry를 통한 실시간 에러 모니터링
- **성능 메트릭**: Prometheus 호환 메트릭 수집
- **헬스 체크**: 시스템 상태 모니터링

## 🙌 기여하기

프로젝트 개선에 참여해주세요!

1. **Fork** 이 저장소
2. **브랜치 생성** (`git checkout -b feature/amazing-feature`)
3. **변경사항 커밋** (`git commit -m 'Add amazing feature'`)
4. **브랜치 푸시** (`git push origin feature/amazing-feature`)
5. **Pull Request 생성**

### 개발 가이드라인
- 코드 스타일: Python PEP 8 준수
- 타입 힌트 필수 사용
- 모든 함수에 docstring 작성
- 테스트 코드 작성 권장

## 📄 라이선스

이 프로젝트는 [MIT 라이선스](LICENSE)에 따라 배포됩니다.
