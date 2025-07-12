"""
헬스 모니터링 시스템 - 온디맨드 방식 (성능 최적화)
"""
import psutil
import os
import logging
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, List
from threading import Thread, Event

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
    """헬스 모니터링 시스템 - 온디맨드 방식"""
    
    def __init__(self, 
                 cpu_threshold: float = 85.0,        # CPU 사용률 임계값
                 memory_threshold: float = 85.0,     # 메모리 사용률 임계값
                 disk_threshold: float = 95.0,       # 디스크 사용률 임계값
                 response_time_threshold: float = 5.0, # 응답시간 임계값
                 error_rate_threshold: float = 0.1):  # 에러율 임계값 (10%)
        
        self.cpu_threshold = cpu_threshold
        self.memory_threshold = memory_threshold
        self.disk_threshold = disk_threshold
        self.response_time_threshold = response_time_threshold
        self.error_rate_threshold = error_rate_threshold
        
        self.start_time = datetime.now()
        
        # 요청 통계 (간소화)
        self.request_count = 0
        self.error_count = 0
        self.total_response_time = 0.0
        self.last_reset_time = datetime.now()
        
        # 최근 메트릭 (캐시용 - 5분간 유효)
        self.cached_metrics = None
        self.cache_timestamp = None
        self.cache_duration = 300  # 5분
        
    def start(self):
        """헬스 모니터링 시작 (온디맨드 방식이므로 백그라운드 스레드 없음)"""
        self.start_time = datetime.now()
        logger.info("Health monitor started (on-demand mode)")
    
    def stop(self):
        """헬스 모니터링 중지"""
        logger.info("Health monitor stopped")
    
    def _collect_metrics_lightweight(self) -> HealthMetrics:
        """가벼운 헬스 메트릭 수집 (필수 항목만)"""
        try:
            process = psutil.Process(os.getpid())
            
            # CPU 사용률 (즉시 반환, interval=0으로 빠른 체크)
            cpu_percent = process.cpu_percent(interval=0)
            
            # 메모리 사용률
            memory_percent = process.memory_percent()
            
            # 디스크 사용률 (루트 파티션만)
            disk_usage = psutil.disk_usage('/')
            disk_usage_percent = disk_usage.percent
            
            # 간단한 프로세스 정보
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
            
        except Exception as e:
            logger.error(f"Error collecting metrics: {e}")
            # 에러 시 기본값 반환
            return HealthMetrics(
                cpu_percent=0.0,
                memory_percent=0.0,
                disk_usage_percent=0.0,
                open_files=0,
                connections=0,
                threads=1,
                uptime_seconds=(datetime.now() - self.start_time).total_seconds(),
                response_time_avg=0.0,
                error_rate=0.0,
                timestamp=datetime.now()
            )
    
    def _evaluate_health(self, metrics: HealthMetrics) -> HealthStatus:
        """헬스 상태 평가 (간소화)"""
        critical_issues = []
        warning_issues = []
        
        # 디스크 사용률 체크 (가장 중요)
        if metrics.disk_usage_percent > self.disk_threshold:
            critical_issues.append(f"High disk usage: {metrics.disk_usage_percent:.1f}%")
        elif metrics.disk_usage_percent > self.disk_threshold * 0.9:
            warning_issues.append(f"Elevated disk usage: {metrics.disk_usage_percent:.1f}%")
        
        # 메모리 사용률 체크
        if metrics.memory_percent > self.memory_threshold:
            critical_issues.append(f"High memory usage: {metrics.memory_percent:.1f}%")
        elif metrics.memory_percent > self.memory_threshold * 0.8:
            warning_issues.append(f"Elevated memory usage: {metrics.memory_percent:.1f}%")
        
        # CPU 사용률 체크 (덜 중요)
        if metrics.cpu_percent > self.cpu_threshold:
            warning_issues.append(f"High CPU usage: {metrics.cpu_percent:.1f}%")
        
        # 상태 결정
        if critical_issues:
            return HealthStatus.CRITICAL
        elif warning_issues:
            return HealthStatus.WARNING
        else:
            return HealthStatus.HEALTHY
    
    def record_request(self, response_time: float, is_error: bool = False):
        """요청 기록 (간소화)"""
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
        """현재 헬스 상태 반환 (캐시 사용)"""
        now = datetime.now()
        
        # 캐시가 유효한지 확인 (5분 이내)
        if (self.cached_metrics and self.cache_timestamp and 
            (now - self.cache_timestamp).total_seconds() < self.cache_duration):
            metrics = self.cached_metrics
        else:
            # 새로운 메트릭 수집
            metrics = self._collect_metrics_lightweight()
            self.cached_metrics = metrics
            self.cache_timestamp = now
        
        status = self._evaluate_health(metrics)
        
        return {
            "status": status.value,
            "timestamp": metrics.timestamp.isoformat(),
            "metrics": {
                "cpu_percent": metrics.cpu_percent,
                "memory_percent": metrics.memory_percent,
                "memory_rss": metrics.memory_percent * 10,  # 근사치
                "disk_usage_percent": metrics.disk_usage_percent,
                "open_files": metrics.open_files,
                "connections": metrics.connections,
                "threads": metrics.threads,
                "uptime_seconds": metrics.uptime_seconds,
                "response_time_avg": metrics.response_time_avg,
                "error_rate": metrics.error_rate
            },
            "cache_info": {
                "cached": self.cached_metrics is not None,
                "cache_age_seconds": (now - self.cache_timestamp).total_seconds() if self.cache_timestamp else 0
            }
        }
    
    def get_current_metrics(self) -> Dict[str, Any]:
        """현재 메트릭 반환"""
        return self.get_health_status()

# 전역 헬스 모니터 (온디맨드 방식)
health_monitor = HealthMonitor()

def get_health_status() -> Dict[str, Any]:
    """헬스 상태 반환"""
    return health_monitor.get_health_status()

def record_request_metrics(response_time: float, is_error: bool = False):
    """요청 메트릭 기록"""
    health_monitor.record_request(response_time, is_error) 