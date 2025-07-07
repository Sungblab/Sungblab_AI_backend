import logging
import os
from logging.handlers import RotatingFileHandler
from app.core.config import settings

# 로거 설정
logger = logging.getLogger("sungblab_api")
logger.setLevel(settings.effective_log_level)

# 파일 핸들러 설정 (LOG_FILE이 설정되어 있는 경우에만)
if settings.LOG_FILE:
    # 로그 디렉토리 생성
    os.makedirs(os.path.dirname(settings.LOG_FILE), exist_ok=True)
    
    file_handler = RotatingFileHandler(
        settings.LOG_FILE,
        maxBytes=10485760,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(file_handler)

# 콘솔 핸들러 설정
console_handler = logging.StreamHandler()
console_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logger.addHandler(console_handler) 