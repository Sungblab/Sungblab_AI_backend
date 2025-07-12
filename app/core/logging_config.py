"""
중앙 집중식 통합 로깅 설정 모듈

- JSON 형식의 구조화된 로그 출력
- 파일 크기 및 시간 기반 로그 순환
- 외부 라이브러리 로깅 레벨 제어
- 오래된 로그 파일 자동 정리
"""
import logging
import logging.handlers
import os
import json
import traceback
from datetime import datetime
from typing import Optional, Dict, Any

from app.core.config import settings

# --- JSON Formatter ---

class JsonFormatter(logging.Formatter):
    """로그 레코드를 JSON 형식으로 변환하는 포맷터"""
    def format(self, record: logging.LogRecord) -> str:
        log_object = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_object['exc_info'] = self.formatException(record.exc_info)
            log_object['traceback'] = traceback.format_exc()
        
        # extra 필드의 내용을 로그 객체에 추가
        if hasattr(record, '__dict__'):
            for key, value in record.__dict__.items():
                if key not in log_object and key not in ['args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename', 'funcName', 'levelname', 'levelno', 'lineno', 'module', 'msecs', 'message', 'msg', 'name', 'pathname', 'process', 'processName', 'relativeCreated', 'stack_info', 'thread', 'threadName']:
                    log_object[key] = value
            
        return json.dumps(log_object, ensure_ascii=False)

# --- 로깅 설정 함수 ---

def setup_logging(
    log_level: str = settings.LOG_LEVEL,
    log_file: Optional[str] = settings.LOG_FILE,
    max_file_size: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    enable_file_logging: bool = True
):
    """애플리케이션 전역 로깅을 설정합니다."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    formatter = JsonFormatter()
    
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # 기존 핸들러 제거
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 콘솔 핸들러 추가
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # 파일 핸들러 추가 (프로덕션 환경 기본)
    if enable_file_logging and log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
            
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_file_size,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # 주요 외부 라이브러리 로깅 레벨 조정
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("alembic").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    logging.info(f"Logging system initialized. Level: {log_level}, File logging: {enable_file_logging}")

# --- 로그 정리 함수 ---

def cleanup_old_logs(log_directory: str, max_age_days: int = 7):
    """지정된 기간보다 오래된 로그 파일을 정리합니다."""
    if not os.path.exists(log_directory):
        return
    
    cutoff_time = datetime.now().timestamp() - (max_age_days * 24 * 3600)
    for filename in os.listdir(log_directory):
        if filename.endswith('.log') or '.log.' in filename:
            filepath = os.path.join(log_directory, filename)
            try:
                if os.path.getmtime(filepath) < cutoff_time:
                    os.remove(filepath)
                    logging.info(f"Removed old log file: {filepath}")
            except OSError as e:
                logging.error(f"Error removing log file {filepath}: {e}")

def get_log_files_info(log_directory: str) -> Dict[str, Any]:
    """로그 파일들의 총 크기와 개수를 반환합니다."""
    total_size = 0
    file_count = 0
    if os.path.exists(log_directory):
        for filename in os.listdir(log_directory):
            if filename.endswith('.log') or '.log.' in filename:
                filepath = os.path.join(log_directory, filename)
                try:
                    if os.path.isfile(filepath):
                        total_size += os.path.getsize(filepath)
                        file_count += 1
                except OSError as e:
                    logging.error(f"Error getting size of log file {filepath}: {e}")
    return {
        "file_count": file_count,
        "total_size_mb": total_size / (1024 * 1024)
    }

# --- 애플리케이션 시작 시 로깅 초기화 ---
# main.py에서 이 함수를 호출하여 로깅을 설정합니다.
def init_logging():
    setup_logging()