"""Order Worker Pool for parallel order processing.

Phase 2 - Order Processing Pipeline Optimization
Worker Pool 패턴을 사용한 병렬 주문 처리 구현.
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Deque, Dict, List, Optional, Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from ..models import OrderStatus, OrderType
from ..models.order import Order
from ..utils.logger import get_logger

KST = ZoneInfo("Asia/Seoul")
logger = get_logger(__name__)


@dataclass
class WorkerMetrics:
    """워커 성능 지표."""

    worker_id: str
    total_processed: int = 0
    successful_orders: int = 0
    failed_orders: int = 0
    total_processing_time: float = 0.0
    average_processing_time: float = 0.0
    last_processed_at: Optional[datetime] = None

    def update(self, success: bool, processing_time: float):
        """지표를 업데이트합니다."""
        self.total_processed += 1
        if success:
            self.successful_orders += 1
        else:
            self.failed_orders += 1
        self.total_processing_time += processing_time
        self.average_processing_time = self.total_processing_time / self.total_processed
        self.last_processed_at = datetime.now(tz=KST)


@dataclass
class OrderTask:
    """주문 처리 작업."""

    order: Order
    priority: int = 0  # 높을수록 우선순위 높음
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=KST))
    task_id: str = field(default_factory=lambda: str(uuid4()))
    retry_count: int = 0
    max_retries: int = 3

    def __lt__(self, other):
        """우선순위 비교 (for PriorityQueue)."""
        return self.priority > other.priority


class OrderProcessorProtocol(Protocol):
    """주문 처리기 프로토콜."""

    async def execute_order(self, order: Order) -> tuple[bool, Optional[str], Optional[Order]]:
        """주문을 실행합니다."""
        ...


class OrderWorkerPool:
    """비동기 주문 처리 워커 풀.

    Features:
    - 병렬 주문 처리
    - 자동 재시도 메커니즘
    - 동적 워커 스케일링
    - 성능 모니터링
    - 우선순위 기반 처리
    """

    def __init__(
        self,
        order_processor: OrderProcessorProtocol,
        min_workers: int = 2,
        max_workers: int = 10,
        max_queue_size: int = 1000,
        enable_auto_scaling: bool = True,
        scale_up_threshold: float = 0.8,  # 큐 사용률 80% 이상 시 확장
        scale_down_threshold: float = 0.2,  # 큐 사용률 20% 이하 시 축소
    ):
        """워커 풀을 초기화합니다.

        Args:
            order_processor: 주문 처리기 (OrderExecutor)
            min_workers: 최소 워커 수
            max_workers: 최대 워커 수
            max_queue_size: 최대 큐 크기
            enable_auto_scaling: 자동 스케일링 활성화 여부
            scale_up_threshold: 확장 임계값
            scale_down_threshold: 축소 임계값
        """
        self.order_processor = order_processor
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size
        self.enable_auto_scaling = enable_auto_scaling
        self.scale_up_threshold = scale_up_threshold
        self.scale_down_threshold = scale_down_threshold

        # 작업 큐 (우선순위 기반)
        self._task_queue: asyncio.PriorityQueue[OrderTask] = asyncio.PriorityQueue(
            maxsize=max_queue_size
        )

        # 워커 관리
        self._workers: List[asyncio.Task] = []
        self._worker_metrics: Dict[str, WorkerMetrics] = {}
        self._active_workers = 0
        self._shutdown_event = asyncio.Event()

        # 성능 지표
        self._total_submitted = 0
        self._total_processed = 0
        self._total_successful = 0
        self._total_failed = 0

        # 콜백 함수
        self._success_callbacks: List[Callable[[Order], None]] = []
        self._failure_callbacks: List[Callable[[Order, str], None]] = []

    async def start(self):
        """워커 풀을 시작합니다."""
        logger.info(
            f"워커 풀 시작: 최소 {self.min_workers}개, 최대 {self.max_workers}개 워커"
        )

        # 초기 워커 생성
        for _ in range(self.min_workers):
            await self._add_worker()

        # 자동 스케일링 태스크 시작
        if self.enable_auto_scaling:
            asyncio.create_task(self._auto_scale_workers())

        logger.info(f"워커 풀 시작 완료: {len(self._workers)}개 워커 활성화")

    async def stop(self):
        """워커 풀을 종료합니다."""
        logger.info("워커 풀 종료 시작...")

        # 종료 신호 설정
        self._shutdown_event.set()

        # 모든 워커 종료 대기
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)

        # 남은 작업 처리
        remaining_tasks = []
        while not self._task_queue.empty():
            try:
                task = self._task_queue.get_nowait()
                remaining_tasks.append(task)
            except asyncio.QueueEmpty:
                break

        if remaining_tasks:
            logger.warning(f"종료 시 처리되지 않은 작업: {len(remaining_tasks)}개")

        logger.info("워커 풀 종료 완료")

    async def submit_order(
        self,
        order: Order,
        priority: int = 0,
        callback_on_success: Optional[Callable[[Order], None]] = None,
        callback_on_failure: Optional[Callable[[Order, str], None]] = None
    ) -> str:
        """주문을 처리 큐에 제출합니다.

        Args:
            order: 처리할 주문
            priority: 우선순위 (높을수록 먼저 처리)
            callback_on_success: 성공 시 콜백
            callback_on_failure: 실패 시 콜백

        Returns:
            작업 ID

        Raises:
            asyncio.QueueFull: 큐가 가득 찬 경우
        """
        task = OrderTask(order=order, priority=priority)

        # 콜백 등록
        if callback_on_success:
            self._success_callbacks.append(callback_on_success)
        if callback_on_failure:
            self._failure_callbacks.append(callback_on_failure)

        # 큐에 추가
        await self._task_queue.put(task)
        self._total_submitted += 1

        logger.info(
            f"주문 제출: {order.order_id} "
            f"(우선순위: {priority}, 큐 크기: {self._task_queue.qsize()})"
        )

        return task.task_id

    async def _add_worker(self) -> Optional[str]:
        """새 워커를 추가합니다."""
        if len(self._workers) >= self.max_workers:
            return None

        worker_id = f"worker_{uuid4().hex[:8]}"
        worker = asyncio.create_task(self._worker_loop(worker_id))
        self._workers.append(worker)
        self._worker_metrics[worker_id] = WorkerMetrics(worker_id=worker_id)

        logger.info(f"워커 추가: {worker_id} (총 {len(self._workers)}개)")
        return worker_id

    async def _remove_worker(self) -> bool:
        """워커를 제거합니다."""
        if len(self._workers) <= self.min_workers:
            return False

        # 가장 오래 유휴 상태인 워커 찾기
        oldest_idle_worker = None
        oldest_idle_time = datetime.now(tz=KST)

        for worker_id, metrics in self._worker_metrics.items():
            if metrics.last_processed_at and metrics.last_processed_at < oldest_idle_time:
                oldest_idle_time = metrics.last_processed_at
                oldest_idle_worker = worker_id

        if oldest_idle_worker:
            # 워커 제거 (실제 구현에서는 graceful shutdown 필요)
            logger.info(f"워커 제거: {oldest_idle_worker} (총 {len(self._workers) - 1}개)")
            return True

        return False

    async def _worker_loop(self, worker_id: str):
        """워커 실행 루프."""
        logger.info(f"워커 시작: {worker_id}")
        self._active_workers += 1

        try:
            while not self._shutdown_event.is_set():
                try:
                    # 작업 가져오기 (타임아웃 설정)
                    task = await asyncio.wait_for(
                        self._task_queue.get(),
                        timeout=1.0
                    )

                    # 처리 시작
                    start_time = time.time()
                    success, error_msg = await self._process_order(task, worker_id)
                    processing_time = time.time() - start_time

                    # 지표 업데이트
                    self._worker_metrics[worker_id].update(success, processing_time)
                    self._total_processed += 1

                    if success:
                        self._total_successful += 1
                    else:
                        self._total_failed += 1

                    logger.debug(
                        f"[{worker_id}] 처리 완료: {task.order.order_id} "
                        f"(소요시간: {processing_time:.2f}초)"
                    )

                except asyncio.TimeoutError:
                    # 큐가 비어있음 - 대기
                    continue
                except Exception as e:
                    logger.error(f"[{worker_id}] 워커 오류: {e}", exc_info=True)

        finally:
            self._active_workers -= 1
            logger.info(f"워커 종료: {worker_id}")

    async def _process_order(self, task: OrderTask, worker_id: str) -> tuple[bool, Optional[str]]:
        """주문을 처리합니다."""
        order = task.order

        try:
            order_type_str = order.order_type.value if hasattr(order.order_type, 'value') else order.order_type
            logger.info(
                f"[{worker_id}] 주문 처리 시작: {order.order_id} "
                f"({order_type_str} {order.stock_code} {order.quantity}주)"
            )

            # 주문 실행
            success, error_msg, filled_order = await self.order_processor.execute_order(order)

            if success and filled_order:
                # 성공 콜백 실행
                for callback in self._success_callbacks:
                    try:
                        callback(filled_order)
                    except Exception as e:
                        logger.error(f"성공 콜백 오류: {e}")

                return True, None
            else:
                # 재시도 확인
                if task.retry_count < task.max_retries:
                    task.retry_count += 1
                    logger.warning(
                        f"[{worker_id}] 주문 재시도 예약: {order.order_id} "
                        f"(시도 {task.retry_count}/{task.max_retries})"
                    )
                    await self._task_queue.put(task)
                    return False, error_msg

                # 실패 콜백 실행
                for callback in self._failure_callbacks:
                    try:
                        callback(order, error_msg or "Unknown error")
                    except Exception as e:
                        logger.error(f"실패 콜백 오류: {e}")

                return False, error_msg

        except Exception as e:
            error_msg = f"주문 처리 중 예외: {str(e)}"
            logger.error(f"[{worker_id}] {error_msg}", exc_info=True)
            return False, error_msg

    async def _auto_scale_workers(self):
        """워커 수를 자동으로 조절합니다."""
        logger.info("자동 스케일링 시작")

        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(5)  # 5초마다 체크

                # 큐 사용률 계산
                queue_usage = self._task_queue.qsize() / self.max_queue_size

                # 스케일 업
                if queue_usage > self.scale_up_threshold:
                    added = await self._add_worker()
                    if added:
                        logger.info(
                            f"자동 스케일 업: 큐 사용률 {queue_usage:.1%} "
                            f"(임계값: {self.scale_up_threshold:.1%})"
                        )

                # 스케일 다운
                elif queue_usage < self.scale_down_threshold:
                    removed = await self._remove_worker()
                    if removed:
                        logger.info(
                            f"자동 스케일 다운: 큐 사용률 {queue_usage:.1%} "
                            f"(임계값: {self.scale_down_threshold:.1%})"
                        )

            except Exception as e:
                logger.error(f"자동 스케일링 오류: {e}", exc_info=True)

    def get_metrics(self) -> Dict[str, Any]:
        """워커 풀 성능 지표를 반환합니다."""
        return {
            "pool_status": {
                "total_workers": len(self._workers),
                "active_workers": self._active_workers,
                "min_workers": self.min_workers,
                "max_workers": self.max_workers,
            },
            "queue_status": {
                "current_size": self._task_queue.qsize(),
                "max_size": self.max_queue_size,
                "usage_rate": self._task_queue.qsize() / self.max_queue_size,
            },
            "processing_stats": {
                "total_submitted": self._total_submitted,
                "total_processed": self._total_processed,
                "total_successful": self._total_successful,
                "total_failed": self._total_failed,
                "success_rate": (
                    self._total_successful / self._total_processed
                    if self._total_processed > 0 else 0
                ),
            },
            "worker_metrics": {
                worker_id: {
                    "total_processed": metrics.total_processed,
                    "successful_orders": metrics.successful_orders,
                    "failed_orders": metrics.failed_orders,
                    "average_processing_time": metrics.average_processing_time,
                    "last_processed_at": (
                        metrics.last_processed_at.isoformat()
                        if metrics.last_processed_at else None
                    ),
                }
                for worker_id, metrics in self._worker_metrics.items()
            }
        }