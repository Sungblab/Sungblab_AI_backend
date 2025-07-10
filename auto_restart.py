#!/usr/bin/env python3
"""
자동 재시작 스크립트
서버 상태를 모니터링하고 필요시 자동으로 재시작
"""

import time
import requests
import subprocess
import sys
import os
import logging
from datetime import datetime, timedelta
from typing import Optional

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('auto_restart.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class AutoRestartMonitor:
    """자동 재시작 모니터"""
    
    def __init__(self,
                 server_url: str = "http://localhost:8000",
                 check_interval: int = 60,  # 1분마다 체크
                 max_consecutive_failures: int = 3,
                 restart_command: str = "python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"):
        
        self.server_url = server_url
        self.check_interval = check_interval
        self.max_consecutive_failures = max_consecutive_failures
        self.restart_command = restart_command
        
        self.consecutive_failures = 0
        self.last_restart_time = None
        self.min_restart_interval = 300  # 5분 최소 재시작 간격
        
        self.process = None
        
    def check_server_health(self) -> bool:
        """서버 상태 체크"""
        try:
            # 기본 헬스 체크
            response = requests.get(
                f"{self.server_url}/health",
                timeout=10
            )
            
            if response.status_code != 200:
                logger.warning(f"Health check failed with status {response.status_code}")
                return False
            
            # 상세 헬스 체크
            try:
                detailed_response = requests.get(
                    f"{self.server_url}/health/detailed",
                    timeout=10
                )
                
                if detailed_response.status_code == 200:
                    health_data = detailed_response.json()
                    status = health_data.get("status", "unknown")
                    
                    if status == "critical":
                        logger.warning("Server is in critical state")
                        return False
                    
                    # 메모리 사용률 체크
                    metrics = health_data.get("metrics", {})
                    memory_percent = metrics.get("memory_percent", 0)
                    cpu_percent = metrics.get("cpu_percent", 0)
                    
                    if memory_percent > 90 or cpu_percent > 95:
                        logger.warning(f"High resource usage: Memory {memory_percent}%, CPU {cpu_percent}%")
                        return False
                    
                    # 연속 비정상 상태 체크
                    unhealthy_count = health_data.get("consecutive_unhealthy_count", 0)
                    if unhealthy_count >= 5:
                        logger.warning(f"Server has been unhealthy for {unhealthy_count} consecutive checks")
                        return False
                        
            except Exception as e:
                logger.debug(f"Detailed health check failed: {e}")
                # 기본 헬스 체크가 성공했으므로 계속 진행
                pass
            
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Health check request failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Health check error: {e}")
            return False
    
    def should_restart(self) -> bool:
        """재시작 필요 여부 결정"""
        # 최근 재시작 후 최소 간격 체크
        if self.last_restart_time:
            time_since_restart = (datetime.now() - self.last_restart_time).total_seconds()
            if time_since_restart < self.min_restart_interval:
                logger.debug(f"Too soon to restart (last restart: {time_since_restart:.0f}s ago)")
                return False
        
        # 연속 실패 횟수 체크
        if self.consecutive_failures >= self.max_consecutive_failures:
            logger.warning(f"Max consecutive failures reached: {self.consecutive_failures}")
            return True
        
        return False
    
    def restart_server(self) -> bool:
        """서버 재시작"""
        try:
            logger.info("Starting server restart...")
            
            # 기존 프로세스 종료
            if self.process and self.process.poll() is None:
                logger.info("Terminating existing process...")
                self.process.terminate()
                
                # 5초 대기 후 강제 종료
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning("Process did not terminate gracefully, killing...")
                    self.process.kill()
                    self.process.wait()
            
            # 새 프로세스 시작
            logger.info(f"Starting new process: {self.restart_command}")
            
            self.process = subprocess.Popen(
                self.restart_command.split(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.getcwd()
            )
            
            # 시작 대기
            time.sleep(10)
            
            # 프로세스 상태 확인
            if self.process.poll() is not None:
                stdout, stderr = self.process.communicate()
                logger.error(f"Process failed to start. stdout: {stdout.decode()}, stderr: {stderr.decode()}")
                return False
            
            # 서버 응답 확인
            max_wait = 30
            for i in range(max_wait):
                if self.check_server_health():
                    logger.info("Server restart successful")
                    self.last_restart_time = datetime.now()
                    self.consecutive_failures = 0
                    return True
                time.sleep(1)
            
            logger.error("Server failed to respond after restart")
            return False
            
        except Exception as e:
            logger.error(f"Server restart failed: {e}")
            return False
    
    def run(self):
        """모니터링 시작"""
        logger.info(f"Starting auto-restart monitor for {self.server_url}")
        logger.info(f"Check interval: {self.check_interval}s")
        logger.info(f"Max consecutive failures: {self.max_consecutive_failures}")
        
        while True:
            try:
                logger.debug("Checking server health...")
                
                if self.check_server_health():
                    logger.debug("Server is healthy")
                    self.consecutive_failures = 0
                else:
                    self.consecutive_failures += 1
                    logger.warning(f"Server health check failed (consecutive failures: {self.consecutive_failures})")
                    
                    if self.should_restart():
                        logger.info("Initiating server restart...")
                        if self.restart_server():
                            logger.info("Server restart completed successfully")
                        else:
                            logger.error("Server restart failed")
                            # 재시작 실패 시 잠시 대기
                            time.sleep(60)
                
                time.sleep(self.check_interval)
                
            except KeyboardInterrupt:
                logger.info("Shutdown requested by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error in monitoring loop: {e}")
                time.sleep(self.check_interval)
        
        # 정리 작업
        if self.process and self.process.poll() is None:
            logger.info("Terminating server process...")
            self.process.terminate()
            self.process.wait()

def main():
    """메인 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Auto-restart monitor for SungbLab AI API')
    parser.add_argument('--url', default='http://localhost:8000', help='Server URL')
    parser.add_argument('--interval', type=int, default=60, help='Check interval (seconds)')
    parser.add_argument('--max-failures', type=int, default=3, help='Max consecutive failures')
    parser.add_argument('--restart-cmd', default='python -m uvicorn app.main:app --host 0.0.0.0 --port 8000', 
                       help='Restart command')
    
    args = parser.parse_args()
    
    monitor = AutoRestartMonitor(
        server_url=args.url,
        check_interval=args.interval,
        max_consecutive_failures=args.max_failures,
        restart_command=args.restart_cmd
    )
    
    try:
        monitor.run()
    except KeyboardInterrupt:
        logger.info("Monitoring stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 