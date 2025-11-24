"""Batch Order Aggregator for grouping same-symbol orders.

Phase 2 - Order Processing Pipeline Optimization
동일 종목 주문을 배치로 묶어 처리하는 최적화 구현.
"""

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Deque, Dict, List, Optional, Set, Tuple
from uuid import uuid4
from zoneinfo import ZoneInfo

from ..models import OrderStatus, OrderType, PriceType
from ..models.order import Order
from ..utils.logger import get_logger

KST = ZoneInfo("Asia/Seoul")
logger = get_logger(__name__)


@dataclass
class OrderBatch:
    """동일 종목 주문 배치."""

    batch_id: str = field(default_factory=lambda: str(uuid4()))
    stock_code: str = ""
    orders: List[Order] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=KST))
    batch_type: Optional[OrderType] = None  # BUY or SELL
    total_quantity: int = 0
    average_price: Optional[Decimal] = None
    min_price: Optional[Decimal] = None
    max_price: Optional[Decimal] = None

    def add_order(self, order: Order) -> bool:
        """배치에 주문을 추가합니다.

        Args:
            order: 추가할 주문

        Returns:
            추가 성공 여부
        """
        # 첫 번째 주문인 경우
        if not self.orders:
            self.stock_code = order.stock_code
            self.batch_type = order.order_type
            self.orders.append(order)
            self._update_statistics()
            return True

        # 동일 종목, 동일 주문 유형 확인
        if order.stock_code != self.stock_code:
            return False

        if order.order_type != self.batch_type:
            return False

        self.orders.append(order)
        self._update_statistics()
        return True

    def _update_statistics(self):
        """배치 통계를 업데이트합니다."""
        if not self.orders:
            return

        self.total_quantity = sum(order.quantity for order in self.orders)

        # 가격 정보 수집 (지정가 주문만)
        prices = [
            order.limit_price for order in self.orders
            if order.price_type == PriceType.LIMIT and order.limit_price
        ]

        if prices:
            self.min_price = min(prices)
            self.max_price = max(prices)
            # 수량 가중 평균가 계산
            total_value = sum(
                order.limit_price * order.quantity
                for order in self.orders
                if order.price_type == PriceType.LIMIT and order.limit_price
            )
            total_qty = sum(
                order.quantity
                for order in self.orders
                if order.price_type == PriceType.LIMIT
            )
            if total_qty > 0:
                self.average_price = total_value / total_qty

    def can_merge(self, other: "OrderBatch") -> bool:
        """다른 배치와 병합 가능한지 확인합니다."""
        return (
            self.stock_code == other.stock_code
            and self.batch_type == other.batch_type
        )

    def merge(self, other: "OrderBatch") -> "OrderBatch":
        """두 배치를 병합합니다."""
        if not self.can_merge(other):
            raise ValueError("Cannot merge batches: incompatible types")

        merged = OrderBatch()
        merged.stock_code = self.stock_code
        merged.batch_type = self.batch_type
        merged.orders = self.orders + other.orders
        merged._update_statistics()
        return merged


@dataclass
class BatchingStrategy:
    """배치 생성 전략 설정."""

    max_batch_size: int = 10  # 최대 배치 크기
    batch_timeout: float = 1.0  # 배치 대기 시간 (초)
    enable_price_grouping: bool = True  # 가격대별 그룹핑 활성화
    price_tolerance: Decimal = Decimal("0.01")  # 가격 허용 범위 (1%)
    enable_smart_batching: bool = True  # 스마트 배칭 활성화
    priority_symbols: Set[str] = field(default_factory=set)  # 우선 처리 종목


class BatchAggregatorMetrics:
    """배치 집계기 성능 지표."""

    def __init__(self):
        self.total_batches_created = 0
        self.total_orders_batched = 0
        self.average_batch_size = 0.0
        self.max_batch_size = 0
        self.batch_creation_times: Deque[datetime] = deque(maxlen=100)
        self.symbol_batch_counts: Dict[str, int] = defaultdict(int)
        self.batch_type_counts: Dict[OrderType, int] = defaultdict(int)

    def record_batch(self, batch: OrderBatch):
        """배치 생성을 기록합니다."""
        self.total_batches_created += 1
        self.total_orders_batched += len(batch.orders)
        self.average_batch_size = (
            self.total_orders_batched / self.total_batches_created
            if self.total_batches_created > 0 else 0
        )
        self.max_batch_size = max(self.max_batch_size, len(batch.orders))
        self.batch_creation_times.append(batch.created_at)
        self.symbol_batch_counts[batch.stock_code] += 1
        if batch.batch_type:
            self.batch_type_counts[batch.batch_type] += 1

    def get_metrics(self) -> Dict[str, Any]:
        """지표를 반환합니다."""
        return {
            "total_batches_created": self.total_batches_created,
            "total_orders_batched": self.total_orders_batched,
            "average_batch_size": self.average_batch_size,
            "max_batch_size": self.max_batch_size,
            "symbol_batch_counts": dict(self.symbol_batch_counts),
            "batch_type_counts": {
                (k.value if hasattr(k, 'value') else k): v for k, v in self.batch_type_counts.items()
            },
            "recent_batch_rate": self._calculate_batch_rate(),
        }

    def _calculate_batch_rate(self) -> float:
        """최근 배치 생성 비율을 계산합니다."""
        if len(self.batch_creation_times) < 2:
            return 0.0

        time_span = (
            self.batch_creation_times[-1] - self.batch_creation_times[0]
        ).total_seconds()

        if time_span == 0:
            return 0.0

        return len(self.batch_creation_times) / time_span


