"""Auto Performance Tuner.

Phase 7: Performance Monitoring
성능 메트릭을 분석하여 자동으로 시스템을 튜닝합니다.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from ..services.order_pipeline_optimizer import OrderPipelineOptimizer, PipelineMode
from ..utils.logger import get_logger
from .metrics_collector import MetricsCollector

KST = ZoneInfo("Asia/Seoul")
logger = get_logger(__name__)


@dataclass
class TuningRule:
    """튜닝 규칙."""

    name: str
    condition: str  # 조건 설명
    action: str  # 액션 설명
    cooldown_seconds: int = 60  # 재실행 쿨다운 (초)
    last_executed: Optional[datetime] = None


@dataclass
class TuningAction:
    """튜닝 액션."""

    timestamp: datetime
    rule_name: str
    action: str
    before_config: Dict[str, Any]
    after_config: Dict[str, Any]
    reason: str


class PerformanceTuner:
    """자동 성능 튜닝 시스템.

    Features:
    - 실시간 메트릭 분석
    - 규칙 기반 자동 튜닝
    - Pipeline 모드 자동 전환
    - Worker Pool 자동 스케일링
    - Batch 크기 자동 조정
    - 튜닝 히스토리 추적
    """

    def __init__(
        self,
        metrics_collector: MetricsCollector,
        pipeline: Optional[OrderPipelineOptimizer] = None,
        check_interval: float = 30.0,  # 체크 간격 (초)
    ):
        """성능 튜너를 초기화합니다.

        Args:
            metrics_collector: 메트릭 수집기
            pipeline: 주문 파이프라인 (옵션)
            check_interval: 체크 간격 (초)
        """
        self.metrics_collector = metrics_collector
        self.pipeline = pipeline
        self.check_interval = check_interval

        # 튜닝 규칙
        self.rules: List[TuningRule] = self._initialize_rules()

        # 튜닝 히스토리
        self.tuning_history: List[TuningAction] = []

        # 실행 상태
        self._running = False
        self._tuner_task: Optional[asyncio.Task] = None

        logger.info(
            f"PerformanceTuner initialized (rules={len(self.rules)}, "
            f"check_interval={check_interval}s)"
        )

    def _initialize_rules(self) -> List[TuningRule]:
        """튜닝 규칙을 초기화합니다."""
        return [
            TuningRule(
                name="low_throughput_to_parallel",
                condition="처리량 < 5 orders/sec AND 모드 = SEQUENTIAL",
                action="PARALLEL 모드로 전환",
                cooldown_seconds=120,
            ),
            TuningRule(
                name="high_queue_to_batch",
                condition="큐 깊이 > 100 AND 모드 != BATCH",
                action="BATCH 모드로 전환",
                cooldown_seconds=120,
            ),
            TuningRule(
                name="high_latency_to_optimized",
                condition="평균 지연시간 > 2초 AND 모드 != OPTIMIZED",
                action="OPTIMIZED 모드로 전환",
                cooldown_seconds=120,
            ),
            TuningRule(
                name="scale_up_workers",
                condition="큐 깊이 > 50 AND 활성 워커 = 최대 워커",
                action="최대 워커 수 증가",
                cooldown_seconds=180,
            ),
            TuningRule(
                name="scale_down_workers",
                condition="큐 깊이 < 10 AND 활성 워커 < 최대 워커 * 0.3",
                action="최대 워커 수 감소",
                cooldown_seconds=180,
            ),
            TuningRule(
                name="increase_batch_size",
                condition="배치 크기 < 최대 배치 크기 * 0.5",
                action="배치 타임아웃 증가",
                cooldown_seconds=90,
            ),
        ]

    async def start(self):
        """자동 튜닝을 시작합니다."""
        logger.info("자동 성능 튜닝 시작")
        self._running = True
        self._tuner_task = asyncio.create_task(self._tuning_loop())

    async def stop(self):
        """자동 튜닝을 종료합니다."""
        logger.info("자동 성능 튜닝 종료")
        self._running = False

        if self._tuner_task:
            self._tuner_task.cancel()
            try:
                await self._tuner_task
            except asyncio.CancelledError:
                pass

        # 튜닝 히스토리 출력
        logger.info(
            f"튜닝 히스토리: {len(self.tuning_history)}개 액션 실행됨"
        )
        for action in self.tuning_history[-5:]:  # 최근 5개
            logger.info(
                f"  - {action.timestamp.strftime('%H:%M:%S')}: "
                f"{action.rule_name} -> {action.action}"
            )

    async def _tuning_loop(self):
        """튜닝 루프."""
        while self._running:
            try:
                await asyncio.sleep(self.check_interval)
                await self._check_and_tune()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"튜닝 체크 오류: {e}", exc_info=True)

    async def _check_and_tune(self):
        """메트릭을 체크하고 필요시 튜닝합니다."""
        if not self.pipeline:
            logger.debug("Pipeline not configured. Skipping tuning.")
            return

        # 현재 메트릭 가져오기
        metrics_summary = self.metrics_collector.get_metrics_summary()
        simulated = metrics_summary.get("simulated_metrics", {})

        # 파이프라인 메트릭
        throughput = simulated.get("pipeline_throughput", 0.0)
        latency = simulated.get("pipeline_latency", 0.0)
        queue_depth = int(simulated.get("pipeline_queue_depth", 0.0))
        active_workers = int(simulated.get("pipeline_active_workers", 0.0))
        batch_size = simulated.get("pipeline_batch_size", 1.0)

        # 현재 설정
        current_mode = self.pipeline.config.mode
        max_workers = self.pipeline.config.max_workers
        max_batch_size = self.pipeline.config.max_batch_size
        batch_timeout = self.pipeline.config.batch_timeout

        logger.debug(
            f"Tuning check: throughput={throughput:.2f}/s, latency={latency:.3f}s, "
            f"queue={queue_depth}, mode={current_mode.value}"
        )

        # 규칙 체크 및 실행
        for rule in self.rules:
            # 쿨다운 체크
            if rule.last_executed:
                elapsed = (datetime.now(tz=KST) - rule.last_executed).total_seconds()
                if elapsed < rule.cooldown_seconds:
                    continue

            # 규칙별 조건 체크
            should_execute = False
            action_description = ""

            if rule.name == "low_throughput_to_parallel":
                if throughput < 5 and current_mode == PipelineMode.SEQUENTIAL:
                    should_execute = True
                    action_description = f"처리량 낮음 ({throughput:.2f}/s) -> PARALLEL 모드 전환"

            elif rule.name == "high_queue_to_batch":
                if queue_depth > 100 and current_mode != PipelineMode.BATCH:
                    should_execute = True
                    action_description = f"큐 깊이 높음 ({queue_depth}) -> BATCH 모드 전환"

            elif rule.name == "high_latency_to_optimized":
                if latency > 2.0 and current_mode != PipelineMode.OPTIMIZED:
                    should_execute = True
                    action_description = f"지연시간 높음 ({latency:.2f}s) -> OPTIMIZED 모드 전환"

            elif rule.name == "scale_up_workers":
                if queue_depth > 50 and active_workers == max_workers and max_workers < 20:
                    should_execute = True
                    action_description = f"워커 부족 (queue={queue_depth}) -> 최대 워커 수 증가"

            elif rule.name == "scale_down_workers":
                if queue_depth < 10 and active_workers < max_workers * 0.3 and max_workers > 2:
                    should_execute = True
                    action_description = f"워커 활용률 낮음 -> 최대 워커 수 감소"

            elif rule.name == "increase_batch_size":
                if batch_size < max_batch_size * 0.5 and batch_timeout < 2.0:
                    should_execute = True
                    action_description = f"배치 크기 작음 ({batch_size:.1f}) -> 배치 타임아웃 증가"

            # 액션 실행
            if should_execute:
                await self._execute_tuning_action(rule, action_description)

    async def _execute_tuning_action(self, rule: TuningRule, reason: str):
        """튜닝 액션을 실행합니다."""
        try:
            # 현재 설정 저장
            before_config = {
                "mode": self.pipeline.config.mode.value,
                "max_workers": self.pipeline.config.max_workers,
                "max_batch_size": self.pipeline.config.max_batch_size,
                "batch_timeout": self.pipeline.config.batch_timeout,
            }

            # 규칙별 액션 실행
            if rule.name == "low_throughput_to_parallel":
                self.pipeline.config.mode = PipelineMode.PARALLEL
                logger.info(f"[AUTO-TUNE] {reason}")

            elif rule.name == "high_queue_to_batch":
                self.pipeline.config.mode = PipelineMode.BATCH
                logger.info(f"[AUTO-TUNE] {reason}")

            elif rule.name == "high_latency_to_optimized":
                self.pipeline.config.mode = PipelineMode.OPTIMIZED
                logger.info(f"[AUTO-TUNE] {reason}")

            elif rule.name == "scale_up_workers":
                self.pipeline.config.max_workers = min(
                    self.pipeline.config.max_workers + 2, 20
                )
                logger.info(f"[AUTO-TUNE] {reason} -> max_workers={self.pipeline.config.max_workers}")

            elif rule.name == "scale_down_workers":
                self.pipeline.config.max_workers = max(
                    self.pipeline.config.max_workers - 1, 2
                )
                logger.info(f"[AUTO-TUNE] {reason} -> max_workers={self.pipeline.config.max_workers}")

            elif rule.name == "increase_batch_size":
                self.pipeline.config.batch_timeout = min(
                    self.pipeline.config.batch_timeout + 0.5, 5.0
                )
                logger.info(
                    f"[AUTO-TUNE] {reason} -> batch_timeout={self.pipeline.config.batch_timeout}s"
                )

            # 변경 후 설정
            after_config = {
                "mode": self.pipeline.config.mode.value,
                "max_workers": self.pipeline.config.max_workers,
                "max_batch_size": self.pipeline.config.max_batch_size,
                "batch_timeout": self.pipeline.config.batch_timeout,
            }

            # 튜닝 액션 기록
            action = TuningAction(
                timestamp=datetime.now(tz=KST),
                rule_name=rule.name,
                action=rule.action,
                before_config=before_config,
                after_config=after_config,
                reason=reason,
            )
            self.tuning_history.append(action)

            # 규칙 마지막 실행 시간 업데이트
            rule.last_executed = datetime.now(tz=KST)

        except Exception as e:
            logger.error(f"튜닝 액션 실행 실패 ({rule.name}): {e}", exc_info=True)

    def get_tuning_summary(self) -> Dict[str, Any]:
        """튜닝 요약을 반환합니다."""
        return {
            "total_actions": len(self.tuning_history),
            "recent_actions": [
                {
                    "timestamp": action.timestamp.isoformat(),
                    "rule": action.rule_name,
                    "action": action.action,
                    "reason": action.reason,
                }
                for action in self.tuning_history[-10:]
            ],
            "rules": [
                {
                    "name": rule.name,
                    "condition": rule.condition,
                    "action": rule.action,
                    "last_executed": (
                        rule.last_executed.isoformat() if rule.last_executed else None
                    ),
                }
                for rule in self.rules
            ],
        }
