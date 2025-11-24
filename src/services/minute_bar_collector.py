"""분봉 데이터 수집 및 집계 서비스.

Phase 3: Enhanced Data Pipeline
- 실시간 분봉 데이터 수집
- 틱 데이터를 분봉으로 집계
- 다양한 시간 프레임 지원 (1분, 5분, 10분, 30분, 60분)
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Set
from zoneinfo import ZoneInfo

from ..models import ChartInterval, Stock
from ..models.chart_data import ChartData
from ..utils.logger import get_logger

KST = ZoneInfo("Asia/Seoul")
logger = get_logger(__name__)


@dataclass
class TickData:
    """실시간 체결 데이터."""

    stock_code: str
    timestamp: datetime
    price: Decimal
    volume: int

    def __post_init__(self):
        """타임스탬프 KST 변환."""
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=KST)
        elif self.timestamp.tzinfo != KST:
            self.timestamp = self.timestamp.astimezone(KST)


@dataclass
class MinuteBar:
    """분봉 데이터 (OHLCV)."""

    stock_code: str
    interval_minutes: int
    start_time: datetime
    end_time: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int = 0
    tick_count: int = 0

    def __post_init__(self):
        """타임스탬프 KST 변환."""
        if self.start_time.tzinfo is None:
            self.start_time = self.start_time.replace(tzinfo=KST)
        if self.end_time.tzinfo is None:
            self.end_time = self.end_time.replace(tzinfo=KST)

    def update(self, tick: TickData) -> None:
        """틱 데이터로 분봉 업데이트.

        Args:
            tick: 체결 데이터
        """
        # 고가/저가 업데이트
        self.high_price = max(self.high_price, tick.price)
        self.low_price = min(self.low_price, tick.price)

        # 종가 업데이트 (최신 체결가)
        self.close_price = tick.price

        # 거래량 누적
        self.volume += tick.volume
        self.tick_count += 1

    def to_chart_data(self) -> ChartData:
        """ChartData 모델로 변환.

        Returns:
            ChartData 인스턴스
        """
        # 분봉 interval 매핑
        interval_map = {
            1: ChartInterval.MINUTE_1,
            5: ChartInterval.MINUTE_5,
            10: ChartInterval.MINUTE_10,
            30: ChartInterval.MINUTE_30,
            60: ChartInterval.MINUTE_60
        }

        interval = interval_map.get(self.interval_minutes, ChartInterval.MINUTE_1)

        return ChartData(
            stock_code=self.stock_code,
            interval=interval,
            timestamp=self.start_time,
            open_price=self.open_price,
            high_price=self.high_price,
            low_price=self.low_price,
            close_price=self.close_price,
            volume=self.volume
        )


class MinuteBarCollector:
    """분봉 데이터 수집기.

    실시간 체결 데이터를 받아서 분봉으로 집계합니다.
    다양한 시간 프레임(1분, 5분, 10분, 30분, 60분)을 동시에 생성합니다.

    Attributes:
        supported_intervals: 지원하는 분봉 간격 (분 단위)
        active_bars: 현재 집계 중인 분봉 (종목코드별, 간격별)
        completed_bars: 완성된 분봉 큐
        tick_buffer: 틱 데이터 버퍼 (비동기 처리용)
        running: 실행 상태
        process_task: 틱 처리 태스크
    """

    def __init__(self, supported_intervals: Optional[List[int]] = None):
        """MinuteBarCollector 초기화.

        Args:
            supported_intervals: 지원할 분봉 간격 리스트 (기본값: [1, 5, 10, 30, 60])
        """
        self.supported_intervals = supported_intervals or [1, 5, 10, 30, 60]

        # 현재 집계 중인 분봉 (stock_code -> interval -> MinuteBar)
        self.active_bars: Dict[str, Dict[int, MinuteBar]] = defaultdict(dict)

        # 완성된 분봉 큐
        self.completed_bars: asyncio.Queue = asyncio.Queue()

        # 틱 데이터 버퍼
        self.tick_buffer: asyncio.Queue = asyncio.Queue()

        self.running = False
        self.process_task: Optional[asyncio.Task] = None

        # 통계
        self.stats = {
            "ticks_processed": 0,
            "bars_completed": 0,
            "errors": 0
        }

    def _get_bar_window(self, timestamp: datetime, interval_minutes: int) -> tuple[datetime, datetime]:
        """해당 시점이 속하는 분봉 시간 윈도우 계산.

        Args:
            timestamp: 기준 시점
            interval_minutes: 분봉 간격 (분)

        Returns:
            (시작시간, 종료시간) 튜플
        """
        # 분 단위로 정렬
        minute = timestamp.minute
        aligned_minute = (minute // interval_minutes) * interval_minutes

        start_time = timestamp.replace(
            minute=aligned_minute,
            second=0,
            microsecond=0
        )

        end_time = start_time + timedelta(minutes=interval_minutes)

        return start_time, end_time

    async def add_tick(self, tick: TickData) -> None:
        """틱 데이터 추가.

        Args:
            tick: 체결 데이터
        """
        await self.tick_buffer.put(tick)

    async def add_stock_tick(self, stock: Stock) -> None:
        """Stock 객체에서 틱 데이터 추출 및 추가.

        Args:
            stock: Stock 객체 (current_price, volume 포함)
        """
        tick = TickData(
            stock_code=stock.stock_code,
            timestamp=datetime.now(tz=KST),
            price=stock.current_price,
            volume=getattr(stock, 'last_volume', 0)  # 마지막 체결 거래량
        )
        await self.add_tick(tick)

    async def start(self) -> None:
        """분봉 수집기 시작."""
        if self.running:
            logger.warning("MinuteBarCollector is already running")
            return

        self.running = True
        logger.info(f"MinuteBarCollector started with intervals: {self.supported_intervals}")

        # 틱 처리 태스크 시작
        self.process_task = asyncio.create_task(self._process_ticks())

    async def stop(self) -> None:
        """분봉 수집기 중지."""
        if not self.running:
            return

        logger.info("Stopping MinuteBarCollector")
        self.running = False

        # 태스크 종료 대기
        if self.process_task:
            self.process_task.cancel()
            try:
                await self.process_task
            except asyncio.CancelledError:
                pass

        # 마지막 분봉들 완료 처리
        await self._complete_all_bars()

        logger.info(f"MinuteBarCollector stopped. Stats: {self.stats}")

    async def _process_ticks(self) -> None:
        """틱 데이터 처리 루프."""
        try:
            while self.running:
                try:
                    # 틱 데이터 대기 (최대 1초)
                    tick = await asyncio.wait_for(
                        self.tick_buffer.get(),
                        timeout=1.0
                    )

                    # 각 간격별로 분봉 업데이트
                    await self._update_bars(tick)

                    self.stats["ticks_processed"] += 1

                except asyncio.TimeoutError:
                    # 타임아웃 시 현재 시간 체크하여 완료된 분봉 처리
                    await self._check_completed_bars()

                except Exception as e:
                    logger.error(f"Error processing tick: {e}")
                    self.stats["errors"] += 1

        except asyncio.CancelledError:
            logger.debug("Tick processing cancelled")
            raise

    async def _update_bars(self, tick: TickData) -> None:
        """틱 데이터로 분봉 업데이트.

        Args:
            tick: 체결 데이터
        """
        stock_code = tick.stock_code

        for interval in self.supported_intervals:
            start_time, end_time = self._get_bar_window(tick.timestamp, interval)

            # 현재 분봉 가져오기 또는 생성
            if interval not in self.active_bars[stock_code]:
                # 새 분봉 생성
                self.active_bars[stock_code][interval] = MinuteBar(
                    stock_code=stock_code,
                    interval_minutes=interval,
                    start_time=start_time,
                    end_time=end_time,
                    open_price=tick.price,
                    high_price=tick.price,
                    low_price=tick.price,
                    close_price=tick.price,
                    volume=tick.volume,
                    tick_count=1
                )
                logger.debug(f"Created new {interval}-minute bar for {stock_code} at {start_time}")

            else:
                bar = self.active_bars[stock_code][interval]

                # 시간 윈도우 확인
                if tick.timestamp >= bar.end_time:
                    # 현재 분봉 완료
                    await self._complete_bar(stock_code, interval)

                    # 새 분봉 생성
                    self.active_bars[stock_code][interval] = MinuteBar(
                        stock_code=stock_code,
                        interval_minutes=interval,
                        start_time=start_time,
                        end_time=end_time,
                        open_price=tick.price,
                        high_price=tick.price,
                        low_price=tick.price,
                        close_price=tick.price,
                        volume=tick.volume,
                        tick_count=1
                    )
                else:
                    # 기존 분봉 업데이트
                    bar.update(tick)

    async def _check_completed_bars(self) -> None:
        """완료된 분봉 확인 및 처리."""
        current_time = datetime.now(tz=KST)

        for stock_code in list(self.active_bars.keys()):
            for interval in list(self.active_bars[stock_code].keys()):
                bar = self.active_bars[stock_code][interval]

                # 종료 시간이 지난 분봉 완료 처리
                if current_time >= bar.end_time:
                    await self._complete_bar(stock_code, interval)

    async def _complete_bar(self, stock_code: str, interval: int) -> None:
        """분봉 완료 처리.

        Args:
            stock_code: 종목코드
            interval: 분봉 간격
        """
        if stock_code not in self.active_bars:
            return

        if interval not in self.active_bars[stock_code]:
            return

        bar = self.active_bars[stock_code].pop(interval)

        # 완성된 분봉을 큐에 추가
        await self.completed_bars.put(bar)

        self.stats["bars_completed"] += 1

        logger.debug(
            f"Completed {interval}-minute bar for {stock_code}: "
            f"O={bar.open_price} H={bar.high_price} L={bar.low_price} "
            f"C={bar.close_price} V={bar.volume} ticks={bar.tick_count}"
        )

    async def _complete_all_bars(self) -> None:
        """모든 활성 분봉 완료 처리."""
        for stock_code in list(self.active_bars.keys()):
            for interval in list(self.active_bars[stock_code].keys()):
                await self._complete_bar(stock_code, interval)

    async def get_completed_bars(self, timeout: float = 1.0) -> List[MinuteBar]:
        """완성된 분봉 가져오기.

        Args:
            timeout: 대기 시간 (초)

        Returns:
            완성된 분봉 리스트
        """
        bars = []

        try:
            while True:
                bar = await asyncio.wait_for(
                    self.completed_bars.get(),
                    timeout=timeout
                )
                bars.append(bar)
                timeout = 0.01  # 이후 바로 다음 항목 확인

        except asyncio.TimeoutError:
            pass

        return bars

    def get_active_bars(self, stock_code: Optional[str] = None) -> Dict:
        """현재 집계 중인 분봉 조회.

        Args:
            stock_code: 특정 종목만 조회 (None이면 전체)

        Returns:
            활성 분봉 정보
        """
        if stock_code:
            return dict(self.active_bars.get(stock_code, {}))

        return {
            code: dict(intervals)
            for code, intervals in self.active_bars.items()
        }

    def get_statistics(self) -> Dict:
        """수집기 통계 반환.

        Returns:
            통계 정보
        """
        return {
            **self.stats,
            "active_stocks": len(self.active_bars),
            "active_bars_count": sum(
                len(intervals) for intervals in self.active_bars.values()
            ),
            "supported_intervals": self.supported_intervals,
            "running": self.running
        }