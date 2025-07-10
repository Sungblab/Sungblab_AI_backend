"""
스케줄링 태스크 관리
"""
import os
import schedule
import time
import threading
from datetime import datetime, timedelta
from app.core.logging_config import cleanup_old_logs, get_log_files_info
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

class ScheduledTasks:
    def __init__(self):
        self.running = False
        self.thread = None
        
    def start(self):
        """스케줄링 태스크 시작"""
        if self.running:
            return
            
        self.running = True
        
        # 스케줄 등록
        schedule.every().day.at("02:00").do(self.cleanup_logs_task)  # 매일 새벽 2시
        schedule.every().week.do(self.weekly_maintenance_task)  # 주간 유지보수
        
        # 백그라운드 스레드 시작
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        
        logger.info("Scheduled tasks started")
        
    def stop(self):
        """스케줄링 태스크 중지"""
        self.running = False
        schedule.clear()
        logger.info("Scheduled tasks stopped")
        
    def _run_scheduler(self):
        """스케줄러 실행"""
        while self.running:
            schedule.run_pending()
            time.sleep(60)  # 1분마다 체크
            
    def cleanup_logs_task(self):
        """로그 정리 태스크"""
        try:
            # 로그 디렉토리 경로
            log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
            
            if os.path.exists(log_dir):
                # 정리 전 로그 파일 정보
                before_info = get_log_files_info(log_dir)
                before_size = before_info.get('total_size_mb', 0)
                
                # 로그 정리 실행
                cleanup_old_logs(log_dir, max_age_days=7)
                
                # 정리 후 로그 파일 정보
                after_info = get_log_files_info(log_dir)
                after_size = after_info.get('total_size_mb', 0)
                
                saved_space = before_size - after_size
                
                logger.info(f"Log cleanup completed. Saved {saved_space:.2f}MB of disk space")
                
        except Exception as e:
            logger.error(f"Error in log cleanup task: {e}")
            
    def weekly_maintenance_task(self):
        """주간 유지보수 태스크"""
        try:
            # 로그 디렉토리 정보 수집
            log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
            
            if os.path.exists(log_dir):
                log_info = get_log_files_info(log_dir)
                
                logger.info(f"Weekly maintenance report:")
                logger.info(f"- Total log files: {log_info.get('file_count', 0)}")
                logger.info(f"- Total log size: {log_info.get('total_size_mb', 0):.2f}MB")
                
                # 로그 파일이 너무 많거나 크면 경고
                if log_info.get('file_count', 0) > 20:
                    logger.warning(f"Too many log files ({log_info.get('file_count', 0)}). Consider more frequent cleanup.")
                    
                if log_info.get('total_size_mb', 0) > 100:
                    logger.warning(f"Log files are taking too much space ({log_info.get('total_size_mb', 0):.2f}MB). Consider reducing log retention.")
                    
        except Exception as e:
            logger.error(f"Error in weekly maintenance task: {e}")
            
    def force_cleanup_logs(self):
        """즉시 로그 정리 실행"""
        logger.info("Force cleanup initiated")
        self.cleanup_logs_task()

# 전역 스케줄 매니저
scheduled_tasks = ScheduledTasks() 