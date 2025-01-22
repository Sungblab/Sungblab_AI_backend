import logging
import sys
from logging.handlers import RotatingFileHandler
from app.core.config import settings

def setup_logging():
    # 로거 설정
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, settings.LOG_LEVEL))

    # 포맷터 설정
    formatter = logging.Formatter(settings.LOG_FORMAT)

    # 콘솔 핸들러
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 파일 핸들러 (프로덕션 환경에서만)
    if settings.ENVIRONMENT == "production" and settings.LOG_FILE:
        file_handler = RotatingFileHandler(
            settings.LOG_FILE,
            maxBytes=10485760,  # 10MB
            backupCount=5
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # 개발 환경에서는 디버그 레벨 로깅
    if settings.ENVIRONMENT == "development":
        logger.setLevel(logging.DEBUG)
        
    return logger 