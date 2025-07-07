"""
배치 처리 최적화 시스템
임베딩 생성 배치화, 대용량 파일 처리, 비동기 작업 큐 구현
"""

import asyncio
import json
import time
import uuid
from typing import List, Dict, Any, Optional, Callable, Union
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime, timedelta
import threading
from concurrent.futures import ThreadPoolExecutor
import heapq

from app.core.structured_logging import StructuredLogger
from app.core.performance_cache import perf_logger

# 배치 처리 로거
batch_logger = StructuredLogger("batch_processing")

class TaskStatus(str, Enum):
    """작업 상태"""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class TaskPriority(int, Enum):
    """작업 우선순위"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4

@dataclass
class BatchTask:
    """배치 작업 단위"""
    id: str
    task_type: str
    data: Dict[str, Any]
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.id is None:
            self.id = str(uuid.uuid4())
    
    def __lt__(self, other):
        # 우선순위 큐를 위한 비교 함수 (높은 우선순위가 먼저)
        return self.priority.value > other.priority.value
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        data = asdict(self)
        # datetime 객체를 문자열로 변환
        for key in ['created_at', 'started_at', 'completed_at']:
            if data[key]:
                data[key] = data[key].isoformat()
        return data

class EmbeddingBatchProcessor:
    """임베딩 배치 처리기"""
    
    def __init__(self, batch_size: int = 50, max_concurrent: int = 5):
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent
        self.processing_queue = []
        self.processing_lock = threading.Lock()
        
    async def add_embedding_task(
        self,
        texts: List[str],
        model: str,
        project_id: str,
        file_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """임베딩 작업을 배치에 추가"""
        
        task = BatchTask(
            id=str(uuid.uuid4()),
            task_type="embedding_generation",
            data={
                "texts": texts,
                "model": model,
                "project_id": project_id,
                "file_id": file_id,
                "metadata": metadata or {}
            },
            priority=TaskPriority.NORMAL
        )
        
        with self.processing_lock:
            self.processing_queue.append(task)
            
        batch_logger.info("embedding_task_added", {
            "task_id": task.id,
            "text_count": len(texts),
            "model": model,
            "project_id": project_id
        })
        
        return task.id
    
    async def process_embedding_batch(
        self,
        batch_tasks: List[BatchTask],
        client,
        embedding_func: Callable
    ) -> List[BatchTask]:
        """임베딩 배치 처리"""
        
        start_time = time.time()
        batch_logger.info("embedding_batch_started", {
            "batch_size": len(batch_tasks),
            "task_ids": [task.id for task in batch_tasks]
        })
        
        try:
            # 모든 텍스트를 하나의 배치로 수집
            all_texts = []
            task_text_mapping = {}
            
            for task in batch_tasks:
                task.status = TaskStatus.PROCESSING
                task.started_at = datetime.utcnow()
                
                texts = task.data["texts"]
                start_idx = len(all_texts)
                all_texts.extend(texts)
                task_text_mapping[task.id] = (start_idx, start_idx + len(texts))
            
            # 배치 임베딩 생성
            model = batch_tasks[0].data["model"]  # 모든 작업이 같은 모델이라고 가정
            
            embeddings = await embedding_func(all_texts, model, client)
            
            # 결과를 각 작업에 분배
            for task in batch_tasks:
                start_idx, end_idx = task_text_mapping[task.id]
                task_embeddings = embeddings[start_idx:end_idx]
                
                task.result = {
                    "embeddings": task_embeddings,
                    "text_count": len(task.data["texts"]),
                    "embedding_dimensions": len(task_embeddings[0]) if task_embeddings else 0
                }
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.utcnow()
            
            batch_logger.info("embedding_batch_completed", {
                "batch_size": len(batch_tasks),
                "total_embeddings": len(all_texts),
                "duration": time.time() - start_time,
                "success": True
            })
            
        except Exception as e:
            # 배치 전체 실패 처리
            for task in batch_tasks:
                if task.status == TaskStatus.PROCESSING:
                    task.status = TaskStatus.FAILED
                    task.error = str(e)
                    task.completed_at = datetime.utcnow()
                    task.retry_count += 1
            
            batch_logger.error("embedding_batch_failed", {
                "batch_size": len(batch_tasks),
                "error": str(e),
                "duration": time.time() - start_time
            })
        
        return batch_tasks

class FileBatchProcessor:
    """파일 배치 처리기"""
    
    def __init__(self, chunk_size: int = 1000, max_file_size: int = 100 * 1024 * 1024):
        self.chunk_size = chunk_size
        self.max_file_size = max_file_size
        
    async def process_large_file(
        self,
        file_content: str,
        file_name: str,
        project_id: str,
        file_id: str,
        chunk_overlap: int = 100
    ) -> List[Dict[str, Any]]:
        """대용량 파일을 청크로 분할하여 배치 처리"""
        
        start_time = time.time()
        
        if len(file_content.encode()) > self.max_file_size:
            raise ValueError(f"File too large: {len(file_content.encode())} bytes")
        
        batch_logger.info("large_file_processing_started", {
            "file_name": file_name,
            "file_size": len(file_content),
            "project_id": project_id,
            "chunk_size": self.chunk_size
        })
        
        try:
            # 텍스트를 청크로 분할
            chunks = await self._split_text_into_chunks(
                file_content, self.chunk_size, chunk_overlap
            )
            
            # 청크별 메타데이터 생성
            chunk_data = []
            for i, chunk in enumerate(chunks):
                chunk_data.append({
                    "chunk_index": i,
                    "chunk_text": chunk,
                    "chunk_size": len(chunk),
                    "file_name": file_name,
                    "project_id": project_id,
                    "file_id": file_id
                })
            
            batch_logger.info("large_file_processing_completed", {
                "file_name": file_name,
                "total_chunks": len(chunks),
                "duration": time.time() - start_time,
                "avg_chunk_size": sum(len(c) for c in chunks) / len(chunks) if chunks else 0
            })
            
            return chunk_data
            
        except Exception as e:
            batch_logger.error("large_file_processing_failed", {
                "file_name": file_name,
                "error": str(e),
                "duration": time.time() - start_time
            })
            raise
    
    async def _split_text_into_chunks(
        self, 
        text: str, 
        chunk_size: int, 
        overlap: int
    ) -> List[str]:
        """텍스트를 청크로 분할"""
        
        if len(text) <= chunk_size:
            return [text]
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = min(start + chunk_size, len(text))
            
            # 단어 경계에서 자르기 위해 조정
            if end < len(text):
                # 마지막 공백이나 줄바꿈 찾기
                last_space = text.rfind(' ', start, end)
                last_newline = text.rfind('\n', start, end)
                
                boundary = max(last_space, last_newline)
                if boundary > start:
                    end = boundary
            
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            
            # 다음 청크 시작점 (오버랩 고려)
            start = max(start + 1, end - overlap)
            
            # 무한 루프 방지
            if start >= len(text):
                break
        
        return chunks

class AsyncTaskQueue:
    """비동기 작업 큐"""
    
    def __init__(self, max_workers: int = 10, max_queue_size: int = 1000):
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size
        self.task_queue = []  # 우선순위 큐
        self.active_tasks = {}  # 진행 중인 작업들
        self.completed_tasks = {}  # 완료된 작업들 (제한된 수만 보관)
        self.worker_semaphore = asyncio.Semaphore(max_workers)
        self.queue_lock = asyncio.Lock()
        self.is_running = False
        
    async def start(self):
        """큐 시작"""
        self.is_running = True
        batch_logger.info("task_queue_started", {
            "max_workers": self.max_workers,
            "max_queue_size": self.max_queue_size
        })
        
        # 워커들 시작
        workers = []
        for i in range(self.max_workers):
            worker = asyncio.create_task(self._worker(f"worker-{i}"))
            workers.append(worker)
        
        return workers
    
    async def stop(self):
        """큐 중지"""
        self.is_running = False
        batch_logger.info("task_queue_stopped", {})
    
    async def add_task(self, task: BatchTask) -> bool:
        """작업 추가"""
        async with self.queue_lock:
            if len(self.task_queue) >= self.max_queue_size:
                batch_logger.warning("task_queue_full", {
                    "queue_size": len(self.task_queue),
                    "max_size": self.max_queue_size
                })
                return False
            
            heapq.heappush(self.task_queue, task)
            batch_logger.info("task_added_to_queue", {
                "task_id": task.id,
                "task_type": task.task_type,
                "priority": task.priority.name,
                "queue_size": len(self.task_queue)
            })
            
        return True
    
    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """작업 상태 조회"""
        
        # 진행 중인 작업에서 찾기
        if task_id in self.active_tasks:
            return self.active_tasks[task_id].to_dict()
        
        # 완료된 작업에서 찾기
        if task_id in self.completed_tasks:
            return self.completed_tasks[task_id].to_dict()
        
        # 큐에서 찾기
        async with self.queue_lock:
            for task in self.task_queue:
                if task.id == task_id:
                    return task.to_dict()
        
        return None
    
    async def _worker(self, worker_name: str):
        """워커 함수"""
        batch_logger.info("worker_started", {"worker_name": worker_name})
        
        while self.is_running:
            try:
                # 큐에서 작업 가져오기
                task = await self._get_next_task()
                if task is None:
                    await asyncio.sleep(0.1)  # 잠시 대기
                    continue
                
                # 세마포어로 동시 실행 수 제한
                async with self.worker_semaphore:
                    await self._process_task(task, worker_name)
                    
            except Exception as e:
                batch_logger.error("worker_error", {
                    "worker_name": worker_name,
                    "error": str(e)
                })
                await asyncio.sleep(1)  # 에러 발생시 잠시 대기
        
        batch_logger.info("worker_stopped", {"worker_name": worker_name})
    
    async def _get_next_task(self) -> Optional[BatchTask]:
        """큐에서 다음 작업 가져오기"""
        async with self.queue_lock:
            if self.task_queue:
                return heapq.heappop(self.task_queue)
        return None
    
    async def _process_task(self, task: BatchTask, worker_name: str):
        """작업 처리"""
        task.status = TaskStatus.PROCESSING
        task.started_at = datetime.utcnow()
        self.active_tasks[task.id] = task
        
        batch_logger.info("task_processing_started", {
            "task_id": task.id,
            "task_type": task.task_type,
            "worker_name": worker_name
        })
        
        start_time = time.time()
        
        try:
            # 작업 타입에 따른 처리
            if task.task_type == "embedding_generation":
                await self._process_embedding_task(task)
            elif task.task_type == "file_processing":
                await self._process_file_task(task)
            else:
                raise ValueError(f"Unknown task type: {task.task_type}")
            
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()
            
            batch_logger.info("task_processing_completed", {
                "task_id": task.id,
                "task_type": task.task_type,
                "duration": time.time() - start_time,
                "worker_name": worker_name
            })
            
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.utcnow()
            task.retry_count += 1
            
            batch_logger.error("task_processing_failed", {
                "task_id": task.id,
                "task_type": task.task_type,
                "error": str(e),
                "retry_count": task.retry_count,
                "duration": time.time() - start_time,
                "worker_name": worker_name
            })
            
            # 재시도 로직
            if task.retry_count < task.max_retries:
                # 지수 백오프로 재시도
                delay = min(2 ** task.retry_count, 60)  # 최대 60초
                await asyncio.sleep(delay)
                
                task.status = TaskStatus.PENDING
                await self.add_task(task)
        
        finally:
            # 활성 작업에서 제거하고 완료된 작업에 추가
            if task.id in self.active_tasks:
                del self.active_tasks[task.id]
            
            # 완료된 작업 저장 (최대 1000개만 보관)
            self.completed_tasks[task.id] = task
            if len(self.completed_tasks) > 1000:
                # 가장 오래된 작업 제거
                oldest_task_id = min(
                    self.completed_tasks.keys(),
                    key=lambda x: self.completed_tasks[x].completed_at or datetime.min
                )
                del self.completed_tasks[oldest_task_id]
    
    async def _process_embedding_task(self, task: BatchTask):
        """임베딩 작업 처리"""
        # 실제 임베딩 생성 로직 구현
        # 이는 구체적인 임베딩 생성 함수와 연동되어야 함
        await asyncio.sleep(0.1)  # 플레이스홀더
        task.result = {"status": "processed", "type": "embedding"}
    
    async def _process_file_task(self, task: BatchTask):
        """파일 처리 작업"""
        # 실제 파일 처리 로직 구현
        await asyncio.sleep(0.1)  # 플레이스홀더
        task.result = {"status": "processed", "type": "file"}

class BatchProcessingManager:
    """배치 처리 관리자"""
    
    def __init__(self):
        self.embedding_processor = EmbeddingBatchProcessor()
        self.file_processor = FileBatchProcessor()
        self.task_queue = AsyncTaskQueue()
        self.is_initialized = False
    
    async def initialize(self):
        """매니저 초기화"""
        if not self.is_initialized:
            await self.task_queue.start()
            self.is_initialized = True
            batch_logger.info("batch_manager_initialized", {})
    
    async def shutdown(self):
        """매니저 종료"""
        if self.is_initialized:
            await self.task_queue.stop()
            self.is_initialized = False
            batch_logger.info("batch_manager_shutdown", {})
    
    async def submit_embedding_batch(
        self,
        texts: List[str],
        model: str,
        project_id: str,
        file_id: str,
        priority: TaskPriority = TaskPriority.NORMAL
    ) -> str:
        """임베딩 배치 작업 제출"""
        
        task = BatchTask(
            task_type="embedding_generation",
            data={
                "texts": texts,
                "model": model,
                "project_id": project_id,
                "file_id": file_id
            },
            priority=priority
        )
        
        success = await self.task_queue.add_task(task)
        if not success:
            raise RuntimeError("Failed to add task to queue (queue full)")
        
        return task.id
    
    async def submit_file_processing_batch(
        self,
        file_content: str,
        file_name: str,
        project_id: str,
        file_id: str,
        priority: TaskPriority = TaskPriority.NORMAL
    ) -> str:
        """파일 처리 배치 작업 제출"""
        
        task = BatchTask(
            task_type="file_processing",
            data={
                "file_content": file_content,
                "file_name": file_name,
                "project_id": project_id,
                "file_id": file_id
            },
            priority=priority
        )
        
        success = await self.task_queue.add_task(task)
        if not success:
            raise RuntimeError("Failed to add task to queue (queue full)")
        
        return task.id
    
    async def get_batch_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """배치 작업 상태 조회"""
        return await self.task_queue.get_task_status(task_id)
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """큐 통계 조회"""
        return {
            "queue_size": len(self.task_queue.task_queue),
            "active_tasks": len(self.task_queue.active_tasks),
            "completed_tasks": len(self.task_queue.completed_tasks),
            "max_workers": self.task_queue.max_workers,
            "is_running": self.task_queue.is_running
        }

# 전역 배치 처리 매니저
batch_manager = BatchProcessingManager() 