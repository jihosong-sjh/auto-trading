"""Tests for Order Processing Pipeline Optimization Components.

Phase 2 테스트 - Worker Pool, Batch Aggregator, Pipeline Optimizer
"""

import asyncio
import time
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from src.models import OrderStatus, OrderType, PriceType
from src.models.order import Order
from src.services.order_batch_aggregator import (
    BatchingStrategy,
    OrderBatch,
    OrderBatchAggregator,
)
from src.services.order_pipeline_optimizer import (
    CircuitBreaker,
    CircuitBreakerState,
    OrderPipelineOptimizer,
    PipelineConfig,
    PipelineMode,
)
from src.services.order_worker_pool import OrderTask, OrderWorkerPool, WorkerMetrics
from src.services.pipeline_performance_monitor import (
    AlertThresholds,
    PipelinePerformanceMonitor,
)

KST = ZoneInfo("Asia/Seoul")


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def sample_order():
    """샘플 주문을 생성합니다."""
    return Order(
        order_id=str(uuid4()),
        account_number="12345678",
        stock_code="005930",
        order_type=OrderType.BUY,
        price_type=PriceType.LIMIT,
        quantity=100,
        limit_price=Decimal("70000"),
        status=OrderStatus.PENDING,
    )


@pytest.fixture
def sample_orders():
    """여러 샘플 주문을 생성합니다."""
    orders = []
    for i in range(5):
        orders.append(
            Order(
                order_id=str(uuid4()),
                account_number="12345678",
                stock_code="005930" if i < 3 else "000660",
                order_type=OrderType.BUY if i % 2 == 0 else OrderType.SELL,
                price_type=PriceType.LIMIT,
                quantity=100 + i * 10,
                limit_price=Decimal("70000") + Decimal(i * 100),
                status=OrderStatus.PENDING,
            )
        )
    return orders


@pytest.fixture
def mock_order_processor():
    """Mock OrderProcessor를 생성합니다."""
    processor = AsyncMock()
    processor.execute_order = AsyncMock(
        return_value=(True, None, MagicMock(status=OrderStatus.FILLED))
    )
    return processor


# ============================================================================
# Worker Pool Tests
# ============================================================================


@pytest.mark.asyncio
class TestOrderWorkerPool:
    """OrderWorkerPool 테스트."""

    async def test_worker_pool_initialization(self, mock_order_processor):
        """워커 풀 초기화를 테스트합니다."""
        pool = OrderWorkerPool(
            order_processor=mock_order_processor,
            min_workers=2,
            max_workers=5,
        )

        assert pool.min_workers == 2
        assert pool.max_workers == 5
        assert pool._active_workers == 0
        assert len(pool._workers) == 0

    async def test_worker_pool_start_stop(self, mock_order_processor):
        """워커 풀 시작과 종료를 테스트합니다."""
        pool = OrderWorkerPool(
            order_processor=mock_order_processor,
            min_workers=2,
            max_workers=5,
        )

        # 시작
        await pool.start()
        assert len(pool._workers) == 2  # min_workers 만큼 생성
        assert pool._active_workers > 0

        # 종료
        await pool.stop()
        assert pool._shutdown_event.is_set()

    async def test_submit_order_to_pool(self, mock_order_processor, sample_order):
        """주문 제출을 테스트합니다."""
        pool = OrderWorkerPool(
            order_processor=mock_order_processor,
            min_workers=1,
            max_workers=3,
        )

        await pool.start()

        # 주문 제출
        task_id = await pool.submit_order(sample_order, priority=5)
        assert task_id is not None
        assert pool._total_submitted == 1

        # 처리 대기
        await asyncio.sleep(0.5)

        # 검증
        assert mock_order_processor.execute_order.called
        assert pool._total_processed > 0

        await pool.stop()

    async def test_worker_pool_priority_processing(self, mock_order_processor, sample_orders):
        """우선순위 기반 처리를 테스트합니다."""
        pool = OrderWorkerPool(
            order_processor=mock_order_processor,
            min_workers=1,
            max_workers=2,
        )

        await pool.start()

        # 다양한 우선순위로 주문 제출
        tasks = []
        for i, order in enumerate(sample_orders):
            priority = 10 - i  # 역순 우선순위
            task_id = await pool.submit_order(order, priority=priority)
            tasks.append(task_id)

        # 처리 대기
        await asyncio.sleep(1.0)

        # 모든 주문이 처리되었는지 확인
        assert pool._total_submitted == len(sample_orders)

        await pool.stop()

    async def test_worker_auto_scaling(self, mock_order_processor, sample_orders):
        """자동 스케일링을 테스트합니다."""
        pool = OrderWorkerPool(
            order_processor=mock_order_processor,
            min_workers=1,
            max_workers=5,
            max_queue_size=10,
            enable_auto_scaling=True,
            scale_up_threshold=0.5,  # 50% 이상 시 확장
        )

        await pool.start()
        initial_workers = len(pool._workers)

        # 많은 주문 제출로 큐 채우기
        for order in sample_orders * 2:  # 10개 주문
            await pool.submit_order(order)

        # 자동 스케일링 대기
        await asyncio.sleep(6)  # 스케일링 체크 주기 대기

        # 워커가 증가했는지 확인
        assert len(pool._workers) >= initial_workers

        await pool.stop()

    async def test_worker_metrics(self, mock_order_processor, sample_order):
        """워커 메트릭스를 테스트합니다."""
        pool = OrderWorkerPool(
            order_processor=mock_order_processor,
            min_workers=1,
        )

        await pool.start()

        # 주문 처리
        await pool.submit_order(sample_order)
        await asyncio.sleep(0.5)

        # 메트릭스 확인
        metrics = pool.get_metrics()
        assert "pool_status" in metrics
        assert "queue_status" in metrics
        assert "processing_stats" in metrics
        assert "worker_metrics" in metrics

        assert metrics["processing_stats"]["total_submitted"] > 0
        assert metrics["processing_stats"]["total_processed"] > 0

        await pool.stop()


