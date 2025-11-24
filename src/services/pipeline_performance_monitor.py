"""Pipeline Performance Monitor.

Phase 2 - Order Processing Pipeline Optimization
파이프라인 성능 모니터링 및 리포팅 시스템.
"""

import asyncio
import json
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Deque, Dict, List, Optional
from zoneinfo import ZoneInfo

try:
    import psutil
except ImportError:
    psutil = None

from ..utils.logger import get_logger
from .order_pipeline_optimizer import OrderPipelineOptimizer, PipelineMode

KST = ZoneInfo("Asia/Seoul")
logger = get_logger(__name__)


@dataclass
class PerformanceSnapshot:
    """성능 스냅샷."""

    timestamp: datetime
    throughput: float  # 초당 처리량
    average_latency: float  # 평균 지연시간 (초)
    success_rate: float  # 성공률
    queue_depth: int  # 큐 깊이
    active_workers: int  # 활성 워커 수
    batch_size: float  # 평균 배치 크기
    memory_usage_mb: float  # 메모리 사용량 (MB)
    cpu_usage_percent: float  # CPU 사용률 (%)


@dataclass
class AlertThresholds:
    """알림 임계값 설정."""

    min_throughput: float = 10.0  # 최소 초당 처리량
    max_latency: float = 5.0  # 최대 지연시간 (초)
    min_success_rate: float = 0.95  # 최소 성공률
    max_queue_depth: int = 1000  # 최대 큐 깊이
    max_memory_usage_mb: float = 1000.0  # 최대 메모리 사용량
    max_cpu_usage_percent: float = 80.0  # 최대 CPU 사용률


@dataclass
class PerformanceAlert:
    """성능 알림."""

    alert_id: str
    alert_type: str
    severity: str  # "info", "warning", "critical"
    message: str
    timestamp: datetime
    metric_name: str
    metric_value: float
    threshold_value: float
    resolved: bool = False
    resolved_at: Optional[datetime] = None


