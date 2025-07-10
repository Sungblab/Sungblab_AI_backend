"""
시스템 헬스 모니터링 및 자동 재시작 시스템
"""
import psutil
import time
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from threading import Thread, Event
from dataclasses import dataclass
from enum import Enum
import subprocess
import sys
import os

logger = logging.getLogger("health_monitor")

class HealthStatus(str, Enum):
    """헬스 상태"""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNHEALTHY = "unhealthy"

@dataclass
class HealthMetrics:
    """헬스 메트릭"""
    cpu_percent: float
    memory_percent: float
    disk_usage_percent: float
    open_files: int
    connections: int
    threads: int
    uptime_seconds: float
    response_time_avg: float
    error_rate: float
    timestamp: datetime

class HealthMonitor:
    """헬스 모니터링 시스템"""
    
    def __init__(self, 
                 check_interval: int = 60,           # 1분마다 체크
                 cpu_threshold: float = 85.0,        # CPU 사용률 임계값
                 memory_threshold: float = 85.0,     # 메모리 사용률 임계값
                 disk_threshold: float = 90.0,       # 디스크 사용률 임계값
                 response_time_threshold: float = 5.0, # 응답시간 임계값
                 error_rate_threshold: float = 0.1,  # 에러율 임계값 (10%)
                 unhealthy_duration: int = 300):     # 5분간 비정상 상태시 재시작
        
        self.check_interval = check_interval
        self.cpu_threshold = cpu_threshold
        self.memory_threshold = memory_threshold
        self.disk_threshold = disk_threshold
        self.response_time_threshold = response_time_threshold
        self.error_rate_threshold = error_rate_threshold
        self.unhealthy_duration = unhealthy_duration
        
        self.is_running = False
        self.stop_event = Event()
        self.monitor_thread = None
        self.start_time = datetime.now()
        
        # 메트릭 히스토리 (최근 100개)
        self.metrics_history = []
        self.max_history = 100
        
        # 비정상 상태 추적
        self.unhealthy_start_time = None
        self.consecutive_unhealthy_count = 0
        
        # 요청 통계
        self.request_count = 0
        self.error_count = 0
        self.total_response_time = 0.0
        self.last_reset_time = datetime.now()
        
    def start(self):
        """헬스 모니터링 시작"""
        if not self.is_running:
            self.is_running = True
            self.stop_event.clear()
            self.start_time = datetime.now()
            
            self.monitor_thread = Thread(target=self._monitor_loop)
            self.monitor_thread.daemon = True
            self.monitor_thread.start()
            
            logger.info("Health monitor started")
    
    def stop(self):
        """헬스 모니터링 중지"""
        if self.is_running:
            self.is_running = False
            self.stop_event.set()
            
            if self.monitor_thread:
                self.monitor_thread.join(timeout=5)
                
            logger.info("Health monitor stopped")
    
    def _monitor_loop(self):
        """모니터링 루프"""
        while self.is_running and not self.stop_event.wait(self.check_interval):
            try:
                # 헬스 메트릭 수집
                metrics = self._collect_metrics()
                
                # 헬스 상태 평가
                status = self._evaluate_health(metrics)
                
                # 메트릭 히스토리 업데이트
                self._update_history(metrics)
                
                # 상태별 처리
                self._handle_health_status(status, metrics)
                
                # 로깅
                logger.info(f"Health check: {status.value} - "
                           f"CPU: {metrics.cpu_percent:.1f}%, "
                           f"Memory: {metrics.memory_percent:.1f}%, "
                           f"Disk: {metrics.disk_usage_percent:.1f}%")
                
            except Exception as e:
                logger.error(f"Health monitoring error: {e}")
    
    def _collect_metrics(self) -> HealthMetrics:
        """헬스 메트릭 수집"""
        process = psutil.Process(os.getpid())
        
        # CPU 사용률
        cpu_percent = process.cpu_percent(interval=1)
        
        # 메모리 사용률
        memory_info = process.memory_info()
        memory_percent = process.memory_percent()
        
        # 디스크 사용률
        disk_usage = psutil.disk_usage('/')
        disk_usage_percent = disk_usage.percent
        
        # 파일 및 연결 수
        open_files = len(process.open_files())
        connections = len(process.connections())
        threads = process.num_threads()
        
        # 업타임
        uptime_seconds = (datetime.now() - self.start_time).total_seconds()
        
        # 응답시간 평균
        response_time_avg = (self.total_response_time / self.request_count 
                           if self.request_count > 0 else 0.0)
        
        # 에러율
        error_rate = (self.error_count / self.request_count 
                     if self.request_count > 0 else 0.0)
        
        return HealthMetrics(
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
            disk_usage_percent=disk_usage_percent,
            open_files=open_files,
            connections=connections,
            threads=threads,
            uptime_seconds=uptime_seconds,
            response_time_avg=response_time_avg,
            error_rate=error_rate,
            timestamp=datetime.now()
        )
    
    def _evaluate_health(self, metrics: HealthMetrics) -> HealthStatus:
        """헬스 상태 평가"""
        critical_issues = []
        warning_issues = []
        
        # CPU 사용률 체크
        if metrics.cpu_percent > self.cpu_threshold:
            critical_issues.append(f"High CPU usage: {metrics.cpu_percent:.1f}%")
        elif metrics.cpu_percent > self.cpu_threshold * 0.8:
            warning_issues.append(f"Elevated CPU usage: {metrics.cpu_percent:.1f}%")
        
        # 메모리 사용률 체크
        if metrics.memory_percent > self.memory_threshold:
            critical_issues.append(f"High memory usage: {metrics.memory_percent:.1f}%")
        elif metrics.memory_percent > self.memory_threshold * 0.8:
            warning_issues.append(f"Elevated memory usage: {metrics.memory_percent:.1f}%")
        
        # 디스크 사용률 체크
        if metrics.disk_usage_percent > self.disk_threshold:
            critical_issues.append(f"High disk usage: {metrics.disk_usage_percent:.1f}%")
        elif metrics.disk_usage_percent > self.disk_threshold * 0.9:
            warning_issues.append(f"Elevated disk usage: {metrics.disk_usage_percent:.1f}%")
        
        # 응답시간 체크
        if metrics.response_time_avg > self.response_time_threshold:
            critical_issues.append(f"High response time: {metrics.response_time_avg:.2f}s")
        elif metrics.response_time_avg > self.response_time_threshold * 0.8:
            warning_issues.append(f"Elevated response time: {metrics.response_time_avg:.2f}s")
        
        # 에러율 체크
        if metrics.error_rate > self.error_rate_threshold:
            critical_issues.append(f"High error rate: {metrics.error_rate:.1%}")
        elif metrics.error_rate > self.error_rate_threshold * 0.8:
            warning_issues.append(f"Elevated error rate: {metrics.error_rate:.1%}")
        
        # 파일 디스크립터 체크
        if metrics.open_files > 1000:
            critical_issues.append(f"Too many open files: {metrics.open_files}")
        elif metrics.open_files > 500:
            warning_issues.append(f"Many open files: {metrics.open_files}")
        
        # 상태 결정
        if critical_issues:
            logger.warning(f"Critical issues detected: {', '.join(critical_issues)}")
            return HealthStatus.CRITICAL
        elif warning_issues:
            logger.info(f"Warning issues detected: {', '.join(warning_issues)}")
            return HealthStatus.WARNING
        else:
            return HealthStatus.HEALTHY
    
    def _handle_health_status(self, status: HealthStatus, metrics: HealthMetrics):
        """헬스 상태 처리"""
        if status in [HealthStatus.CRITICAL, HealthStatus.UNHEALTHY]:
            if self.unhealthy_start_time is None:
                self.unhealthy_start_time = datetime.now()
                self.consecutive_unhealthy_count = 1
            else:
                self.consecutive_unhealthy_count += 1
                
                # 지속적인 비정상 상태 체크
                unhealthy_duration = (datetime.now() - self.unhealthy_start_time).total_seconds()
                if unhealthy_duration > self.unhealthy_duration:
                    logger.critical(f"System has been unhealthy for {unhealthy_duration:.0f} seconds")
                    self._trigger_restart_recommendation()
        else:
            # 정상 상태로 회복
            if self.unhealthy_start_time is not None:
                recovery_time = (datetime.now() - self.unhealthy_start_time).total_seconds()
                logger.info(f"System recovered after {recovery_time:.0f} seconds")
                
            self.unhealthy_start_time = None
            self.consecutive_unhealthy_count = 0
    
    def _trigger_restart_recommendation(self):
        """재시작 권고 발생"""
        logger.critical("RESTART RECOMMENDED: System has been in unhealthy state for too long")
        
        # 재시작 권고 로그를 특별한 형태로 기록
        restart_log = {
            "event": "RESTART_RECOMMENDED",
            "timestamp": datetime.now().isoformat(),
            "reason": "prolonged_unhealthy_state",
            "unhealthy_duration": self.unhealthy_duration,
            "consecutive_unhealthy_count": self.consecutive_unhealthy_count
        }
        
        logger.critical(f"RESTART_RECOMMENDATION: {restart_log}")
    
    def _update_history(self, metrics: HealthMetrics):
        """메트릭 히스토리 업데이트"""
        self.metrics_history.append(metrics)
        
        # 최대 히스토리 크기 유지
        if len(self.metrics_history) > self.max_history:
            self.metrics_history.pop(0)
    
    def record_request(self, response_time: float, is_error: bool = False):
        """요청 기록"""
        self.request_count += 1
        self.total_response_time += response_time
        
        if is_error:
            self.error_count += 1
        
        # 1시간마다 통계 리셋
        if (datetime.now() - self.last_reset_time).total_seconds() > 3600:
            self.reset_request_stats()
    
    def reset_request_stats(self):
        """요청 통계 리셋"""
        self.request_count = 0
        self.error_count = 0
        self.total_response_time = 0.0
        self.last_reset_time = datetime.now()
    
    def get_health_status(self) -> Dict[str, Any]:
        """현재 헬스 상태 반환"""
        if not self.metrics_history:
            return {"status": "unknown", "message": "No metrics available"}
        
        latest_metrics = self.metrics_history[-1]
        status = self._evaluate_health(latest_metrics)
        
        return {
            "status": status.value,
            "timestamp": latest_metrics.timestamp.isoformat(),
            "metrics": {
                "cpu_percent": latest_metrics.cpu_percent,
                "memory_percent": latest_metrics.memory_percent,
                "disk_usage_percent": latest_metrics.disk_usage_percent,
                "open_files": latest_metrics.open_files,
                "connections": latest_metrics.connections,
                "threads": latest_metrics.threads,
                "uptime_seconds": latest_metrics.uptime_seconds,
                "response_time_avg": latest_metrics.response_time_avg,
                "error_rate": latest_metrics.error_rate
            },
            "unhealthy_duration": (
                (datetime.now() - self.unhealthy_start_time).total_seconds()
                if self.unhealthy_start_time else 0
            ),
            "consecutive_unhealthy_count": self.consecutive_unhealthy_count
        }
    
    def get_metrics_history(self, limit: int = 50) -> list:
        """메트릭 히스토리 반환"""
        return [
            {
                "timestamp": m.timestamp.isoformat(),
                "cpu_percent": m.cpu_percent,
                "memory_percent": m.memory_percent,
                "disk_usage_percent": m.disk_usage_percent,
                "response_time_avg": m.response_time_avg,
                "error_rate": m.error_rate
            }
            for m in self.metrics_history[-limit:]
        ]

# 전역 헬스 모니터
health_monitor = HealthMonitor()

def get_health_status() -> Dict[str, Any]:
    """헬스 상태 반환"""
    return health_monitor.get_health_status()

def record_request_metrics(response_time: float, is_error: bool = False):
    """요청 메트릭 기록"""
    health_monitor.record_request(response_time, is_error) 