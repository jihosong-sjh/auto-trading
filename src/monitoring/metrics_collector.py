"""Metrics Collector for Prometheus.

Phase 7: Performance Monitoring
모든 시스템 메트릭을 수집하고 Prometheus 형식으로 노출합니다.
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

try:
    from prometheus_client import (
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        Summary,
        generate_latest,
    )
except ImportError:
    # prometheus_client가 없으면 Mock 클래스 사용
    CollectorRegistry = None
    Counter = None
    Gauge = None
    Histogram = None
    Summary = None
    generate_latest = None

from ..utils.logger import get_logger

KST = ZoneInfo("Asia/Seoul")
logger = get_logger(__name__)


@dataclass
class MetricDefinition:
    """메트릭 정의."""

    name: str
    metric_type: str  # "counter", "gauge", "histogram", "summary"
    description: str
    labels: List[str] = None


class MetricsCollector:
    """통합 메트릭 수집기.

    Features:
    - API Rate Limiter 메트릭
    - Order Pipeline 메트릭
    - Risk Manager 메트릭
    - Data Pipeline 메트릭
    - Event Sourcing 메트릭
    - Strategy 메트릭
    - System 메트릭 (CPU, Memory, Disk)
    """

    def __init__(self, registry: Optional[Any] = None):
        """메트릭 수집기를 초기화합니다.

        Args:
            registry: Prometheus CollectorRegistry (None이면 기본 레지스트리 사용)
        """
        if CollectorRegistry is None:
            logger.warning("prometheus_client not installed. Metrics will be simulated.")
            self.registry = None
            self.enabled = False
        else:
            self.registry = registry or CollectorRegistry()
            self.enabled = True

        # 메트릭 딕셔너리
        self.counters: Dict[str, Any] = {}
        self.gauges: Dict[str, Any] = {}
        self.histograms: Dict[str, Any] = {}
        self.summaries: Dict[str, Any] = {}

        # 메트릭이 없을 때 시뮬레이션용 데이터
        self.simulated_metrics: Dict[str, float] = defaultdict(float)

        # 메트릭 정의 및 초기화
        self._initialize_metrics()

        logger.info(
            f"MetricsCollector initialized (enabled={self.enabled}, "
            f"counters={len(self.counters)}, gauges={len(self.gauges)}, "
            f"histograms={len(self.histograms)}, summaries={len(self.summaries)})"
        )

    def _initialize_metrics(self):
        """메트릭을 초기화합니다."""
        if not self.enabled:
            return

        # ============================================
        # API Rate Limiter Metrics
        # ============================================
        self.counters["api_requests_total"] = Counter(
            "api_requests_total",
            "Total API requests",
            ["api_type"],
            registry=self.registry,
        )

        self.gauges["api_queue_size"] = Gauge(
            "api_queue_size",
            "API request queue size",
            ["api_type"],
            registry=self.registry,
        )

        self.histograms["api_wait_time_seconds"] = Histogram(
            "api_wait_time_seconds",
            "API request wait time",
            ["api_type"],
            registry=self.registry,
        )

        # ============================================
        # Order Pipeline Metrics
        # ============================================
        self.gauges["pipeline_throughput_per_second"] = Gauge(
            "pipeline_throughput_per_second",
            "Order pipeline throughput (orders/sec)",
            registry=self.registry,
        )

        self.gauges["pipeline_average_latency_seconds"] = Gauge(
            "pipeline_average_latency_seconds",
            "Order pipeline average processing latency",
            registry=self.registry,
        )

        self.gauges["pipeline_success_rate"] = Gauge(
            "pipeline_success_rate",
            "Order pipeline success rate (0-1)",
            registry=self.registry,
        )

        self.gauges["pipeline_queue_depth"] = Gauge(
            "pipeline_queue_depth",
            "Order pipeline queue depth",
            registry=self.registry,
        )

        self.gauges["pipeline_active_workers"] = Gauge(
            "pipeline_active_workers",
            "Active worker count in pipeline",
            registry=self.registry,
        )

        self.gauges["pipeline_batch_size"] = Gauge(
            "pipeline_batch_size",
            "Average batch size in pipeline",
            registry=self.registry,
        )

        self.counters["pipeline_orders_processed_total"] = Counter(
            "pipeline_orders_processed_total",
            "Total orders processed by pipeline",
            ["status"],
            registry=self.registry,
        )

        # ============================================
        # Risk Manager Metrics
        # ============================================
        self.counters["risk_stop_loss_triggered_total"] = Counter(
            "risk_stop_loss_triggered_total",
            "Total stop-loss triggers",
            ["stock_code"],
            registry=self.registry,
        )

        self.counters["risk_take_profit_triggered_total"] = Counter(
            "risk_take_profit_triggered_total",
            "Total take-profit triggers",
            ["stock_code"],
            registry=self.registry,
        )

        self.gauges["risk_daily_loss_ratio"] = Gauge(
            "risk_daily_loss_ratio",
            "Daily loss ratio (0-1)",
            registry=self.registry,
        )

        self.gauges["risk_position_concentration"] = Gauge(
            "risk_position_concentration",
            "Position concentration ratio (0-1)",
            ["stock_code"],
            registry=self.registry,
        )

        # ============================================
        # Data Pipeline Metrics
        # ============================================
        self.counters["data_minute_bars_collected_total"] = Counter(
            "data_minute_bars_collected_total",
            "Total minute bars collected",
            ["stock_code"],
            registry=self.registry,
        )

        self.gauges["data_cache_hit_ratio"] = Gauge(
            "data_cache_hit_ratio",
            "Timeseries cache hit ratio (0-1)",
            registry=self.registry,
        )

        self.gauges["data_cache_size"] = Gauge(
            "data_cache_size",
            "Timeseries cache size (entries)",
            registry=self.registry,
        )

        # ============================================
        # Event Sourcing Metrics
        # ============================================
        self.counters["events_stored_total"] = Counter(
            "events_stored_total",
            "Total events stored",
            ["event_type"],
            registry=self.registry,
        )

        self.histograms["event_store_latency_seconds"] = Histogram(
            "event_store_latency_seconds",
            "Event store operation latency",
            ["operation"],
            registry=self.registry,
        )

        # ============================================
        # Strategy Metrics
        # ============================================
        self.counters["strategy_signals_total"] = Counter(
            "strategy_signals_total",
            "Total strategy signals generated",
            ["strategy_name", "signal_type"],
            registry=self.registry,
        )

        self.gauges["strategy_win_rate"] = Gauge(
            "strategy_win_rate",
            "Strategy win rate (0-1)",
            ["strategy_name"],
            registry=self.registry,
        )

        # ============================================
        # System Metrics
        # ============================================
        self.gauges["system_cpu_usage_percent"] = Gauge(
            "system_cpu_usage_percent",
            "System CPU usage percentage",
            registry=self.registry,
        )

        self.gauges["system_memory_usage_mb"] = Gauge(
            "system_memory_usage_mb",
            "System memory usage (MB)",
            registry=self.registry,
        )

        self.gauges["system_disk_usage_percent"] = Gauge(
            "system_disk_usage_percent",
            "System disk usage percentage",
            registry=self.registry,
        )

        logger.info("All Prometheus metrics initialized")

    # ============================================
    # API Rate Limiter Metrics
    # ============================================
    def record_api_request(self, api_type: str):
        """API 요청을 기록합니다."""
        if self.enabled:
            self.counters["api_requests_total"].labels(api_type=api_type).inc()
        else:
            self.simulated_metrics[f"api_requests_{api_type}"] += 1

    def set_api_queue_size(self, api_type: str, size: int):
        """API 큐 크기를 설정합니다."""
        if self.enabled:
            self.gauges["api_queue_size"].labels(api_type=api_type).set(size)
        else:
            self.simulated_metrics[f"api_queue_size_{api_type}"] = float(size)

    def record_api_wait_time(self, api_type: str, wait_time: float):
        """API 대기 시간을 기록합니다."""
        if self.enabled:
            self.histograms["api_wait_time_seconds"].labels(api_type=api_type).observe(
                wait_time
            )
        else:
            self.simulated_metrics[f"api_wait_time_{api_type}"] = wait_time

    # ============================================
    # Order Pipeline Metrics
    # ============================================
    def set_pipeline_throughput(self, throughput: float):
        """파이프라인 처리량을 설정합니다."""
        if self.enabled:
            self.gauges["pipeline_throughput_per_second"].set(throughput)
        else:
            self.simulated_metrics["pipeline_throughput"] = throughput

    def set_pipeline_latency(self, latency: float):
        """파이프라인 지연시간을 설정합니다."""
        if self.enabled:
            self.gauges["pipeline_average_latency_seconds"].set(latency)
        else:
            self.simulated_metrics["pipeline_latency"] = latency

    def set_pipeline_success_rate(self, success_rate: float):
        """파이프라인 성공률을 설정합니다."""
        if self.enabled:
            self.gauges["pipeline_success_rate"].set(success_rate)
        else:
            self.simulated_metrics["pipeline_success_rate"] = success_rate

    def set_pipeline_queue_depth(self, depth: int):
        """파이프라인 큐 깊이를 설정합니다."""
        if self.enabled:
            self.gauges["pipeline_queue_depth"].set(depth)
        else:
            self.simulated_metrics["pipeline_queue_depth"] = float(depth)

    def set_pipeline_active_workers(self, workers: int):
        """파이프라인 활성 워커 수를 설정합니다."""
        if self.enabled:
            self.gauges["pipeline_active_workers"].set(workers)
        else:
            self.simulated_metrics["pipeline_active_workers"] = float(workers)

    def set_pipeline_batch_size(self, batch_size: float):
        """파이프라인 배치 크기를 설정합니다."""
        if self.enabled:
            self.gauges["pipeline_batch_size"].set(batch_size)
        else:
            self.simulated_metrics["pipeline_batch_size"] = batch_size

    def record_pipeline_order(self, status: str):
        """파이프라인 주문 처리를 기록합니다."""
        if self.enabled:
            self.counters["pipeline_orders_processed_total"].labels(status=status).inc()
        else:
            self.simulated_metrics[f"pipeline_orders_{status}"] += 1

    # ============================================
    # Risk Manager Metrics
    # ============================================
    def record_stop_loss_trigger(self, stock_code: str):
        """손절 트리거를 기록합니다."""
        if self.enabled:
            self.counters["risk_stop_loss_triggered_total"].labels(
                stock_code=stock_code
            ).inc()
        else:
            self.simulated_metrics[f"stop_loss_{stock_code}"] += 1

    def record_take_profit_trigger(self, stock_code: str):
        """익절 트리거를 기록합니다."""
        if self.enabled:
            self.counters["risk_take_profit_triggered_total"].labels(
                stock_code=stock_code
            ).inc()
        else:
            self.simulated_metrics[f"take_profit_{stock_code}"] += 1

    def set_daily_loss_ratio(self, ratio: float):
        """일일 손실 비율을 설정합니다."""
        if self.enabled:
            self.gauges["risk_daily_loss_ratio"].set(ratio)
        else:
            self.simulated_metrics["daily_loss_ratio"] = ratio

    def set_position_concentration(self, stock_code: str, ratio: float):
        """포지션 집중도를 설정합니다."""
        if self.enabled:
            self.gauges["risk_position_concentration"].labels(
                stock_code=stock_code
            ).set(ratio)
        else:
            self.simulated_metrics[f"position_concentration_{stock_code}"] = ratio

    # ============================================
    # Data Pipeline Metrics
    # ============================================
    def record_minute_bar_collected(self, stock_code: str):
        """분봉 수집을 기록합니다."""
        if self.enabled:
            self.counters["data_minute_bars_collected_total"].labels(
                stock_code=stock_code
            ).inc()
        else:
            self.simulated_metrics[f"minute_bars_{stock_code}"] += 1

    def set_cache_hit_ratio(self, ratio: float):
        """캐시 히트율을 설정합니다."""
        if self.enabled:
            self.gauges["data_cache_hit_ratio"].set(ratio)
        else:
            self.simulated_metrics["cache_hit_ratio"] = ratio

    def set_cache_size(self, size: int):
        """캐시 크기를 설정합니다."""
        if self.enabled:
            self.gauges["data_cache_size"].set(size)
        else:
            self.simulated_metrics["cache_size"] = float(size)

    # ============================================
    # Event Sourcing Metrics
    # ============================================
    def record_event_stored(self, event_type: str):
        """이벤트 저장을 기록합니다."""
        if self.enabled:
            self.counters["events_stored_total"].labels(event_type=event_type).inc()
        else:
            self.simulated_metrics[f"events_stored_{event_type}"] += 1

    def record_event_store_latency(self, operation: str, latency: float):
        """이벤트 저장 지연시간을 기록합니다."""
        if self.enabled:
            self.histograms["event_store_latency_seconds"].labels(
                operation=operation
            ).observe(latency)
        else:
            self.simulated_metrics[f"event_latency_{operation}"] = latency

    # ============================================
    # Strategy Metrics
    # ============================================
    def record_strategy_signal(self, strategy_name: str, signal_type: str):
        """전략 신호를 기록합니다."""
        if self.enabled:
            self.counters["strategy_signals_total"].labels(
                strategy_name=strategy_name, signal_type=signal_type
            ).inc()
        else:
            self.simulated_metrics[f"strategy_{strategy_name}_{signal_type}"] += 1

    def set_strategy_win_rate(self, strategy_name: str, win_rate: float):
        """전략 승률을 설정합니다."""
        if self.enabled:
            self.gauges["strategy_win_rate"].labels(strategy_name=strategy_name).set(
                win_rate
            )
        else:
            self.simulated_metrics[f"win_rate_{strategy_name}"] = win_rate

    # ============================================
    # System Metrics
    # ============================================
    def set_system_cpu_usage(self, usage: float):
        """시스템 CPU 사용률을 설정합니다."""
        if self.enabled:
            self.gauges["system_cpu_usage_percent"].set(usage)
        else:
            self.simulated_metrics["system_cpu_usage"] = usage

    def set_system_memory_usage(self, usage_mb: float):
        """시스템 메모리 사용량을 설정합니다."""
        if self.enabled:
            self.gauges["system_memory_usage_mb"].set(usage_mb)
        else:
            self.simulated_metrics["system_memory_usage"] = usage_mb

    def set_system_disk_usage(self, usage: float):
        """시스템 디스크 사용률을 설정합니다."""
        if self.enabled:
            self.gauges["system_disk_usage_percent"].set(usage)
        else:
            self.simulated_metrics["system_disk_usage"] = usage

    # ============================================
    # System Metrics Collection
    # ============================================
    async def collect_system_metrics(self):
        """시스템 메트릭을 수집합니다."""
        try:
            import psutil

            # CPU 사용률
            cpu_percent = psutil.cpu_percent(interval=1)
            self.set_system_cpu_usage(cpu_percent)

            # 메모리 사용량
            memory = psutil.virtual_memory()
            memory_mb = memory.used / 1024 / 1024
            self.set_system_memory_usage(memory_mb)

            # 디스크 사용률
            disk = psutil.disk_usage("/")
            self.set_system_disk_usage(disk.percent)

            logger.debug(
                f"System metrics: CPU={cpu_percent:.1f}%, "
                f"Memory={memory_mb:.1f}MB, Disk={disk.percent:.1f}%"
            )

        except ImportError:
            logger.warning("psutil not installed. System metrics not available.")
        except Exception as e:
            logger.error(f"Failed to collect system metrics: {e}")

    # ============================================
    # Export Metrics
    # ============================================
    def export_metrics(self) -> bytes:
        """Prometheus 형식으로 메트릭을 내보냅니다."""
        if self.enabled and generate_latest:
            return generate_latest(self.registry)
        else:
            # 시뮬레이션된 메트릭을 텍스트로 반환
            lines = ["# Simulated Metrics\n"]
            for key, value in self.simulated_metrics.items():
                lines.append(f"{key} {value}\n")
            return "".join(lines).encode("utf-8")

    def get_metrics_summary(self) -> Dict[str, Any]:
        """메트릭 요약을 반환합니다."""
        if self.enabled:
            return {
                "enabled": True,
                "counters": len(self.counters),
                "gauges": len(self.gauges),
                "histograms": len(self.histograms),
                "summaries": len(self.summaries),
            }
        else:
            return {
                "enabled": False,
                "simulated_metrics_count": len(self.simulated_metrics),
                "simulated_metrics": dict(self.simulated_metrics),
            }