class PipelinePerformanceMonitor:
    """파이프라인 성능 모니터.

    Features:
    - 실시간 성능 모니터링
    - 임계값 기반 알림
    - 성능 추세 분석
    - 자동 최적화 제안
    - 리포트 생성
    """

    def __init__(
        self,
        pipeline: OrderPipelineOptimizer,
        thresholds: Optional[AlertThresholds] = None,
        snapshot_interval: float = 10.0,  # 스냅샷 간격 (초)
        history_size: int = 1000,  # 히스토리 크기
    ):
        """성능 모니터를 초기화합니다.

        Args:
            pipeline: 모니터링할 파이프라인
            thresholds: 알림 임계값
            snapshot_interval: 스냅샷 수집 간격
            history_size: 유지할 히스토리 크기
        """
        self.pipeline = pipeline
        self.thresholds = thresholds or AlertThresholds()
        self.snapshot_interval = snapshot_interval
        self.history_size = history_size

        # 성능 히스토리
        self.snapshots: Deque[PerformanceSnapshot] = deque(maxlen=history_size)
        self.alerts: List[PerformanceAlert] = []
        self.active_alerts: Dict[str, PerformanceAlert] = {}

        # 통계
        self.total_snapshots = 0
        self.total_alerts = 0
        self.optimization_suggestions: List[str] = []

        # 실행 상태
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None

    async def start(self):
        """모니터링을 시작합니다."""
        logger.info("파이프라인 성능 모니터링 시작")
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"모니터링 간격: {self.snapshot_interval}초")

    async def stop(self):
        """모니터링을 종료합니다."""
        logger.info("파이프라인 성능 모니터링 종료")
        self._running = False

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        # 최종 리포트 생성
        report = self.generate_report()
        logger.info(f"최종 성능 리포트:\n{json.dumps(report, indent=2, default=str)}")

    async def _monitor_loop(self):
        """모니터링 루프."""
        while self._running:
            try:
                await asyncio.sleep(self.snapshot_interval)
                snapshot = await self._collect_snapshot()
                if snapshot:
                    self.snapshots.append(snapshot)
                    self.total_snapshots += 1
                    await self._check_alerts(snapshot)
                    await self._analyze_performance()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"모니터링 오류: {e}", exc_info=True)

    async def _collect_snapshot(self) -> Optional[PerformanceSnapshot]:
        """성능 스냅샷을 수집합니다."""
        try:
            metrics = self.pipeline.get_metrics()

            # 메모리와 CPU 사용량 (시뮬레이션)
            if psutil:
                process = psutil.Process()
                memory_usage_mb = process.memory_info().rss / 1024 / 1024
                cpu_usage_percent = process.cpu_percent(interval=0.1)
            else:
                # psutil이 없으면 기본값 사용
                memory_usage_mb = 100.0
                cpu_usage_percent = 25.0

            # 파이프라인 메트릭 추출
            pipeline_metrics = metrics.get("pipeline", {})
            throughput = pipeline_metrics.get("throughput_per_second", 0.0)
            avg_latency = pipeline_metrics.get("average_processing_time", 0.0)
            success_rate = pipeline_metrics.get("success_rate", 0.0)

            # Worker Pool 메트릭
            worker_metrics = metrics.get("worker_pool", {})
            if worker_metrics:
                queue_depth = worker_metrics.get("queue_status", {}).get("current_size", 0)
                active_workers = worker_metrics.get("pool_status", {}).get("active_workers", 0)
            else:
                queue_depth = 0
                active_workers = 0

            # Batch Aggregator 메트릭
            batch_metrics = metrics.get("batch_aggregator", {})
            if batch_metrics:
                aggregator_metrics = batch_metrics.get("aggregator_metrics", {})
                avg_batch_size = aggregator_metrics.get("average_batch_size", 1.0)
            else:
                avg_batch_size = 1.0

            snapshot = PerformanceSnapshot(
                timestamp=datetime.now(tz=KST),
                throughput=throughput,
                average_latency=avg_latency,
                success_rate=success_rate,
                queue_depth=queue_depth,
                active_workers=active_workers,
                batch_size=avg_batch_size,
                memory_usage_mb=memory_usage_mb,
                cpu_usage_percent=cpu_usage_percent,
            )

            logger.debug(
                f"스냅샷 수집: 처리량={throughput:.2f}/s, "
                f"지연={avg_latency:.3f}s, 성공률={success_rate:.1%}"
            )

            return snapshot

        except Exception as e:
            logger.error(f"스냅샷 수집 오류: {e}", exc_info=True)
            return None

    async def _check_alerts(self, snapshot: PerformanceSnapshot):
        """알림 조건을 검사합니다."""
        alerts = []

        # 처리량 체크
        if snapshot.throughput < self.thresholds.min_throughput:
            alerts.append(
                self._create_alert(
                    "low_throughput",
                    "critical",
                    f"처리량이 임계값 미만: {snapshot.throughput:.2f}/s < {self.thresholds.min_throughput}/s",
                    "throughput",
                    snapshot.throughput,
                    self.thresholds.min_throughput,
                )
            )

        # 지연시간 체크
        if snapshot.average_latency > self.thresholds.max_latency:
            alerts.append(
                self._create_alert(
                    "high_latency",
                    "warning",
                    f"지연시간이 임계값 초과: {snapshot.average_latency:.2f}s > {self.thresholds.max_latency}s",
                    "latency",
                    snapshot.average_latency,
                    self.thresholds.max_latency,
                )
            )

        # 성공률 체크
        if snapshot.success_rate < self.thresholds.min_success_rate:
            alerts.append(
                self._create_alert(
                    "low_success_rate",
                    "critical",
                    f"성공률이 임계값 미만: {snapshot.success_rate:.1%} < {self.thresholds.min_success_rate:.1%}",
                    "success_rate",
                    snapshot.success_rate,
                    self.thresholds.min_success_rate,
                )
            )

        # 큐 깊이 체크
        if snapshot.queue_depth > self.thresholds.max_queue_depth:
            alerts.append(
                self._create_alert(
                    "high_queue_depth",
                    "warning",
                    f"큐 깊이가 임계값 초과: {snapshot.queue_depth} > {self.thresholds.max_queue_depth}",
                    "queue_depth",
                    snapshot.queue_depth,
                    self.thresholds.max_queue_depth,
                )
            )

        # 메모리 사용량 체크
        if snapshot.memory_usage_mb > self.thresholds.max_memory_usage_mb:
            alerts.append(
                self._create_alert(
                    "high_memory_usage",
                    "warning",
                    f"메모리 사용량 초과: {snapshot.memory_usage_mb:.1f}MB > {self.thresholds.max_memory_usage_mb}MB",
                    "memory_usage",
                    snapshot.memory_usage_mb,
                    self.thresholds.max_memory_usage_mb,
                )
            )

        # CPU 사용률 체크
        if snapshot.cpu_usage_percent > self.thresholds.max_cpu_usage_percent:
            alerts.append(
                self._create_alert(
                    "high_cpu_usage",
                    "warning",
                    f"CPU 사용률 초과: {snapshot.cpu_usage_percent:.1f}% > {self.thresholds.max_cpu_usage_percent}%",
                    "cpu_usage",
                    snapshot.cpu_usage_percent,
                    self.thresholds.max_cpu_usage_percent,
                )
            )

        # 알림 처리
        for alert in alerts:
            if alert.alert_type not in self.active_alerts:
                self.active_alerts[alert.alert_type] = alert
                self.alerts.append(alert)
                self.total_alerts += 1
                logger.warning(f"[{alert.severity}] {alert.message}")

        # 해결된 알림 체크
        resolved_types = []
        for alert_type, alert in self.active_alerts.items():
            if alert_type not in [a.alert_type for a in alerts]:
                alert.resolved = True
                alert.resolved_at = datetime.now(tz=KST)
                resolved_types.append(alert_type)
                logger.info(f"알림 해결: {alert_type}")

        for alert_type in resolved_types:
            del self.active_alerts[alert_type]

    def _create_alert(
        self,
        alert_type: str,
        severity: str,
        message: str,
        metric_name: str,
        metric_value: float,
        threshold_value: float,
    ) -> PerformanceAlert:
        """알림을 생성합니다."""
        from uuid import uuid4

        return PerformanceAlert(
            alert_id=str(uuid4()),
            alert_type=alert_type,
            severity=severity,
            message=message,
            timestamp=datetime.now(tz=KST),
            metric_name=metric_name,
            metric_value=metric_value,
            threshold_value=threshold_value,
        )

    async def _analyze_performance(self):
        """성능을 분석하고 최적화 제안을 생성합니다."""
        if len(self.snapshots) < 10:
            return

        # 최근 10개 스냅샷 분석
        recent_snapshots = list(self.snapshots)[-10:]
        avg_throughput = sum(s.throughput for s in recent_snapshots) / len(recent_snapshots)
        avg_latency = sum(s.average_latency for s in recent_snapshots) / len(recent_snapshots)
        avg_queue_depth = sum(s.queue_depth for s in recent_snapshots) / len(recent_snapshots)
        avg_batch_size = sum(s.batch_size for s in recent_snapshots) / len(recent_snapshots)

        suggestions = []

        # 모드 전환 제안
        current_mode = self.pipeline.config.mode

        if current_mode == PipelineMode.SEQUENTIAL and avg_throughput < 5:
            suggestions.append("성능이 낮습니다. PARALLEL 모드로 전환을 고려하세요.")

        if current_mode == PipelineMode.PARALLEL and avg_queue_depth > 100:
            suggestions.append("큐가 길어지고 있습니다. 워커 수를 늘리는 것을 고려하세요.")

        if current_mode != PipelineMode.BATCH and avg_batch_size < 2:
            suggestions.append("배치 크기가 작습니다. BATCH 모드 활성화를 고려하세요.")

        if avg_latency > 2 and current_mode != PipelineMode.OPTIMIZED:
            suggestions.append("지연시간이 높습니다. OPTIMIZED 모드로 전환을 고려하세요.")

        # 워커 스케일링 제안
        if self.pipeline.worker_pool:
            worker_metrics = self.pipeline.worker_pool.get_metrics()
            pool_status = worker_metrics.get("pool_status", {})
            total_workers = pool_status.get("total_workers", 0)
            active_workers = pool_status.get("active_workers", 0)

            if active_workers == total_workers and avg_queue_depth > 50:
                suggestions.append(f"모든 워커가 활성화됨. 최대 워커 수 증가를 고려하세요.")

            if active_workers < total_workers * 0.3 and total_workers > self.pipeline.config.min_workers:
                suggestions.append(f"워커 활용률이 낮습니다. 워커 수 감소를 고려하세요.")

        # 배치 설정 제안
        if self.pipeline.batch_aggregator:
            if avg_batch_size < self.pipeline.config.max_batch_size * 0.5:
                suggestions.append("배치 타임아웃을 늘려 더 큰 배치를 만드는 것을 고려하세요.")

        # 새로운 제안만 추가
        for suggestion in suggestions:
            if suggestion not in self.optimization_suggestions:
                self.optimization_suggestions.append(suggestion)
                logger.info(f"최적화 제안: {suggestion}")

    def get_current_performance(self) -> Optional[PerformanceSnapshot]:
        """현재 성능 스냅샷을 반환합니다."""
        if self.snapshots:
            return self.snapshots[-1]
        return None

    def get_performance_trend(self, minutes: int = 10) -> List[PerformanceSnapshot]:
        """지정된 시간 동안의 성능 추세를 반환합니다."""
        if not self.snapshots:
            return []

        cutoff_time = datetime.now(tz=KST) - timedelta(minutes=minutes)
        return [s for s in self.snapshots if s.timestamp >= cutoff_time]

    def get_active_alerts(self) -> List[PerformanceAlert]:
        """활성 알림을 반환합니다."""
        return list(self.active_alerts.values())

    def generate_report(self) -> Dict[str, Any]:
        """성능 리포트를 생성합니다."""
        if not self.snapshots:
            return {"error": "No performance data available"}

        # 전체 통계 계산
        all_snapshots = list(self.snapshots)
        avg_throughput = sum(s.throughput for s in all_snapshots) / len(all_snapshots)
        avg_latency = sum(s.average_latency for s in all_snapshots) / len(all_snapshots)
        avg_success_rate = sum(s.success_rate for s in all_snapshots) / len(all_snapshots)
        max_queue_depth = max(s.queue_depth for s in all_snapshots)
        max_memory = max(s.memory_usage_mb for s in all_snapshots)
        max_cpu = max(s.cpu_usage_percent for s in all_snapshots)

        # 최근 추세
        recent_trend = self.get_performance_trend(10)
        if recent_trend:
            recent_avg_throughput = sum(s.throughput for s in recent_trend) / len(recent_trend)
            recent_avg_latency = sum(s.average_latency for s in recent_trend) / len(recent_trend)
        else:
            recent_avg_throughput = 0
            recent_avg_latency = 0

        return {
            "summary": {
                "total_snapshots": self.total_snapshots,
                "total_alerts": self.total_alerts,
                "active_alerts": len(self.active_alerts),
                "monitoring_duration_minutes": (
                    (all_snapshots[-1].timestamp - all_snapshots[0].timestamp).total_seconds() / 60
                    if len(all_snapshots) > 1 else 0
                ),
            },
            "overall_performance": {
                "average_throughput": avg_throughput,
                "average_latency": avg_latency,
                "average_success_rate": avg_success_rate,
                "max_queue_depth": max_queue_depth,
                "max_memory_usage_mb": max_memory,
                "max_cpu_usage_percent": max_cpu,
            },
            "recent_trend": {
                "average_throughput": recent_avg_throughput,
                "average_latency": recent_avg_latency,
                "trend_duration_minutes": 10,
            },
            "active_alerts": [
                {
                    "type": alert.alert_type,
                    "severity": alert.severity,
                    "message": alert.message,
                    "timestamp": alert.timestamp.isoformat(),
                }
                for alert in self.active_alerts.values()
            ],
            "optimization_suggestions": self.optimization_suggestions[:5],  # Top 5 suggestions
            "current_configuration": {
                "mode": self.pipeline.config.mode.value,
                "min_workers": self.pipeline.config.min_workers,
                "max_workers": self.pipeline.config.max_workers,
                "batch_size": self.pipeline.config.max_batch_size,
                "batch_timeout": self.pipeline.config.batch_timeout,
            },
        }