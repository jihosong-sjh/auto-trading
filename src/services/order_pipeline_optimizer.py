"""Optimized Order Processing Pipeline.

Phase 2 - Order Processing Pipeline Optimization
Worker Pool과 Batch Aggregator를 통합한 최적화된 주문 처리 파이프라인.
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Tuple
from uuid import uuid4
from zoneinfo import ZoneInfo

from ..models import OrderStatus, OrderType
from ..models.order import Order
from ..utils.logger import get_logger
from .order_batch_aggregator import (
    BatchingStrategy,
    OrderBatch,
    OrderBatchAggregator,
)
from .order_worker_pool import OrderProcessorProtocol, OrderWorkerPool

KST = ZoneInfo("Asia/Seoul")
logger = get_logger(__name__)


class PipelineMode(Enum):
    """파이프라인 동작 모드."""

    SEQUENTIAL = "sequential"  # 순차 처리 (기본)
    PARALLEL = "parallel"  # 병렬 처리 (Worker Pool)
    BATCH = "batch"  # 배치 처리 (Aggregator)
    OPTIMIZED = "optimized"  # 최적화 (Pool + Batch)


@dataclass
class PipelineConfig:
    """파이프라인 설정."""

    # 모드 설정
    mode: PipelineMode = PipelineMode.OPTIMIZED

    # Worker Pool 설정
    enable_worker_pool: bool = True
    min_workers: int = 2
    max_workers: int = 10
    enable_auto_scaling: bool = True

    # Batch Aggregator 설정
    enable_batch_aggregation: bool = True
    max_batch_size: int = 10
    batch_timeout: float = 1.0
    enable_smart_batching: bool = True

    # 성능 최적화 설정
    enable_priority_queue: bool = True
    enable_circuit_breaker: bool = True
    circuit_breaker_threshold: int = 5  # 연속 실패 임계값
    circuit_breaker_timeout: float = 60.0  # 회로 차단 시간 (초)

    # 모니터링 설정
    enable_metrics: bool = True
    metrics_interval: float = 30.0  # 메트릭 수집 간격 (초)


class CircuitBreakerState(Enum):
    """회로 차단기 상태."""

    CLOSED = "closed"  # 정상 동작
    OPEN = "open"  # 차단됨
    HALF_OPEN = "half_open"  # 복구 시도 중


class CircuitBreaker:
    """회로 차단기 패턴 구현."""

    def __init__(self, threshold: int = 5, timeout: float = 60.0):
        """회로 차단기를 초기화합니다.

        Args:
            threshold: 연속 실패 임계값
            timeout: 차단 시간 (초)
        """
        self.threshold = threshold
        self.timeout = timeout
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.circuit_open_time: Optional[datetime] = None

    def record_success(self):
        """성공을 기록합니다."""
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.state = CircuitBreakerState.CLOSED
            self.failure_count = 0
            logger.info("회로 차단기 복구: CLOSED 상태로 전환")

    def record_failure(self):
        """실패를 기록합니다."""
        self.failure_count += 1
        self.last_failure_time = datetime.now(tz=KST)

        if self.failure_count >= self.threshold:
            self.state = CircuitBreakerState.OPEN
            self.circuit_open_time = datetime.now(tz=KST)
            logger.warning(
                f"회로 차단기 작동: {self.failure_count}회 연속 실패로 OPEN 상태 전환"
            )

    def is_open(self) -> bool:
        """회로가 차단되었는지 확인합니다."""
        if self.state == CircuitBreakerState.CLOSED:
            return False

        if self.state == CircuitBreakerState.OPEN and self.circuit_open_time:
            elapsed = (datetime.now(tz=KST) - self.circuit_open_time).total_seconds()
            if elapsed > self.timeout:
                self.state = CircuitBreakerState.HALF_OPEN
                logger.info("회로 차단기 복구 시도: HALF_OPEN 상태로 전환")
                return False

        return self.state == CircuitBreakerState.OPEN

    def reset(self):
        """회로 차단기를 초기화합니다."""
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        self.circuit_open_time = None


class PipelineMetrics:
    """파이프라인 성능 지표."""

    def __init__(self):
        self.start_time = datetime.now(tz=KST)
        self.total_orders_received = 0
        self.total_orders_processed = 0
        self.total_batches_processed = 0
        self.total_successful = 0
        self.total_failed = 0
        self.total_processing_time = 0.0
        self.mode_usage: Dict[PipelineMode, int] = {mode: 0 for mode in PipelineMode}
        self.circuit_breaker_trips = 0
        self.last_metrics_time = datetime.now(tz=KST)

    def record_order(self, mode: PipelineMode):
        """주문 접수를 기록합니다."""
        self.total_orders_received += 1
        self.mode_usage[mode] += 1

    def record_completion(self, success: bool, processing_time: float, batch_size: int = 1):
        """처리 완료를 기록합니다."""
        self.total_orders_processed += batch_size
        self.total_processing_time += processing_time

        if batch_size > 1:
            self.total_batches_processed += 1

        if success:
            self.total_successful += batch_size
        else:
            self.total_failed += batch_size

    def record_circuit_breaker_trip(self):
        """회로 차단기 작동을 기록합니다."""
        self.circuit_breaker_trips += 1

    def get_metrics(self) -> Dict[str, Any]:
        """지표를 반환합니다."""
        uptime = (datetime.now(tz=KST) - self.start_time).total_seconds()
        throughput = self.total_orders_processed / uptime if uptime > 0 else 0
        avg_processing_time = (
            self.total_processing_time / self.total_orders_processed
            if self.total_orders_processed > 0
            else 0
        )

        return {
            "uptime_seconds": uptime,
            "total_orders_received": self.total_orders_received,
            "total_orders_processed": self.total_orders_processed,
            "total_batches_processed": self.total_batches_processed,
            "total_successful": self.total_successful,
            "total_failed": self.total_failed,
            "success_rate": (
                self.total_successful / self.total_orders_processed
                if self.total_orders_processed > 0
                else 0
            ),
            "throughput_per_second": throughput,
            "average_processing_time": avg_processing_time,
            "mode_usage": {mode.value: count for mode, count in self.mode_usage.items()},
            "circuit_breaker_trips": self.circuit_breaker_trips,
        }


class OrderPipelineOptimizer:
    """최적화된 주문 처리 파이프라인.

    Features:
    - 동적 모드 전환 (Sequential/Parallel/Batch/Optimized)
    - Worker Pool을 통한 병렬 처리
    - Batch Aggregator를 통한 배치 처리
    - Circuit Breaker 패턴
    - 실시간 성능 모니터링
    - 자동 최적화
    """

    def __init__(
        self,
        order_processor: OrderProcessorProtocol,
        config: Optional[PipelineConfig] = None,
    ):
        """파이프라인을 초기화합니다.

        Args:
            order_processor: 주문 처리기 (OrderExecutor)
            config: 파이프라인 설정
        """
        self.order_processor = order_processor
        self.config = config or PipelineConfig()

        # 컴포넌트 초기화
        self.worker_pool: Optional[OrderWorkerPool] = None
        self.batch_aggregator: Optional[OrderBatchAggregator] = None
        self.circuit_breaker: Optional[CircuitBreaker] = None

        # 메트릭스
        self.metrics = PipelineMetrics()

        # 실행 상태
        self._running = False
        self._metrics_task: Optional[asyncio.Task] = None

        # 주문 큐 (순차 처리용)
        self._sequential_queue: asyncio.Queue[Order] = asyncio.Queue()
        self._sequential_processor_task: Optional[asyncio.Task] = None

    async def start(self):
        """파이프라인을 시작합니다."""
        logger.info(f"주문 처리 파이프라인 시작: 모드={self.config.mode.value}")
        self._running = True

        # Worker Pool 초기화
        if self.config.enable_worker_pool and self.config.mode in [
            PipelineMode.PARALLEL,
            PipelineMode.OPTIMIZED,
        ]:
            self.worker_pool = OrderWorkerPool(
                order_processor=self.order_processor,
                min_workers=self.config.min_workers,
                max_workers=self.config.max_workers,
                enable_auto_scaling=self.config.enable_auto_scaling,
            )
            await self.worker_pool.start()

        # Batch Aggregator 초기화
        if self.config.enable_batch_aggregation and self.config.mode in [
            PipelineMode.BATCH,
            PipelineMode.OPTIMIZED,
        ]:
            strategy = BatchingStrategy(
                max_batch_size=self.config.max_batch_size,
                batch_timeout=self.config.batch_timeout,
                enable_smart_batching=self.config.enable_smart_batching,
            )
            self.batch_aggregator = OrderBatchAggregator(strategy=strategy)
            await self.batch_aggregator.start()

        # Circuit Breaker 초기화
        if self.config.enable_circuit_breaker:
            self.circuit_breaker = CircuitBreaker(
                threshold=self.config.circuit_breaker_threshold,
                timeout=self.config.circuit_breaker_timeout,
            )

        # 순차 처리 태스크 시작 (Sequential 모드용)
        if self.config.mode == PipelineMode.SEQUENTIAL:
            self._sequential_processor_task = asyncio.create_task(
                self._sequential_processor()
            )

        # 메트릭스 수집 태스크 시작
        if self.config.enable_metrics:
            self._metrics_task = asyncio.create_task(self._metrics_collector())

        logger.info("파이프라인 시작 완료")

    async def stop(self):
        """파이프라인을 종료합니다."""
        logger.info("파이프라인 종료 시작")
        self._running = False

        # 메트릭스 태스크 종료
        if self._metrics_task:
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass

        # 순차 처리 태스크 종료
        if self._sequential_processor_task:
            self._sequential_processor_task.cancel()
            try:
                await self._sequential_processor_task
            except asyncio.CancelledError:
                pass

        # Worker Pool 종료
        if self.worker_pool:
            await self.worker_pool.stop()

        # Batch Aggregator 종료
        if self.batch_aggregator:
            await self.batch_aggregator.stop()

        logger.info("파이프라인 종료 완료")

    async def submit_order(
        self, order: Order, priority: int = 0
    ) -> Tuple[bool, Optional[str]]:
        """주문을 파이프라인에 제출합니다.

        Args:
            order: 처리할 주문
            priority: 우선순위

        Returns:
            (성공 여부, 오류 메시지) 튜플
        """
        # Circuit Breaker 체크
        if self.circuit_breaker and self.circuit_breaker.is_open():
            error_msg = "Circuit breaker is open - service temporarily unavailable"
            logger.warning(f"주문 거부: {error_msg}")
            self.metrics.record_circuit_breaker_trip()
            return False, error_msg

        # 메트릭 기록
        self.metrics.record_order(self.config.mode)

        try:
            # 모드별 처리
            if self.config.mode == PipelineMode.SEQUENTIAL:
                return await self._submit_sequential(order)

            elif self.config.mode == PipelineMode.PARALLEL:
                return await self._submit_parallel(order, priority)

            elif self.config.mode == PipelineMode.BATCH:
                return await self._submit_batch(order)

            elif self.config.mode == PipelineMode.OPTIMIZED:
                return await self._submit_optimized(order, priority)

            else:
                return False, f"Unknown pipeline mode: {self.config.mode}"

        except Exception as e:
            error_msg = f"Pipeline error: {str(e)}"
            logger.error(error_msg, exc_info=True)

            # Circuit Breaker 실패 기록
            if self.circuit_breaker:
                self.circuit_breaker.record_failure()

            return False, error_msg

    async def _submit_sequential(self, order: Order) -> Tuple[bool, Optional[str]]:
        """순차 처리 모드로 주문을 제출합니다."""
        await self._sequential_queue.put(order)
        return True, None

    async def _submit_parallel(
        self, order: Order, priority: int
    ) -> Tuple[bool, Optional[str]]:
        """병렬 처리 모드로 주문을 제출합니다."""
        if not self.worker_pool:
            return False, "Worker pool not initialized"

        task_id = await self.worker_pool.submit_order(
            order,
            priority=priority,
            callback_on_success=self._on_order_success,
            callback_on_failure=self._on_order_failure,
        )

        logger.info(f"주문 병렬 처리 큐 제출: {order.order_id} (task: {task_id})")
        return True, None

    async def _submit_batch(self, order: Order) -> Tuple[bool, Optional[str]]:
        """배치 처리 모드로 주문을 제출합니다."""
        if not self.batch_aggregator:
            return False, "Batch aggregator not initialized"

        # 배치에 추가
        batch = await self.batch_aggregator.add_order(order)

        # 완성된 배치가 있으면 처리
        if batch:
            asyncio.create_task(self._process_batch(batch))

        return True, None

    async def _submit_optimized(
        self, order: Order, priority: int
    ) -> Tuple[bool, Optional[str]]:
        """최적화 모드로 주문을 제출합니다."""
        # 우선순위가 높은 주문은 즉시 병렬 처리
        if priority >= 5:
            return await self._submit_parallel(order, priority)

        # 일반 주문은 배치 처리
        if self.batch_aggregator:
            batch = await self.batch_aggregator.add_order(order)
            if batch:
                # 배치를 Worker Pool로 전송
                if self.worker_pool:
                    for batch_order in batch.orders:
                        await self.worker_pool.submit_order(
                            batch_order,
                            priority=1,  # 배치는 낮은 우선순위
                            callback_on_success=self._on_order_success,
                            callback_on_failure=self._on_order_failure,
                        )
                else:
                    # Worker Pool이 없으면 직접 처리
                    asyncio.create_task(self._process_batch(batch))

        return True, None

    async def _sequential_processor(self):
        """순차 처리 루프."""
        while self._running:
            try:
                order = await asyncio.wait_for(
                    self._sequential_queue.get(), timeout=1.0
                )

                start_time = time.time()
                success, error_msg, filled_order = await self.order_processor.execute_order(
                    order
                )
                processing_time = time.time() - start_time

                self.metrics.record_completion(success, processing_time)

                if success and self.circuit_breaker:
                    self.circuit_breaker.record_success()
                elif not success and self.circuit_breaker:
                    self.circuit_breaker.record_failure()

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Sequential processor error: {e}", exc_info=True)

    async def _process_batch(self, batch: OrderBatch):
        """배치를 처리합니다."""
        logger.info(
            f"배치 처리 시작: {batch.batch_id} "
            f"({batch.stock_code}, {len(batch.orders)}개 주문)"
        )

        start_time = time.time()
        successes = 0
        failures = 0

        for order in batch.orders:
            try:
                success, _, _ = await self.order_processor.execute_order(order)
                if success:
                    successes += 1
                else:
                    failures += 1
            except Exception as e:
                logger.error(f"배치 주문 처리 오류: {e}", exc_info=True)
                failures += 1

        processing_time = time.time() - start_time
        self.metrics.record_completion(
            successes > 0, processing_time, len(batch.orders)
        )

        logger.info(
            f"배치 처리 완료: {batch.batch_id} "
            f"(성공: {successes}, 실패: {failures}, "
            f"소요시간: {processing_time:.2f}초)"
        )

    def _on_order_success(self, order: Order):
        """주문 성공 콜백."""
        logger.info(f"주문 성공: {order.order_id}")
        if self.circuit_breaker:
            self.circuit_breaker.record_success()

    def _on_order_failure(self, order: Order, error_msg: str):
        """주문 실패 콜백."""
        logger.error(f"주문 실패: {order.order_id} - {error_msg}")
        if self.circuit_breaker:
            self.circuit_breaker.record_failure()

    async def _metrics_collector(self):
        """주기적으로 메트릭을 수집합니다."""
        while self._running:
            try:
                await asyncio.sleep(self.config.metrics_interval)
                metrics = self.get_metrics()
                logger.info(f"파이프라인 메트릭스: {metrics}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"메트릭 수집 오류: {e}", exc_info=True)

    def get_metrics(self) -> Dict[str, Any]:
        """파이프라인 메트릭을 반환합니다."""
        metrics = {
            "pipeline": self.metrics.get_metrics(),
            "mode": self.config.mode.value,
            "circuit_breaker": {
                "state": self.circuit_breaker.state.value if self.circuit_breaker else None,
                "failure_count": self.circuit_breaker.failure_count if self.circuit_breaker else 0,
            },
        }

        # Worker Pool 메트릭
        if self.worker_pool:
            metrics["worker_pool"] = self.worker_pool.get_metrics()

        # Batch Aggregator 메트릭
        if self.batch_aggregator:
            metrics["batch_aggregator"] = self.batch_aggregator.get_metrics()

        return metrics

    def switch_mode(self, new_mode: PipelineMode):
        """파이프라인 모드를 전환합니다."""
        logger.info(f"파이프라인 모드 전환: {self.config.mode.value} -> {new_mode.value}")
        self.config.mode = new_mode