# 서버 성능 최적화 가이드

## 문제 상황
서버를 하루 정도 운영하면 성능이 저하되어 재시작이 필요한 상황이 발생했습니다.

## 구현된 해결책

### 1. 메모리 관리 시스템 (`app/core/memory_manager.py`)
- **자동 메모리 모니터링**: 5분마다 메모리 사용률 체크
- **임계값 기반 정리**: 메모리 사용률 80% 초과 시 자동 정리
- **정기적 정리**: 1시간마다 가비지 컬렉션 및 캐시 정리
- **긴급 정리**: 메모리 부족 시 강제 정리

### 2. 캐시 최적화 (`app/core/cache.py`)
- **TTL 단축**: 캐시 만료 시간을 1시간에서 30분으로 단축
- **크기 제한**: 캐시 크기 100MB 제한
- **자동 정리**: 만료된 캐시와 오래된 캐시 자동 정리
- **연결 풀 최적화**: Redis 연결 수 제한

### 3. 헬스 모니터링 (`app/core/health_monitor.py`)
- **실시간 모니터링**: CPU, 메모리, 디스크 사용률 모니터링
- **성능 메트릭**: 응답 시간, 에러율 추적
- **자동 알림**: 비정상 상태 5분 지속 시 재시작 권고
- **히스토리 관리**: 최근 100개 메트릭 기록

### 4. 데이터베이스 최적화 (`app/db/session.py`)
- **연결 풀 최적화**: 기본 연결 수 감소 (5→3)
- **연결 재활용**: 30분마다 연결 재활용
- **연결 타임아웃**: 연결 대기 시간 제한
- **자동 롤백**: 에러 발생 시 자동 트랜잭션 롤백

### 5. 로깅 시스템 (`app/core/logging_config.py`)
- **로그 순환**: 10MB 단위로 로그 파일 순환
- **카테고리별 로그**: 성능, 에러, 헬스 로그 분리
- **자동 정리**: 30일 이상 된 로그 파일 자동 삭제
- **백업 관리**: 최대 5개 백업 파일 유지

### 6. 자동 재시작 시스템 (`auto_restart.py`)
- **헬스 체크**: 1분마다 서버 상태 확인
- **자동 재시작**: 3회 연속 실패 시 자동 재시작
- **안전 장치**: 5분 최소 재시작 간격 설정
- **프로세스 관리**: 안전한 프로세스 종료 및 재시작

## 사용 방법

### 1. 서버 실행
```bash
# 기본 실행
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 자동 재시작 모니터와 함께 실행
python auto_restart.py --url http://localhost:8000 --interval 60 --max-failures 3
```

### 2. 헬스 체크 API
```bash
# 기본 헬스 체크
curl http://localhost:8000/health

# 상세 헬스 체크
curl http://localhost:8000/health/detailed

# 메트릭 히스토리
curl http://localhost:8000/health/metrics
```

### 3. 수동 메모리 정리
```python
from app.core.memory_manager import force_memory_cleanup
force_memory_cleanup()
```

### 4. 캐시 정리
```python
from app.core.cache import cache_manager
cache_manager.clear_old_cache()
```

## 모니터링 지표

### 1. 메모리 사용률
- **정상**: < 80%
- **경고**: 80-90%
- **위험**: > 90%

### 2. CPU 사용률
- **정상**: < 85%
- **경고**: 85-95%
- **위험**: > 95%

### 3. 응답 시간
- **정상**: < 2초
- **경고**: 2-5초
- **위험**: > 5초

### 4. 에러율
- **정상**: < 5%
- **경고**: 5-10%
- **위험**: > 10%

## 로그 파일 위치

```
app/logs/
├── sungblab_api.log          # 메인 로그
├── sungblab_api_performance.log  # 성능 로그
├── sungblab_api_error.log    # 에러 로그
├── sungblab_api_health.log   # 헬스 로그
└── sungblab_api_memory.log   # 메모리 로그
```

## 문제 발생 시 대처 방법

### 1. 메모리 부족
```bash
# 메모리 사용량 확인
curl http://localhost:8000/health/detailed

# 강제 메모리 정리
python -c "from app.core.memory_manager import force_memory_cleanup; force_memory_cleanup()"
```

### 2. 캐시 오버플로
```bash
# 캐시 크기 확인
redis-cli info memory

# 캐시 정리
python -c "from app.core.cache import cache_manager; cache_manager.clear_old_cache()"
```

### 3. 데이터베이스 연결 문제
```bash
# 연결 풀 상태 확인
python -c "from app.db.session import DatabaseManager; print(DatabaseManager.get_connection_info())"

# 연결 정리
python -c "from app.db.session import DatabaseManager; DatabaseManager.dispose_connections()"
```

### 4. 로그 파일 크기 초과
```bash
# 로그 파일 크기 확인
ls -lh app/logs/

# 오래된 로그 정리
python -c "from app.core.logging_config import cleanup_old_logs; cleanup_old_logs('app/logs')"
```

## 성능 최적화 팁

### 1. 정기적 유지보수
- **일일**: 로그 파일 크기 확인
- **주간**: 메모리 사용률 트렌드 분석
- **월간**: 데이터베이스 연결 풀 최적화

### 2. 리소스 모니터링
- **메모리**: 80% 이하 유지
- **CPU**: 85% 이하 유지
- **디스크**: 90% 이하 유지

### 3. 캐시 전략
- **TTL 설정**: 데이터 특성에 맞는 TTL 설정
- **크기 제한**: 메모리 사용량에 맞는 캐시 크기 설정
- **정기 정리**: 불필요한 캐시 정기 정리

### 4. 데이터베이스 최적화
- **연결 풀**: 동시 사용자 수에 맞는 연결 풀 크기 설정
- **쿼리 최적화**: 느린 쿼리 식별 및 최적화
- **인덱스 관리**: 적절한 인덱스 설정

## 알림 및 대응

### 1. 재시작 권고 로그
```
RESTART_RECOMMENDATION: {"event": "RESTART_RECOMMENDED", "timestamp": "...", "reason": "prolonged_unhealthy_state"}
```

### 2. 메모리 부족 경고
```
High memory usage detected: 85.2%
```

### 3. 응답 시간 경고
```
SLOW REQUEST: {"method": "GET", "url": "...", "process_time": 3.45}
```

이러한 로그가 발생하면 즉시 서버 상태를 점검하고 필요시 재시작을 고려해야 합니다. 