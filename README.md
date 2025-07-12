# Sungblab AI Backend

Sungblab AI Backend는 강력하고 확장 가능한 AI 기반 애플리케이션을 신속하게 구축할 수 있도록 설계된 고성능 백엔드 프레임워크입니다. 최신 기술 스택을 활용하여 보안, 속도, 안정성에 중점을 두었으며, 모듈화된 아키텍처를 통해 유지보수와 기능 확장이 용이합니다.

## ✨ 주요 기능

- **🚀 고성능 비동기 처리**: FastAPI를 기반으로 비동기 처리를 완벽하게 지원하여 높은 동시성과 빠른 응답 속도를 보장합니다.
- **🛡️ 강화된 보안 시스템**: OAuth2, JWT 토큰 기반의 안전한 인증 시스템과 함께, 접근 제어, 데이터 검증, 보안 헤더 설정을 포함한 다층적 보안 아키텍처를 갖추고 있습니다.
- **✍️ 구조화된 로깅**: 프로젝트 전반에 걸쳐 일관된 형식의 구조화된 로그(JSON)를 기록합니다. 이를 통해 로그 검색, 분석, 모니터링이 용이하며, 에러 추적 및 디버깅 효율을 극대화합니다.
- **⚡ 지능형 캐싱 전략**: Redis를 활용한 중앙 집중식 캐시 시스템을 통해 반복적인 AI 연산(토큰 계산, 임베딩 생성) 및 데이터베이스 쿼리 비용을 최소화합니다. 인증, API 응답 등 다양한 영역에 특화된 캐시를 적용하여 시스템 전반의 성능을 향상시킵니다.
- **📊 선택적 성능 모니터링**: 필요에 따라 요청 처리 시간, 메모리 사용량, 데이터베이스 쿼리 성능 등을 모니터링하여 시스템 병목 현상을 식별하고 최적화할 수 있습니다.
- **🔄 최적화된 배치 처리**: 대용량 데이터(텍스트, 파일)의 임베딩 생성 및 처리를 위한 비동기 배치 처리 시스템을 구현했습니다. 우선순위 큐를 통해 중요한 작업을 먼저 처리하고, 시스템 부하를 효율적으로 관리합니다.
- **⏰ 스케줄링 태스크**: 로그 정리 및 주간 유지보수와 같은 백그라운드 작업을 자동화하여 시스템의 안정적인 운영을 지원합니다.
- **⚙️ 체계적인 설정 관리**: Pydantic을 사용하여 환경 변수 기반의 설정을 관리하며, 개발, 테스트, 프로덕션 환경에 맞는 설정을 손쉽게 적용할 수 있습니다.
- **📦 모듈화된 아키텍처**: 기능별(사용자, 채팅, 프로젝트 등)로 코드를 명확하게 분리하여 응집도를 높이고 결합도를 낮췄습니다. 이는 코드의 재사용성을 높이고, 새로운 기능을 추가하거나 기존 기능을 수정하기 쉽게 만듭니다.

## 🛠️ 기술 스택

- **Backend**: Python, FastAPI, Uvicorn
- **Database**: PostgreSQL (with pgvector for vector similarity search)
- **Cache**: Redis
- **Async**: asyncio
- **Data Validation**: Pydantic
- **Authentication**: python-jose, passlib
- **Dependency Management**: pip

## 📂 프로젝트 구조

```
app/
├── api/            # API 엔드포인트 및 라우터
├── core/           # 핵심 로직 (보안, 캐시, 로깅, 설정 등)
├── crud/           # 데이터베이스 CRUD (Create, Read, Update, Delete) 연산
├── db/             # 데이터베이스 세션 및 초기화
├── models/         # SQLAlchemy 데이터베이스 모델
├── schemas/        # Pydantic 데이터 스키마 (요청/응답 모델)
├── utils/          # 보조 유틸리티 함수
└── main.py         # FastAPI 애플리케이션 진입점
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
   **주요 환경 변수:**
   - `DATABASE_URL`: PostgreSQL 데이터베이스 연결 정보
   - `REDIS_URL`: Redis 연결 정보
   - `SECRET_KEY`: JWT 토큰 생성을 위한 비밀 키
   - `ALGORITHM`: JWT 토큰 암호화 알고리즘

3. **Docker를 이용한 실행:**
   프로젝트 루트 디렉토리에서 다음 명령어를 실행하여 Docker 컨테이너를 빌드하고 실행합니다.
   ```bash
   docker-compose up --build
   ```
   이 명령어는 FastAPI 애플리케이션, PostgreSQL 데이터베이스, Redis를 함께 실행합니다.

### 3. API 문서

애플리케이션이 실행되면, 다음 주소에서 자동으로 생성된 API 문서를 확인할 수 있습니다.

- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

## 🙌 기여하기

이 프로젝트에 기여하고 싶으시다면, 언제든지 환영합니다! 다음 절차를 따라주세요.

1. 이 저장소를 Fork합니다.
2. 새로운 기능이나 버그 수정을 위한 브랜치를 생성합니다 (`git checkout -b feature/AmazingFeature`).
3. 코드를 수정하고, 변경 사항을 커밋합니다 (`git commit -m 'Add some AmazingFeature'`).
4. 생성한 브랜치로 Push합니다 (`git push origin feature/AmazingFeature`).
5. Pull Request를 생성합니다.

모든 기여는 프로젝트를 더 나은 방향으로 이끌어가는 데 큰 도움이 됩니다.

## 📄 라이선스

이 프로젝트는 [MIT 라이선스](LICENSE)에 따라 배포됩니다.