class OrderBatchAggregator:
    """주문 배치 집계기.

    Features:
    - 동일 종목 주문 자동 그룹핑
    - 가격대별 스마트 배칭
    - 시간 기반 배치 플러시
    - 우선순위 종목 처리
    - 배치 최적화 알고리즘
    """

    def __init__(
        self,
        strategy: Optional[BatchingStrategy] = None,
        auto_flush_interval: float = 1.0,
    ):
        """배치 집계기를 초기화합니다.

        Args:
            strategy: 배칭 전략 설정
            auto_flush_interval: 자동 플러시 간격 (초)
        """
        self.strategy = strategy or BatchingStrategy()
        self.auto_flush_interval = auto_flush_interval

        # 주문 버퍼 (종목코드 -> 주문 리스트)
        self._order_buffer: Dict[str, List[Order]] = defaultdict(list)

        # 완성된 배치 큐
        self._ready_batches: asyncio.Queue[OrderBatch] = asyncio.Queue()

        # 타이머 관리
        self._batch_timers: Dict[str, asyncio.Task] = {}

        # 메트릭스
        self.metrics = BatchAggregatorMetrics()

        # 실행 상태
        self._running = False
        self._auto_flush_task: Optional[asyncio.Task] = None

    async def start(self):
        """배치 집계기를 시작합니다."""
        logger.info("배치 집계기 시작")
        self._running = True

        # 자동 플러시 태스크 시작
        self._auto_flush_task = asyncio.create_task(self._auto_flush_loop())

        logger.info(
            f"배치 집계기 시작 완료: "
            f"최대 배치 크기={self.strategy.max_batch_size}, "
            f"타임아웃={self.strategy.batch_timeout}초"
        )

    async def stop(self):
        """배치 집계기를 종료합니다."""
        logger.info("배치 집계기 종료 시작")
        self._running = False

        # 자동 플러시 태스크 종료
        if self._auto_flush_task:
            self._auto_flush_task.cancel()
            try:
                await self._auto_flush_task
            except asyncio.CancelledError:
                pass

        # 모든 타이머 취소
        for timer in self._batch_timers.values():
            timer.cancel()
        self._batch_timers.clear()

        # 남은 주문 모두 플러시
        await self._flush_all()

        logger.info("배치 집계기 종료 완료")

    async def add_order(self, order: Order) -> Optional[OrderBatch]:
        """주문을 추가하고 완성된 배치를 반환합니다.

        Args:
            order: 추가할 주문

        Returns:
            완성된 배치 (없으면 None)
        """
        stock_code = order.stock_code

        # 우선순위 종목은 즉시 처리
        if stock_code in self.strategy.priority_symbols:
            batch = OrderBatch()
            batch.add_order(order)
            logger.info(f"우선순위 종목 즉시 처리: {stock_code}")
            self.metrics.record_batch(batch)
            return batch

        # 버퍼에 추가
        self._order_buffer[stock_code].append(order)
        buffer_size = len(self._order_buffer[stock_code])

        logger.debug(
            f"주문 버퍼에 추가: {order.order_id} "
            f"(종목: {stock_code}, 버퍼 크기: {buffer_size})"
        )

        # 배치 크기 도달 시 즉시 생성
        if buffer_size >= self.strategy.max_batch_size:
            return await self._create_batch(stock_code)

        # 타이머 설정 (첫 주문인 경우)
        if buffer_size == 1:
            await self._start_batch_timer(stock_code)

        return None

    async def get_ready_batch(self, timeout: Optional[float] = None) -> Optional[OrderBatch]:
        """준비된 배치를 가져옵니다.

        Args:
            timeout: 대기 시간 (초)

        Returns:
            준비된 배치 (없으면 None)
        """
        try:
            if timeout:
                batch = await asyncio.wait_for(
                    self._ready_batches.get(),
                    timeout=timeout
                )
            else:
                batch = await self._ready_batches.get()
            return batch
        except asyncio.TimeoutError:
            return None

    async def _create_batch(self, stock_code: str) -> Optional[OrderBatch]:
        """버퍼의 주문들로 배치를 생성합니다."""
        orders = self._order_buffer.pop(stock_code, [])
        if not orders:
            return None

        # 타이머 취소
        if stock_code in self._batch_timers:
            self._batch_timers[stock_code].cancel()
            del self._batch_timers[stock_code]

        # 스마트 배칭 적용
        if self.strategy.enable_smart_batching:
            batches = self._smart_batch_orders(orders)
        else:
            batches = [self._simple_batch_orders(orders)]

        # 첫 번째 배치만 즉시 반환, 나머지는 큐에 추가
        result_batch = None
        for i, batch in enumerate(batches):
            self.metrics.record_batch(batch)
            if i == 0:
                result_batch = batch
            else:
                await self._ready_batches.put(batch)

        logger.info(
            f"배치 생성: {stock_code} - "
            f"{len(batches)}개 배치, 총 {len(orders)}개 주문"
        )

        return result_batch

    def _smart_batch_orders(self, orders: List[Order]) -> List[OrderBatch]:
        """스마트 배칭 알고리즘을 적용합니다."""
        batches = []

        # 주문 유형별로 분리
        buy_orders = [o for o in orders if o.order_type == OrderType.BUY]
        sell_orders = [o for o in orders if o.order_type == OrderType.SELL]

        # 각 유형별로 배치 생성
        for order_group in [buy_orders, sell_orders]:
            if not order_group:
                continue

            if self.strategy.enable_price_grouping:
                # 가격대별 그룹핑
                price_groups = self._group_by_price(order_group)
                for group in price_groups.values():
                    batch = OrderBatch()
                    for order in group:
                        batch.add_order(order)
                    batches.append(batch)
            else:
                # 단순 배치
                batch = OrderBatch()
                for order in order_group:
                    batch.add_order(order)
                batches.append(batch)

        return batches

    def _simple_batch_orders(self, orders: List[Order]) -> OrderBatch:
        """단순 배칭을 수행합니다."""
        batch = OrderBatch()
        for order in orders:
            batch.add_order(order)
        return batch

    def _group_by_price(self, orders: List[Order]) -> Dict[str, List[Order]]:
        """가격대별로 주문을 그룹핑합니다."""
        price_groups: Dict[str, List[Order]] = defaultdict(list)

        for order in orders:
            if order.price_type == PriceType.MARKET:
                # 시장가 주문은 별도 그룹
                price_groups["MARKET"].append(order)
            elif order.limit_price:
                # 지정가 주문은 가격대별 그룹
                price_range = self._get_price_range(order.limit_price)
                price_groups[price_range].append(order)

        return price_groups

    def _get_price_range(self, price: Decimal) -> str:
        """가격을 기준으로 가격대를 결정합니다."""
        # 가격 허용 범위를 기준으로 그룹핑
        tolerance = self.strategy.price_tolerance
        base_price = price * (1 - tolerance)
        range_key = f"{int(base_price / 100) * 100}"
        return range_key

    async def _start_batch_timer(self, stock_code: str):
        """배치 타이머를 시작합니다."""
        async def timer_callback():
            try:
                await asyncio.sleep(self.strategy.batch_timeout)
                await self._create_batch(stock_code)
            except asyncio.CancelledError:
                pass

        self._batch_timers[stock_code] = asyncio.create_task(timer_callback())

    async def _auto_flush_loop(self):
        """주기적으로 오래된 배치를 플러시합니다."""
        while self._running:
            try:
                await asyncio.sleep(self.auto_flush_interval)
                await self._flush_old_batches()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"자동 플러시 오류: {e}", exc_info=True)

    async def _flush_old_batches(self):
        """오래된 배치를 플러시합니다."""
        now = datetime.now(tz=KST)
        timeout_threshold = timedelta(seconds=self.strategy.batch_timeout)

        stocks_to_flush = []
        for stock_code, orders in self._order_buffer.items():
            if orders:
                # 첫 주문의 시간 확인
                first_order_time = orders[0].created_at
                if now - first_order_time > timeout_threshold:
                    stocks_to_flush.append(stock_code)

        for stock_code in stocks_to_flush:
            batch = await self._create_batch(stock_code)
            if batch:
                await self._ready_batches.put(batch)

    async def _flush_all(self):
        """모든 버퍼의 주문을 플러시합니다."""
        for stock_code in list(self._order_buffer.keys()):
            batch = await self._create_batch(stock_code)
            if batch:
                await self._ready_batches.put(batch)

    def get_buffer_status(self) -> Dict[str, int]:
        """현재 버퍼 상태를 반환합니다."""
        return {
            stock_code: len(orders)
            for stock_code, orders in self._order_buffer.items()
        }

    def get_metrics(self) -> Dict[str, Any]:
        """성능 지표를 반환합니다."""
        return {
            "buffer_status": self.get_buffer_status(),
            "ready_batches": self._ready_batches.qsize(),
            "active_timers": len(self._batch_timers),
            "aggregator_metrics": self.metrics.get_metrics(),
            "strategy": {
                "max_batch_size": self.strategy.max_batch_size,
                "batch_timeout": self.strategy.batch_timeout,
                "enable_price_grouping": self.strategy.enable_price_grouping,
                "enable_smart_batching": self.strategy.enable_smart_batching,
                "priority_symbols": list(self.strategy.priority_symbols),
            }
        }