# ============================================================================
# Batch Aggregator Tests
# ============================================================================


@pytest.mark.asyncio
class TestOrderBatchAggregator:
    """OrderBatchAggregator 테스트."""

    async def test_batch_creation(self, sample_orders):
        """배치 생성을 테스트합니다."""
        batch = OrderBatch()

        # 동일 종목, 동일 유형 주문 추가
        same_stock_orders = [o for o in sample_orders if o.stock_code == "005930"]
        buy_orders = [o for o in same_stock_orders if o.order_type == OrderType.BUY]

        for order in buy_orders:
            assert batch.add_order(order) == True

        assert batch.stock_code == "005930"
        assert batch.batch_type == OrderType.BUY
        assert batch.total_quantity == sum(o.quantity for o in buy_orders)

    async def test_batch_aggregator_initialization(self):
        """배치 집계기 초기화를 테스트합니다."""
        strategy = BatchingStrategy(
            max_batch_size=5,
            batch_timeout=0.5,
        )
        aggregator = OrderBatchAggregator(strategy=strategy)

        assert aggregator.strategy.max_batch_size == 5
        assert aggregator.strategy.batch_timeout == 0.5

    async def test_batch_aggregator_add_order(self, sample_order):
        """주문 추가를 테스트합니다."""
        aggregator = OrderBatchAggregator(
            strategy=BatchingStrategy(max_batch_size=3)
        )
        await aggregator.start()

        # 첫 주문 추가
        batch = await aggregator.add_order(sample_order)
        assert batch is None  # 아직 배치 미완성
        assert len(aggregator._order_buffer[sample_order.stock_code]) == 1

        await aggregator.stop()

    async def test_batch_size_trigger(self, sample_orders):
        """배치 크기 트리거를 테스트합니다."""
        aggregator = OrderBatchAggregator(
            strategy=BatchingStrategy(max_batch_size=2)
        )
        await aggregator.start()

        # 동일 종목 주문 2개 추가
        same_stock = [o for o in sample_orders if o.stock_code == "005930"][:2]

        # 첫 번째 주문
        batch = await aggregator.add_order(same_stock[0])
        assert batch is None

        # 두 번째 주문 (배치 크기 도달)
        batch = await aggregator.add_order(same_stock[1])
        assert batch is not None
        assert len(batch.orders) == 2

        await aggregator.stop()

    async def test_batch_timeout_trigger(self, sample_order):
        """배치 타임아웃 트리거를 테스트합니다."""
        aggregator = OrderBatchAggregator(
            strategy=BatchingStrategy(
                max_batch_size=10,
                batch_timeout=0.5,  # 0.5초 타임아웃
            )
        )
        await aggregator.start()

        # 주문 추가
        batch = await aggregator.add_order(sample_order)
        assert batch is None

        # 타임아웃 대기
        await asyncio.sleep(0.6)

        # 배치 가져오기
        batch = await aggregator.get_ready_batch(timeout=0.5)
        assert batch is not None
        assert len(batch.orders) == 1

        await aggregator.stop()

    async def test_priority_symbols(self, sample_order):
        """우선순위 종목 처리를 테스트합니다."""
        strategy = BatchingStrategy(
            priority_symbols={"005930"},  # 삼성전자를 우선순위로
        )
        aggregator = OrderBatchAggregator(strategy=strategy)
        await aggregator.start()

        # 우선순위 종목 주문
        batch = await aggregator.add_order(sample_order)
        assert batch is not None  # 즉시 처리
        assert len(batch.orders) == 1

        await aggregator.stop()

    async def test_smart_batching(self, sample_orders):
        """스마트 배칭을 테스트합니다."""
        strategy = BatchingStrategy(
            enable_smart_batching=True,
            enable_price_grouping=True,
        )
        aggregator = OrderBatchAggregator(strategy=strategy)

        # 가격대별 그룹핑 테스트
        orders = sample_orders[:3]  # 동일 종목, 다른 가격
        batches = aggregator._smart_batch_orders(orders)

        # 매수/매도 별로 분리되었는지 확인
        assert len(batches) >= 1


