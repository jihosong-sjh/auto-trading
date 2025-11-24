"""Order Processing Pipeline Optimization Example.

Phase 2 구현 테스트 및 성능 비교
"""

import asyncio
import time
from datetime import datetime
from decimal import Decimal
from typing import List
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.models import OrderStatus, OrderType, PriceType
from src.models.order import Order
from src.services.order_pipeline_optimizer import (
    OrderPipelineOptimizer,
    PipelineConfig,
    PipelineMode,
)
from src.services.pipeline_performance_monitor import PipelinePerformanceMonitor

KST = ZoneInfo("Asia/Seoul")


class MockOrderProcessor:
    """Mock Order Processor for testing."""

    def __init__(self, processing_delay: float = 0.1):
        self.processing_delay = processing_delay
        self.total_processed = 0
        self.successful = 0
        self.failed = 0

    async def execute_order(self, order: Order):
        """Simulate order execution with delay."""
        await asyncio.sleep(self.processing_delay)
        self.total_processed += 1

        # 90% 성공률
        import random

        success = random.random() < 0.9
        if success:
            self.successful += 1
            order.status = OrderStatus.FILLED
            order.filled_quantity = order.quantity
            order.filled_price = order.limit_price or Decimal("70000")
            order.filled_at = datetime.now(tz=KST)
            return True, None, order
        else:
            self.failed += 1
            order.status = OrderStatus.FAILED
            order.error_message = "Simulated failure"
            return False, "Simulated failure", order


def generate_orders(count: int) -> List[Order]:
    """Generate sample orders for testing."""
    orders = []
    stock_codes = ["005930", "000660", "005380", "035720", "051910"]  # 삼성전자, SK하이닉스, 현대차, 카카오, LG화학

    for i in range(count):
        stock_code = stock_codes[i % len(stock_codes)]
        order = Order(
            order_id=str(uuid4()),
            account_number="12345678",
            stock_code=stock_code,
            order_type=OrderType.BUY if i % 2 == 0 else OrderType.SELL,
            price_type=PriceType.LIMIT,
            quantity=100 + (i * 10),
            limit_price=Decimal("70000") + Decimal(i * 100),
            status=OrderStatus.PENDING,
        )
        orders.append(order)

    return orders


async def test_sequential_mode(order_processor, orders):
    """Test sequential processing mode."""
    print("\n[Sequential Mode Test]")
    print("=" * 50)

    config = PipelineConfig(
        mode=PipelineMode.SEQUENTIAL,
        enable_metrics=True,
    )

    pipeline = OrderPipelineOptimizer(
        order_processor=order_processor,
        config=config,
    )

    await pipeline.start()
    start_time = time.time()

    # Submit orders
    for order in orders:
        await pipeline.submit_order(order)

    # Wait for processing
    await asyncio.sleep(len(orders) * order_processor.processing_delay + 1)

    elapsed = time.time() - start_time
    metrics = pipeline.get_metrics()

    print(f"Total orders: {len(orders)}")
    print(f"Processing time: {elapsed:.2f} seconds")
    print(f"Throughput: {metrics['pipeline']['throughput_per_second']:.2f} orders/sec")
    print(f"Success rate: {metrics['pipeline']['success_rate']:.1%}")

    await pipeline.stop()
    return elapsed


async def test_parallel_mode(order_processor, orders):
    """Test parallel processing mode with Worker Pool."""
    print("\n[Parallel Mode Test - Worker Pool]")
    print("=" * 50)

    config = PipelineConfig(
        mode=PipelineMode.PARALLEL,
        min_workers=2,
        max_workers=5,
        enable_auto_scaling=True,
        enable_metrics=True,
    )

    pipeline = OrderPipelineOptimizer(
        order_processor=order_processor,
        config=config,
    )

    await pipeline.start()
    start_time = time.time()

    # Submit orders
    for order in orders:
        await pipeline.submit_order(order, priority=1)

    # Wait for processing
    await asyncio.sleep(5)

    elapsed = time.time() - start_time
    metrics = pipeline.get_metrics()

    print(f"Total orders: {len(orders)}")
    print(f"Processing time: {elapsed:.2f} seconds")
    print(f"Throughput: {metrics['pipeline']['throughput_per_second']:.2f} orders/sec")
    print(f"Success rate: {metrics['pipeline']['success_rate']:.1%}")

    # Worker Pool metrics
    if 'worker_pool' in metrics:
        worker_metrics = metrics['worker_pool']
        print(f"Active workers: {worker_metrics['pool_status']['active_workers']}/{worker_metrics['pool_status']['total_workers']}")
        print(f"Queue usage: {worker_metrics['queue_status']['usage_rate']:.1%}")

    await pipeline.stop()
    return elapsed


