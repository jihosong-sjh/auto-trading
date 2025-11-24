"""MinuteBarCollector 단위 테스트."""

import asyncio
import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.models import ChartInterval
from src.services.minute_bar_collector import (
    MinuteBar,
    MinuteBarCollector,
    TickData,
)

KST = ZoneInfo("Asia/Seoul")


class TestTickData:
    """TickData 테스트."""

    def test_tick_data_creation(self):
        """TickData 생성 테스트."""
        tick = TickData(
            stock_code="005930",
            timestamp=datetime.now(tz=KST),
            price=Decimal("70000"),
            volume=100
        )

        assert tick.stock_code == "005930"
        assert tick.price == Decimal("70000")
        assert tick.volume == 100
        assert tick.timestamp.tzinfo == KST

    def test_tick_data_timezone_conversion(self):
        """시간대 변환 테스트."""
        # Naive datetime
        naive_dt = datetime.now()
        tick = TickData(
            stock_code="005930",
            timestamp=naive_dt,
            price=Decimal("70000"),
            volume=100
        )
        assert tick.timestamp.tzinfo == KST

        # UTC datetime
        from zoneinfo import ZoneInfo
        utc_dt = datetime.now(tz=ZoneInfo("UTC"))
        tick2 = TickData(
            stock_code="005930",
            timestamp=utc_dt,
            price=Decimal("70000"),
            volume=100
        )
        assert tick2.timestamp.tzinfo == KST


class TestMinuteBar:
    """MinuteBar 테스트."""

    def test_minute_bar_creation(self):
        """MinuteBar 생성 테스트."""
        now = datetime.now(tz=KST)
        bar = MinuteBar(
            stock_code="005930",
            interval_minutes=1,
            start_time=now,
            end_time=now + timedelta(minutes=1),
            open_price=Decimal("70000"),
            high_price=Decimal("70100"),
            low_price=Decimal("69900"),
            close_price=Decimal("70050"),
            volume=1000,
            tick_count=10
        )

        assert bar.stock_code == "005930"
        assert bar.interval_minutes == 1
        assert bar.open_price == Decimal("70000")
        assert bar.high_price == Decimal("70100")
        assert bar.low_price == Decimal("69900")
        assert bar.close_price == Decimal("70050")
        assert bar.volume == 1000
        assert bar.tick_count == 10

    def test_minute_bar_update(self):
        """MinuteBar 업데이트 테스트."""
        now = datetime.now(tz=KST)
        bar = MinuteBar(
            stock_code="005930",
            interval_minutes=1,
            start_time=now,
            end_time=now + timedelta(minutes=1),
            open_price=Decimal("70000"),
            high_price=Decimal("70000"),
            low_price=Decimal("70000"),
            close_price=Decimal("70000"),
            volume=100,
            tick_count=1
        )

        # 더 높은 가격 틱
        tick1 = TickData(
            stock_code="005930",
            timestamp=now + timedelta(seconds=10),
            price=Decimal("70200"),
            volume=50
        )
        bar.update(tick1)

        assert bar.high_price == Decimal("70200")
        assert bar.close_price == Decimal("70200")
        assert bar.volume == 150
        assert bar.tick_count == 2

        # 더 낮은 가격 틱
        tick2 = TickData(
            stock_code="005930",
            timestamp=now + timedelta(seconds=20),
            price=Decimal("69800"),
            volume=75
        )
        bar.update(tick2)

        assert bar.low_price == Decimal("69800")
        assert bar.close_price == Decimal("69800")
        assert bar.volume == 225
        assert bar.tick_count == 3

    def test_minute_bar_to_chart_data(self):
        """ChartData 변환 테스트."""
        now = datetime.now(tz=KST)

        # 1분봉
        bar1 = MinuteBar(
            stock_code="005930",
            interval_minutes=1,
            start_time=now,
            end_time=now + timedelta(minutes=1),
            open_price=Decimal("70000"),
            high_price=Decimal("70100"),
            low_price=Decimal("69900"),
            close_price=Decimal("70050"),
            volume=1000
        )

        chart_data1 = bar1.to_chart_data()
        assert chart_data1.interval == ChartInterval.MINUTE_1
        assert chart_data1.stock_code == "005930"
        assert chart_data1.open_price == Decimal("70000")

        # 5분봉
        bar5 = MinuteBar(
            stock_code="005930",
            interval_minutes=5,
            start_time=now,
            end_time=now + timedelta(minutes=5),
            open_price=Decimal("70000"),
            high_price=Decimal("70200"),
            low_price=Decimal("69800"),
            close_price=Decimal("70100"),
            volume=5000
        )

        chart_data5 = bar5.to_chart_data()
        assert chart_data5.interval == ChartInterval.MINUTE_5


