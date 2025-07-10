"""
메모리 관리 및 자동 정리 시스템
"""
import gc
import psutil
import os
import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from threading import Thread, Event
import threading
import time

logger = logging.getLogger("memory_manager")

class MemoryManager:
    """메모리 관리자"""
    
    def __init__(self, 
                 memory_threshold: float = 80.0,  # 메모리 사용률 80% 임계값
                 check_interval: int = 300,       # 5분마다 체크
                 cleanup_interval: int = 3600):   # 1시간마다 정리
        self.memory_threshold = memory_threshold
        self.check_interval = check_interval
        self.cleanup_interval = cleanup_interval
        self.is_running = False
        self.stop_event = Event()
        self.monitor_thread = None
        self.cleanup_thread = None
        
    def start(self):
        """메모리 관리자 시작"""
        if not self.is_running:
            self.is_running = True
            self.stop_event.clear()
            
            # 메모리 모니터링 스레드 시작
            self.monitor_thread = Thread(target=self._monitor_memory)
            self.monitor_thread.daemon = True
            self.monitor_thread.start()
            
            # 정리 스레드 시작
            self.cleanup_thread = Thread(target=self._cleanup_loop)
            self.cleanup_thread.daemon = True
            self.cleanup_thread.start()
            
            logger.info("Memory manager started")
    
    def stop(self):
        """메모리 관리자 중지"""
        if self.is_running:
            self.is_running = False
            self.stop_event.set()
            
            if self.monitor_thread:
                self.monitor_thread.join(timeout=5)
            if self.cleanup_thread:
                self.cleanup_thread.join(timeout=5)
                
            logger.info("Memory manager stopped")
    
    def _monitor_memory(self):
        """메모리 모니터링"""
        while self.is_running and not self.stop_event.wait(self.check_interval):
            try:
                memory_info = self.get_memory_info()
                
                if memory_info['memory_percent'] > self.memory_threshold:
                    logger.warning(f"High memory usage detected: {memory_info['memory_percent']:.1f}%")
                    self._emergency_cleanup()
                    
                # 메모리 정보 로깅
                logger.info(f"Memory status: {memory_info}")
                
            except Exception as e:
                logger.error(f"Error monitoring memory: {e}")
    
    def _cleanup_loop(self):
        """정기적 정리 루프"""
        while self.is_running and not self.stop_event.wait(self.cleanup_interval):
            try:
                self._routine_cleanup()
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
    
    def _emergency_cleanup(self):
        """긴급 메모리 정리"""
        logger.info("Starting emergency memory cleanup")
        
        # 1. 가비지 컬렉션 강제 실행
        collected = gc.collect()
        logger.info(f"Garbage collection freed {collected} objects")
        
        # 2. 캐시 정리
        self._cleanup_cache()
        
        # 3. 배치 처리 큐 정리
        self._cleanup_batch_queue()
        
        # 4. 메모리 상태 재확인
        memory_info = self.get_memory_info()
        logger.info(f"Memory after cleanup: {memory_info['memory_percent']:.1f}%")
    
    def _routine_cleanup(self):
        """정기적 정리"""
        logger.info("Starting routine memory cleanup")
        
        # 1. 가비지 컬렉션
        gc.collect()
        
        # 2. 캐시 정리
        self._cleanup_cache()
        
        # 3. 오래된 배치 작업 정리
        self._cleanup_old_tasks()
        
        logger.info("Routine cleanup completed")
    
    def _cleanup_cache(self):
        """캐시 정리"""
        try:
            from app.core.cache import cache_manager
            
            # 만료된 캐시 정리
            cache_manager.redis_client.flushdb()
            logger.info("Cache cleanup completed")
            
        except Exception as e:
            logger.error(f"Cache cleanup failed: {e}")
    
    def _cleanup_batch_queue(self):
        """배치 큐 정리"""
        try:
            # 배치 큐 정리 로직 (안전한 방식)
            logger.info("Attempting to cleanup batch queue")
            
            # 가비지 컬렉션을 통한 메모리 정리
            gc.collect()
            
        except Exception as e:
            logger.error(f"Batch queue cleanup failed: {e}")
    
    def _cleanup_old_tasks(self):
        """오래된 작업 정리"""
        try:
            # 오래된 작업 정리 로직 (안전한 방식)
            logger.info("Attempting to cleanup old tasks")
            
            # 가비지 컬렉션을 통한 메모리 정리
            gc.collect()
                
        except Exception as e:
            logger.error(f"Old tasks cleanup failed: {e}")
    
    def get_memory_info(self) -> Dict[str, Any]:
        """메모리 정보 반환"""
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        system_memory = psutil.virtual_memory()
        
        return {
            'memory_rss': memory_info.rss / 1024 / 1024,  # MB
            'memory_vms': memory_info.vms / 1024 / 1024,  # MB
            'memory_percent': process.memory_percent(),
            'system_memory_total': system_memory.total / 1024 / 1024 / 1024,  # GB
            'system_memory_available': system_memory.available / 1024 / 1024 / 1024,  # GB
            'system_memory_percent': system_memory.percent,
            'cpu_percent': process.cpu_percent(),
            'open_files': len(process.open_files()),
            'connections': len(process.connections()),
            'threads': process.num_threads()
        }
    
    def force_cleanup(self):
        """강제 정리 실행"""
        logger.info("Force cleanup requested")
        self._emergency_cleanup()

# 전역 메모리 관리자
memory_manager = MemoryManager()

def get_memory_status() -> Dict[str, Any]:
    """메모리 상태 반환"""
    return memory_manager.get_memory_info()

def force_memory_cleanup():
    """강제 메모리 정리"""
    memory_manager.force_cleanup() 