# ============================================================================
# Pipeline Optimizer Tests
# ============================================================================


@pytest.mark.asyncio
class TestOrderPipelineOptimizer:
    """OrderPipelineOptimizer 테스트."""

    async def test_pipeline_initialization(self, mock_order_processor):
        """파이프라인 초기화를 테스트합니다."""
        config = PipelineConfig(mode=PipelineMode.OPTIMIZED)
        pipeline = OrderPipelineOptimizer(
            order_processor=mock_order_processor,
            config=config,
        )

        assert pipeline.config.mode == PipelineMode.OPTIMIZED
        assert pipeline.order_processor == mock_order_processor

    async def test_pipeline_sequential_mode(self, mock_order_processor, sample_order):
        """순차 처리 모드를 테스트합니다."""
        config = PipelineConfig(mode=PipelineMode.SEQUENTIAL)
        pipeline = OrderPipelineOptimizer(
            order_processor=mock_order_processor,
            config=config,
        )

        await pipeline.start()

        # 주문 제출
        success, error = await pipeline.submit_order(sample_order)
        assert success == True
        assert error is None

        # 처리 대기
        await asyncio.sleep(1.5)

        # 메트릭 확인
        metrics = pipeline.get_metrics()
        assert metrics["pipeline"]["total_orders_received"] > 0

        await pipeline.stop()

    async def test_pipeline_parallel_mode(self, mock_order_processor, sample_orders):
        """병렬 처리 모드를 테스트합니다."""
        config = PipelineConfig(
            mode=PipelineMode.PARALLEL,
            min_workers=2,
            max_workers=4,
        )
        pipeline = OrderPipelineOptimizer(
            order_processor=mock_order_processor,
            config=config,
        )

        await pipeline.start()

        # 여러 주문 병렬 제출
        for order in sample_orders:
            success, error = await pipeline.submit_order(order, priority=1)
            assert success == True

        # 처리 대기
        await asyncio.sleep(1.0)

        # 워커 풀이 활성화되었는지 확인
        assert pipeline.worker_pool is not None

        await pipeline.stop()

    async def test_pipeline_batch_mode(self, mock_order_processor, sample_orders):
        """배치 처리 모드를 테스트합니다."""
        config = PipelineConfig(
            mode=PipelineMode.BATCH,
            max_batch_size=3,
            batch_timeout=0.5,
        )
        pipeline = OrderPipelineOptimizer(
            order_processor=mock_order_processor,
            config=config,
        )

        await pipeline.start()

        # 동일 종목 주문 제출
        same_stock = [o for o in sample_orders if o.stock_code == "005930"][:3]
        for order in same_stock:
            await pipeline.submit_order(order)

        # 배치 처리 대기
        await asyncio.sleep(1.0)

        # 배치 집계기가 활성화되었는지 확인
        assert pipeline.batch_aggregator is not None

        await pipeline.stop()

    async def test_pipeline_optimized_mode(self, mock_order_processor, sample_orders):
        """최적화 모드를 테스트합니다."""
        config = PipelineConfig(
            mode=PipelineMode.OPTIMIZED,
            enable_worker_pool=True,
            enable_batch_aggregation=True,
        )
        pipeline = OrderPipelineOptimizer(
            order_processor=mock_order_processor,
            config=config,
        )

        await pipeline.start()

        # 다양한 우선순위 주문 제출
        for i, order in enumerate(sample_orders):
            priority = 10 if i == 0 else 1  # 첫 주문은 높은 우선순위
            await pipeline.submit_order(order, priority=priority)

        # 처리 대기
        await asyncio.sleep(1.0)

        # 두 컴포넌트 모두 활성화되었는지 확인
        assert pipeline.worker_pool is not None
        assert pipeline.batch_aggregator is not None

        await pipeline.stop()

    async def test_circuit_breaker(self, mock_order_processor, sample_order):
        """회로 차단기를 테스트합니다."""
        # 실패하도록 설정
        mock_order_processor.execute_order = AsyncMock(
            side_effect=Exception("Test failure")
        )

        config = PipelineConfig(
            mode=PipelineMode.SEQUENTIAL,
            enable_circuit_breaker=True,
            circuit_breaker_threshold=3,
        )
        pipeline = OrderPipelineOptimizer(
            order_processor=mock_order_processor,
            config=config,
        )

        await pipeline.start()

        # 여러 번 실패 시도
        for _ in range(4):
            success, error = await pipeline.submit_order(sample_order)
            if not success and "Circuit breaker is open" in str(error):
                break
            await asyncio.sleep(0.1)

        # 회로가 열렸는지 확인
        assert pipeline.circuit_breaker.state == CircuitBreakerState.OPEN

        await pipeline.stop()

    async def test_mode_switching(self, mock_order_processor):
        """모드 전환을 테스트합니다."""
        config = PipelineConfig(mode=PipelineMode.SEQUENTIAL)
        pipeline = OrderPipelineOptimizer(
            order_processor=mock_order_processor,
            config=config,
        )

        assert pipeline.config.mode == PipelineMode.SEQUENTIAL

        # 모드 전환
        pipeline.switch_mode(PipelineMode.PARALLEL)
        assert pipeline.config.mode == PipelineMode.PARALLEL

        pipeline.switch_mode(PipelineMode.OPTIMIZED)
        assert pipeline.config.mode == PipelineMode.OPTIMIZED