class TestMinuteBarCollector:
    """MinuteBarCollector 테스트."""

    @pytest.mark.asyncio
    async def test_collector_initialization(self):
        """수집기 초기화 테스트."""
        collector = MinuteBarCollector()

        assert collector.supported_intervals == [1, 5, 10, 30, 60]
        assert not collector.running
        assert collector.stats["ticks_processed"] == 0
        assert collector.stats["bars_completed"] == 0

        # 커스텀 간격
        custom_collector = MinuteBarCollector(supported_intervals=[1, 3, 5])
        assert custom_collector.supported_intervals == [1, 3, 5]

    @pytest.mark.asyncio
    async def test_collector_start_stop(self):
        """수집기 시작/중지 테스트."""
        collector = MinuteBarCollector()

        # 시작
        await collector.start()
        assert collector.running
        assert collector.process_task is not None

        # 중지
        await collector.stop()
        assert not collector.running

    @pytest.mark.asyncio
    async def test_bar_window_calculation(self):
        """시간 윈도우 계산 테스트."""
        collector = MinuteBarCollector()

        # 1분 윈도우
        timestamp = datetime(2024, 1, 1, 10, 23, 45, tzinfo=KST)
        start, end = collector._get_bar_window(timestamp, 1)

        assert start == datetime(2024, 1, 1, 10, 23, 0, tzinfo=KST)
        assert end == datetime(2024, 1, 1, 10, 24, 0, tzinfo=KST)

        # 5분 윈도우
        start5, end5 = collector._get_bar_window(timestamp, 5)
        assert start5 == datetime(2024, 1, 1, 10, 20, 0, tzinfo=KST)
        assert end5 == datetime(2024, 1, 1, 10, 25, 0, tzinfo=KST)

        # 30분 윈도우
        start30, end30 = collector._get_bar_window(timestamp, 30)
        assert start30 == datetime(2024, 1, 1, 10, 0, 0, tzinfo=KST)
        assert end30 == datetime(2024, 1, 1, 10, 30, 0, tzinfo=KST)

    @pytest.mark.asyncio
    async def test_tick_processing(self):
        """틱 처리 테스트."""
        collector = MinuteBarCollector(supported_intervals=[1])
        await collector.start()

        try:
            # 틱 추가
            now = datetime.now(tz=KST).replace(second=0, microsecond=0)
            tick = TickData(
                stock_code="005930",
                timestamp=now,
                price=Decimal("70000"),
                volume=100
            )

            await collector.add_tick(tick)

            # 처리 대기
            await asyncio.sleep(0.1)

            # 활성 바 확인
            active_bars = collector.get_active_bars("005930")
            assert 1 in active_bars
            assert active_bars[1].open_price == Decimal("70000")

        finally:
            await collector.stop()

    @pytest.mark.asyncio
    async def test_bar_completion(self):
        """분봉 완료 테스트."""
        collector = MinuteBarCollector(supported_intervals=[1])
        await collector.start()

        try:
            # 현재 분의 시작
            now = datetime.now(tz=KST).replace(second=0, microsecond=0)

            # 첫 틱
            tick1 = TickData(
                stock_code="005930",
                timestamp=now + timedelta(seconds=10),
                price=Decimal("70000"),
                volume=100
            )
            await collector.add_tick(tick1)

            # 두 번째 틱
            tick2 = TickData(
                stock_code="005930",
                timestamp=now + timedelta(seconds=30),
                price=Decimal("70100"),
                volume=200
            )
            await collector.add_tick(tick2)

            # 다음 분의 틱 (분봉 완료 트리거)
            tick3 = TickData(
                stock_code="005930",
                timestamp=now + timedelta(minutes=1, seconds=5),
                price=Decimal("70200"),
                volume=150
            )
            await collector.add_tick(tick3)

            # 처리 대기
            await asyncio.sleep(0.2)

            # 완성된 바 확인
            completed = await collector.get_completed_bars(timeout=0.1)
            assert len(completed) == 1
            assert completed[0].stock_code == "005930"
            assert completed[0].open_price == Decimal("70000")
            assert completed[0].close_price == Decimal("70100")
            assert completed[0].volume == 300

        finally:
            await collector.stop()

    @pytest.mark.asyncio
    async def test_multiple_intervals(self):
        """다중 시간 프레임 테스트."""
        collector = MinuteBarCollector(supported_intervals=[1, 5])
        await collector.start()

        try:
            now = datetime.now(tz=KST).replace(second=0, microsecond=0)

            # 틱 추가
            tick = TickData(
                stock_code="005930",
                timestamp=now,
                price=Decimal("70000"),
                volume=100
            )
            await collector.add_tick(tick)

            # 처리 대기
            await asyncio.sleep(0.1)

            # 두 간격 모두에 바가 생성되어야 함
            active_bars = collector.get_active_bars("005930")
            assert 1 in active_bars
            assert 5 in active_bars

        finally:
            await collector.stop()

    @pytest.mark.asyncio
    async def test_statistics(self):
        """통계 테스트."""
        collector = MinuteBarCollector()
        stats = collector.get_statistics()

        assert "ticks_processed" in stats
        assert "bars_completed" in stats
        assert "errors" in stats
        assert "active_stocks" in stats
        assert "active_bars_count" in stats
        assert "supported_intervals" in stats
        assert "running" in stats