"""
로깅 설정 및 순환 관리
"""
import logging
import logging.handlers
import os
from typing import Optional
from datetime import datetime
from app.core.config import settings

def setup_logging(
    log_level: str = "WARNING",  # INFO에서 WARNING으로 변경
    log_file: Optional[str] = None,
    max_file_size: int = 2 * 1024 * 1024,  # 2MB (5MB에서 2MB로 줄임)
    backup_count: int = 1,  # 2개에서 1개로 줄임
    log_format: Optional[str] = None,
    enable_file_logging: bool = False  # 파일 로깅 비활성화 옵션 추가
):
    """로깅 설정 - 최소화된 로깅"""
    
    # 로그 레벨 설정
    level = getattr(logging, log_level.upper(), logging.WARNING)
    
    # 로그 포맷 설정 (더 간단하게)
    if log_format is None:
        log_format = "%(levelname)s - %(name)s - %(message)s"  # 타임스탬프 제거
    
    formatter = logging.Formatter(log_format)
    
    # 루트 로거 설정
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # 기존 핸들러 제거
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 콘솔 핸들러 추가
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # 파일 로깅이 활성화된 경우에만 파일 핸들러 추가
    if enable_file_logging and log_file:
        # 로그 디렉토리 생성
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        # 에러 로그만 파일에 저장 (WARNING 이상만)
        error_log_file = log_file.replace('.log', '_errors.log')
        error_handler = logging.handlers.RotatingFileHandler(
            error_log_file,
            maxBytes=max_file_size,
            backupCount=backup_count,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.WARNING)  # WARNING 이상만 파일에 저장
        error_handler.setFormatter(formatter)
        root_logger.addHandler(error_handler)
        
    # 외부 라이브러리 로깅 최소화
    logging.getLogger("uvicorn.access").setLevel(logging.ERROR)
    logging.getLogger("uvicorn.error").setLevel(logging.ERROR)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)
    logging.getLogger("alembic").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.ERROR)
    logging.getLogger("httpcore").setLevel(logging.ERROR)
    
    # 기타 로거들도 최소화
    for logger_name in ["performance", "health_monitor", "memory_manager"]:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.ERROR)  # ERROR 레벨로 설정
        logger.propagate = True  # 루트 로거로 전파

def setup_time_based_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    when: str = "midnight",  # 'midnight', 'h' (hourly), 'd' (daily)
    interval: int = 1,
    backup_count: int = 30,
    log_format: Optional[str] = None
):
    """시간 기반 로그 순환 설정"""
    
    # 로그 레벨 설정
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    # 로그 포맷 설정
    if log_format is None:
        log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    formatter = logging.Formatter(log_format)
    
    # 루트 로거 설정
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # 기존 핸들러 제거
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 콘솔 핸들러 추가
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # 시간 기반 파일 핸들러 추가
    if log_file:
        # 로그 디렉토리 생성
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        # 시간 기반 순환 파일 핸들러
        time_handler = logging.handlers.TimedRotatingFileHandler(
            log_file,
            when=when,
            interval=interval,
            backupCount=backup_count,
            encoding='utf-8'
        )
        time_handler.setLevel(level)
        time_handler.setFormatter(formatter)
        root_logger.addHandler(time_handler)

def cleanup_old_logs(log_directory: str, max_age_days: int = 7):  # 30일에서 7일로 줄임
    """오래된 로그 파일 정리 - 더 자주 정리"""
    if not os.path.exists(log_directory):
        return
    
    cutoff_time = datetime.now().timestamp() - (max_age_days * 24 * 3600)
    cleaned_files = []
    
    for filename in os.listdir(log_directory):
        if filename.endswith('.log') or '.log.' in filename:
            filepath = os.path.join(log_directory, filename)
            try:
                if os.path.getctime(filepath) < cutoff_time:
                    file_size = os.path.getsize(filepath)
                    os.remove(filepath)
                    cleaned_files.append(f"{filename} ({file_size / (1024*1024):.2f}MB)")
            except OSError as e:
                print(f"Error removing log file {filepath}: {e}")
    
    if cleaned_files:
        print(f"Cleaned {len(cleaned_files)} old log files: {', '.join(cleaned_files)}")

def get_log_files_info(log_directory: str) -> dict:
    """로그 파일 정보 반환"""
    if not os.path.exists(log_directory):
        return {}
    
    log_files = {}
    total_size = 0
    
    for filename in os.listdir(log_directory):
        if filename.endswith('.log') or '.log.' in filename:
            filepath = os.path.join(log_directory, filename)
            try:
                stat = os.stat(filepath)
                size = stat.st_size
                total_size += size
                
                log_files[filename] = {
                    'size': size,
                    'size_mb': round(size / (1024 * 1024), 2),
                    'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                }
            except OSError:
                continue
    
    return {
        'files': log_files,
        'total_size': total_size,
        'total_size_mb': round(total_size / (1024 * 1024), 2),
        'file_count': len(log_files)
    }

# 기본 로깅 설정 적용
def init_logging():
    """기본 로깅 설정 초기화 - 최소화된 로깅"""
    log_file = None
    
    # 로그 디렉토리 설정 (하지만 기본적으로 파일 로깅 비활성화)
    if hasattr(settings, 'LOG_FILE') and settings.LOG_FILE:
        log_file = settings.LOG_FILE
    else:
        # 기본 로그 파일 위치
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'sungblab_api.log')
    
    # 최소화된 로깅 설정 적용
    setup_logging(
        log_level="WARNING",  # WARNING 레벨로 설정
        log_file=log_file,
        max_file_size=2 * 1024 * 1024,  # 2MB
        backup_count=1,  # 1개
        log_format="%(levelname)s - %(name)s - %(message)s",
        enable_file_logging=False  # 파일 로깅 비활성화
    )
    
    # 로그 정리 (시작 시 기존 로그 파일들 정리)
    if log_file:
        log_directory = os.path.dirname(log_file)
        cleanup_old_logs(log_directory, max_age_days=1)  # 1일 이상된 로그 즉시 정리
    
    logging.warning("Logging system initialized with minimal logging") 