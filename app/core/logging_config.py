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
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    max_file_size: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    log_format: Optional[str] = None
):
    """로깅 설정"""
    
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
    
    # 파일 핸들러 추가 (순환 로그)
    if log_file:
        # 로그 디렉토리 생성
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        # 순환 파일 핸들러
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_file_size,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # 성능 로그 별도 설정
    performance_logger = logging.getLogger("performance")
    performance_logger.setLevel(logging.INFO)
    
    if log_file:
        # 성능 로그 전용 파일
        perf_log_file = log_file.replace('.log', '_performance.log')
        perf_handler = logging.handlers.RotatingFileHandler(
            perf_log_file,
            maxBytes=max_file_size,
            backupCount=backup_count,
            encoding='utf-8'
        )
        perf_handler.setLevel(logging.INFO)
        perf_handler.setFormatter(formatter)
        performance_logger.addHandler(perf_handler)
    
    # 에러 로그 별도 설정
    error_logger = logging.getLogger("error")
    error_logger.setLevel(logging.ERROR)
    
    if log_file:
        # 에러 로그 전용 파일
        error_log_file = log_file.replace('.log', '_error.log')
        error_handler = logging.handlers.RotatingFileHandler(
            error_log_file,
            maxBytes=max_file_size,
            backupCount=backup_count,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        error_logger.addHandler(error_handler)
    
    # 헬스 모니터 로그 별도 설정
    health_logger = logging.getLogger("health_monitor")
    health_logger.setLevel(logging.INFO)
    
    if log_file:
        # 헬스 로그 전용 파일
        health_log_file = log_file.replace('.log', '_health.log')
        health_handler = logging.handlers.RotatingFileHandler(
            health_log_file,
            maxBytes=max_file_size,
            backupCount=backup_count,
            encoding='utf-8'
        )
        health_handler.setLevel(logging.INFO)
        health_handler.setFormatter(formatter)
        health_logger.addHandler(health_handler)
    
    # 메모리 관리 로그 별도 설정
    memory_logger = logging.getLogger("memory_manager")
    memory_logger.setLevel(logging.INFO)
    
    if log_file:
        # 메모리 로그 전용 파일
        memory_log_file = log_file.replace('.log', '_memory.log')
        memory_handler = logging.handlers.RotatingFileHandler(
            memory_log_file,
            maxBytes=max_file_size,
            backupCount=backup_count,
            encoding='utf-8'
        )
        memory_handler.setLevel(logging.INFO)
        memory_handler.setFormatter(formatter)
        memory_logger.addHandler(memory_handler)

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

def cleanup_old_logs(log_directory: str, max_age_days: int = 30):
    """오래된 로그 파일 정리"""
    if not os.path.exists(log_directory):
        return
    
    cutoff_time = datetime.now().timestamp() - (max_age_days * 24 * 3600)
    
    for filename in os.listdir(log_directory):
        if filename.endswith('.log') or filename.endswith('.log.1'):
            filepath = os.path.join(log_directory, filename)
            try:
                if os.path.getctime(filepath) < cutoff_time:
                    os.remove(filepath)
                    print(f"Removed old log file: {filepath}")
            except OSError as e:
                print(f"Error removing log file {filepath}: {e}")

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
    """기본 로깅 설정 초기화"""
    log_file = None
    
    # 로그 디렉토리 설정
    if hasattr(settings, 'LOG_FILE') and settings.LOG_FILE:
        log_file = settings.LOG_FILE
    else:
        # 기본 로그 파일 위치
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'sungblab_api.log')
    
    # 로깅 설정 적용
    setup_logging(
        log_level=settings.LOG_LEVEL,
        log_file=log_file,
        max_file_size=10 * 1024 * 1024,  # 10MB
        backup_count=5,
        log_format=settings.LOG_FORMAT
    )
    
    # 오래된 로그 정리 (30일 이상)
    if log_file:
        log_directory = os.path.dirname(log_file)
        cleanup_old_logs(log_directory, max_age_days=30)
    
    logging.info("Logging system initialized") 