async def test_batch_mode(order_processor, orders):
    """Test batch processing mode."""
    print("\n[Batch Mode Test - Batch Aggregator]")
    print("=" * 50)

    config = PipelineConfig(
        mode=PipelineMode.BATCH,
        max_batch_size=5,
        batch_timeout=0.5,
        enable_smart_batching=True,
        enable_metrics=True,
    )

    pipeline = OrderPipelineOptimizer(
        order_processor=order_processor,
        config=config,
    )

    await pipeline.start()
    start_time = time.time()

    # Submit orders
    for order in orders:
        await pipeline.submit_order(order)

    # Wait for processing
    await asyncio.sleep(8)

    elapsed = time.time() - start_time
    metrics = pipeline.get_metrics()

    print(f"Total orders: {len(orders)}")
    print(f"Processing time: {elapsed:.2f} seconds")
    print(f"Throughput: {metrics['pipeline']['throughput_per_second']:.2f} orders/sec")
    print(f"Success rate: {metrics['pipeline']['success_rate']:.1%}")

    # Batch metrics
    if 'batch_aggregator' in metrics:
        batch_metrics = metrics['batch_aggregator']
        aggregator = batch_metrics.get('aggregator_metrics', {})
        print(f"Total batches: {aggregator.get('total_batches_created', 0)}")
        print(f"Average batch size: {aggregator.get('average_batch_size', 0):.1f}")

    await pipeline.stop()
    return elapsed


async def test_optimized_mode(order_processor, orders):
    """Test optimized mode combining Worker Pool and Batch Aggregator."""
    print("\n[Optimized Mode Test - Combined]")
    print("=" * 50)

    config = PipelineConfig(
        mode=PipelineMode.OPTIMIZED,
        min_workers=3,
        max_workers=8,
        max_batch_size=5,
        batch_timeout=0.3,
        enable_auto_scaling=True,
        enable_smart_batching=True,
        enable_circuit_breaker=True,
        enable_metrics=True,
    )

    pipeline = OrderPipelineOptimizer(
        order_processor=order_processor,
        config=config,
    )

    # Add performance monitor
    monitor = PipelinePerformanceMonitor(
        pipeline=pipeline,
        snapshot_interval=2.0,
    )

    await pipeline.start()
    await monitor.start()
    start_time = time.time()

    # Submit orders with mixed priorities
    for i, order in enumerate(orders):
        priority = 10 if i % 5 == 0 else 1  # Every 5th order is high priority
        await pipeline.submit_order(order, priority=priority)

    # Wait for processing
    await asyncio.sleep(5)

    elapsed = time.time() - start_time
    metrics = pipeline.get_metrics()
    report = monitor.generate_report()

    print(f"Total orders: {len(orders)}")
    print(f"Processing time: {elapsed:.2f} seconds")
    print(f"Throughput: {metrics['pipeline']['throughput_per_second']:.2f} orders/sec")
    print(f"Success rate: {metrics['pipeline']['success_rate']:.1%}")

    # Detailed metrics
    if 'worker_pool' in metrics:
        worker_metrics = metrics['worker_pool']
        print(f"Workers: {worker_metrics['pool_status']['active_workers']}/{worker_metrics['pool_status']['total_workers']}")

    if 'batch_aggregator' in metrics:
        batch_metrics = metrics['batch_aggregator']['aggregator_metrics']
        print(f"Batches created: {batch_metrics.get('total_batches_created', 0)}")

    # Performance insights
    if report.get('optimization_suggestions'):
        print("\nOptimization Suggestions:")
        for suggestion in report['optimization_suggestions'][:3]:
            print(f"  - {suggestion}")

    await monitor.stop()
    await pipeline.stop()
    return elapsed


async def main():
    """Main test runner."""
    print("\n" + "=" * 70)
    print("Order Processing Pipeline Optimization - Performance Test")
    print("Phase 2 Implementation Demo")
    print("=" * 70)

    # Test configuration
    order_count = 20
    processing_delay = 0.1  # 100ms per order

    print(f"\nTest Configuration:")
    print(f"  - Orders to process: {order_count}")
    print(f"  - Processing delay: {processing_delay * 1000:.0f}ms per order")
    print(f"  - Expected sequential time: ~{order_count * processing_delay:.1f} seconds")

    # Generate test orders
    orders = generate_orders(order_count)

    # Create mock processor
    processor = MockOrderProcessor(processing_delay=processing_delay)

    # Run tests
    results = {}

    # Test different modes
    # results['sequential'] = await test_sequential_mode(processor, orders.copy())

    processor = MockOrderProcessor(processing_delay=processing_delay)
    results['parallel'] = await test_parallel_mode(processor, orders.copy())

    processor = MockOrderProcessor(processing_delay=processing_delay)
    results['batch'] = await test_batch_mode(processor, orders.copy())

    processor = MockOrderProcessor(processing_delay=processing_delay)
    results['optimized'] = await test_optimized_mode(processor, orders.copy())

    # Performance comparison
    print("\n" + "=" * 70)
    print("Performance Comparison Summary")
    print("=" * 70)

    baseline = order_count * processing_delay  # Sequential theoretical time

    for mode, elapsed in results.items():
        speedup = baseline / elapsed if elapsed > 0 else 0
        print(f"{mode.capitalize():12} mode: {elapsed:6.2f}s (Speedup: {speedup:.1f}x)")

    print("\n[Conclusion]")
    fastest = min(results.items(), key=lambda x: x[1])
    print(f"Fastest mode: {fastest[0].capitalize()} ({fastest[1]:.2f}s)")
    print(f"Performance improvement: {(baseline / fastest[1] - 1) * 100:.0f}% faster than sequential")


if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())