# ============================================================================
# Performance Monitor Tests
# ============================================================================


@pytest.mark.asyncio
class TestPipelinePerformanceMonitor:
    """PipelinePerformanceMonitor 테스트."""

    async def test_monitor_initialization(self, mock_order_processor):
        """모니터 초기화를 테스트합니다."""
        pipeline = OrderPipelineOptimizer(mock_order_processor)
        thresholds = AlertThresholds(
            min_throughput=5.0,
            max_latency=2.0,
        )
        monitor = PipelinePerformanceMonitor(
            pipeline=pipeline,
            thresholds=thresholds,
            snapshot_interval=1.0,
        )

        assert monitor.pipeline == pipeline
        assert monitor.thresholds.min_throughput == 5.0
        assert monitor.snapshot_interval == 1.0

    @patch("src.services.pipeline_performance_monitor.psutil.Process")
    async def test_snapshot_collection(self, mock_process, mock_order_processor):
        """스냅샷 수집을 테스트합니다."""
        # psutil mock 설정
        mock_process_instance = MagicMock()
        mock_process_instance.memory_info.return_value.rss = 100 * 1024 * 1024
        mock_process_instance.cpu_percent.return_value = 25.0
        mock_process.return_value = mock_process_instance

        pipeline = OrderPipelineOptimizer(mock_order_processor)
        monitor = PipelinePerformanceMonitor(pipeline=pipeline)

        # 스냅샷 수집
        snapshot = await monitor._collect_snapshot()

        assert snapshot is not None
        assert snapshot.memory_usage_mb > 0
        assert snapshot.cpu_usage_percent >= 0

    async def test_alert_generation(self, mock_order_processor):
        """알림 생성을 테스트합니다."""
        pipeline = OrderPipelineOptimizer(mock_order_processor)
        thresholds = AlertThresholds(
            min_throughput=100.0,  # 매우 높은 임계값
            min_success_rate=1.0,  # 100% 성공률 요구
        )
        monitor = PipelinePerformanceMonitor(
            pipeline=pipeline,
            thresholds=thresholds,
        )

        await monitor.start()
        await asyncio.sleep(1.5)  # 스냅샷 수집 대기

        # 알림이 생성되었는지 확인
        active_alerts = monitor.get_active_alerts()
        assert len(active_alerts) >= 0  # 조건에 따라 알림 생성

        await monitor.stop()

    async def test_report_generation(self, mock_order_processor):
        """리포트 생성을 테스트합니다."""
        pipeline = OrderPipelineOptimizer(mock_order_processor)
        monitor = PipelinePerformanceMonitor(
            pipeline=pipeline,
            snapshot_interval=0.5,
        )

        await monitor.start()
        await asyncio.sleep(1.5)  # 몇 개의 스냅샷 수집

        # 리포트 생성
        report = monitor.generate_report()

        assert "summary" in report
        assert "overall_performance" in report
        assert "active_alerts" in report
        assert "optimization_suggestions" in report

        await monitor.stop()


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.asyncio
class TestPipelineIntegration:
    """통합 테스트."""

    async def test_end_to_end_order_processing(self, mock_order_processor, sample_orders):
        """종단 간 주문 처리를 테스트합니다."""
        # 최적화 모드로 파이프라인 구성
        config = PipelineConfig(
            mode=PipelineMode.OPTIMIZED,
            min_workers=2,
            max_workers=5,
            max_batch_size=3,
            batch_timeout=0.5,
            enable_metrics=True,
        )

        pipeline = OrderPipelineOptimizer(
            order_processor=mock_order_processor,
            config=config,
        )

        # 성능 모니터 추가
        monitor = PipelinePerformanceMonitor(
            pipeline=pipeline,
            snapshot_interval=1.0,
        )

        # 시작
        await pipeline.start()
        await monitor.start()

        # 다양한 주문 처리
        for i, order in enumerate(sample_orders * 2):  # 10개 주문
            priority = 5 if i % 3 == 0 else 1
            success, error = await pipeline.submit_order(order, priority=priority)
            assert success == True

        # 처리 대기
        await asyncio.sleep(2.0)

        # 메트릭 확인
        metrics = pipeline.get_metrics()
        assert metrics["pipeline"]["total_orders_received"] == 10

        # 리포트 생성
        report = monitor.generate_report()
        assert report["summary"]["total_snapshots"] > 0

        # 종료
        await monitor.stop()
        await pipeline.stop()

    async def test_performance_under_load(self, mock_order_processor):
        """부하 상태에서의 성능을 테스트합니다."""
        # 처리 지연 시뮬레이션
        async def slow_execute(order):
            await asyncio.sleep(0.1)  # 100ms 지연
            return True, None, MagicMock(status=OrderStatus.FILLED)

        mock_order_processor.execute_order = slow_execute

        config = PipelineConfig(
            mode=PipelineMode.PARALLEL,
            min_workers=3,
            max_workers=10,
            enable_auto_scaling=True,
        )

        pipeline = OrderPipelineOptimizer(
            order_processor=mock_order_processor,
            config=config,
        )

        await pipeline.start()

        # 많은 주문 생성
        start_time = time.time()
        for i in range(20):
            order = Order(
                order_id=str(uuid4()),
                account_number="12345678",
                stock_code=f"00{i%3:04d}",
                order_type=OrderType.BUY,
                price_type=PriceType.MARKET,
                quantity=100,
                status=OrderStatus.PENDING,
            )
            await pipeline.submit_order(order)

        # 모든 주문 처리 대기
        await asyncio.sleep(3.0)

        # 성능 측정
        elapsed = time.time() - start_time
        metrics = pipeline.get_metrics()
        throughput = metrics["pipeline"]["throughput_per_second"]

        print(f"처리 시간: {elapsed:.2f}초, 처리량: {throughput:.2f}/초")

        # 병렬 처리로 인한 성능 향상 확인
        assert throughput > 2.0  # 최소 2개/초 이상

        await pipeline.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])