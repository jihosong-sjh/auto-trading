"""Monitoring System Demo.

Phase 7: Performance Monitoring
Prometheus + Grafana + Auto-Tuning 시스템 데모.
"""

import asyncio
import random
from decimal import Decimal

from src.monitoring.metrics_collector import MetricsCollector
from src.monitoring.performance_tuner import PerformanceTuner
from src.monitoring.prometheus_exporter import PrometheusExporter
from src.services.order_pipeline_optimizer import (
    OrderPipelineOptimizer,
    PipelineConfig,
    PipelineMode,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def simulate_metrics(collector: MetricsCollector, duration: int = 60):
    """메트릭을 시뮬레이션합니다.

    Args:
        collector: 메트릭 수집기
        duration: 시뮬레이션 지속 시간 (초)
    """
    logger.info(f"Starting metrics simulation for {duration} seconds...")

    start_time = asyncio.get_event_loop().time()

    while asyncio.get_event_loop().time() - start_time < duration:
        # API Rate Limiter 메트릭
        collector.record_api_request("kiwoom")
        collector.set_api_queue_size("kiwoom", random.randint(0, 50))
        collector.record_api_wait_time("kiwoom", random.uniform(0.1, 2.0))

        # Order Pipeline 메트릭
        collector.set_pipeline_throughput(random.uniform(1.0, 20.0))
        collector.set_pipeline_latency(random.uniform(0.1, 3.0))
        collector.set_pipeline_success_rate(random.uniform(0.85, 1.0))
        collector.set_pipeline_queue_depth(random.randint(0, 150))
        collector.set_pipeline_active_workers(random.randint(1, 8))
        collector.set_pipeline_batch_size(random.uniform(1.0, 10.0))
        collector.record_pipeline_order("success")

        # Risk Manager 메트릭
        if random.random() < 0.01:  # 1% 확률로 트리거
            collector.record_stop_loss_trigger("005930")
        if random.random() < 0.02:  # 2% 확률로 트리거
            collector.record_take_profit_trigger("005930")

        collector.set_daily_loss_ratio(random.uniform(0.0, 0.025))
        collector.set_position_concentration("005930", random.uniform(0.1, 0.4))

        # Data Pipeline 메트릭
        collector.record_minute_bar_collected("005930")
        collector.set_cache_hit_ratio(random.uniform(0.7, 0.95))
        collector.set_cache_size(random.randint(100, 1000))

        # Event Sourcing 메트릭
        collector.record_event_stored("OrderPlaced")
        collector.record_event_store_latency("write", random.uniform(0.001, 0.01))

        # Strategy 메트릭
        if random.random() < 0.05:  # 5% 확률로 신호
            collector.record_strategy_signal("golden_cross", "buy")
        collector.set_strategy_win_rate("golden_cross", random.uniform(0.5, 0.7))

        # System 메트릭
        await collector.collect_system_metrics()

        # 1초 대기
        await asyncio.sleep(1)

    logger.info("Metrics simulation completed")


async def main():
    """메인 함수."""
    logger.info("=" * 60)
    logger.info("Phase 7: Performance Monitoring Demo")
    logger.info("=" * 60)

    # 1. 메트릭 수집기 초기화
    logger.info("\n[1] Initializing Metrics Collector...")
    collector = MetricsCollector()

    # 2. Prometheus Exporter 초기화
    logger.info("[2] Initializing Prometheus Exporter...")
    exporter = PrometheusExporter(collector, host="0.0.0.0", port=9090)

    # 3. Pipeline 초기화 (옵션)
    logger.info("[3] Initializing Order Pipeline...")
    config = PipelineConfig(
        mode=PipelineMode.SEQUENTIAL,
        min_workers=2,
        max_workers=8,
        max_batch_size=10,
        batch_timeout=1.0,
    )
    pipeline = OrderPipelineOptimizer(config)

    # 4. Auto-Tuner 초기화
    logger.info("[4] Initializing Performance Tuner...")
    tuner = PerformanceTuner(collector, pipeline, check_interval=10.0)

    # 5. 모든 서비스 시작
    logger.info("\n[5] Starting all services...")
    await exporter.start()
    await tuner.start()

    logger.info("\n" + "=" * 60)
    logger.info("Monitoring System Started!")
    logger.info("=" * 60)
    logger.info("Prometheus Exporter: http://localhost:9090/metrics")
    logger.info("Health Check: http://localhost:9090/health")
    logger.info("\nDocker Compose:")
    logger.info("  docker-compose -f docker-compose.monitoring.yml up -d")
    logger.info("\nGrafana Dashboard: http://localhost:3000")
    logger.info("  Username: admin")
    logger.info("  Password: admin")
    logger.info("=" * 60)

    # 6. 메트릭 시뮬레이션
    try:
        await simulate_metrics(collector, duration=120)

    except KeyboardInterrupt:
        logger.info("\nStopping monitoring system...")

    finally:
        # 7. 서비스 종료
        logger.info("\n[7] Stopping all services...")
        await tuner.stop()
        await exporter.stop()

        # 8. 최종 리포트
        logger.info("\n" + "=" * 60)
        logger.info("Tuning Summary")
        logger.info("=" * 60)
        tuning_summary = tuner.get_tuning_summary()
        logger.info(f"Total tuning actions: {tuning_summary['total_actions']}")

        if tuning_summary["recent_actions"]:
            logger.info("\nRecent tuning actions:")
            for action in tuning_summary["recent_actions"]:
                logger.info(
                    f"  - {action['timestamp']}: {action['rule']} -> {action['action']}"
                )
                logger.info(f"    Reason: {action['reason']}")

        logger.info("\n" + "=" * 60)
        logger.info("Demo Completed!")
        logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
