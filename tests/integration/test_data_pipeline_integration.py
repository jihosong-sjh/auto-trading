"""데이터 파이프라인 통합 테스트.

Phase 3: Enhanced Data Pipeline
- 분봉 수집, 집계, 캐싱의 통합 테스트
- 엔드 투 엔드 데이터 플로우 테스트
"""

import asyncio
import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.models import ChartInterval, Stock
from src.services.data_aggregator import DataAggregator
from src.services.minute_bar_collector import MinuteBarCollector, TickData
from src.services.timeseries_cache import MultiLevelCache, TimeSeriesCache

KST = ZoneInfo("Asia/Seoul")


class TestDataPipelineIntegration:
    """데이터 파이프라인 통합 테스트."""

    @pytest.mark.asyncio
    async def test_tick_to_bar_to_cache(self):
        """틱 -> 분봉 -> 캐시 전체 플로우 테스트."""
        # 컴포넌트 초기화
        collector = MinuteBarCollector(supported_intervals=[1, 5])
        cache = TimeSeriesCache()

        await collector.start()

        try:
            # 틱 데이터 생성 및 추가
            now = datetime.now(tz=KST).replace(second=0, microsecond=0)

            for i in range(10):
                tick = TickData(
                    stock_code="005930",
                    timestamp=now + timedelta(seconds=i * 6),  # 6초 간격
                    price=Decimal(f"{70000 + i * 10}"),
                    volume=100 + i
                )
                await collector.add_tick(tick)

            # 처리 대기
            await asyncio.sleep(0.2)

            # 다음 분으로 이동 (분봉 완료)
            next_minute_tick = TickData(
                stock_code="005930",
                timestamp=now + timedelta(minutes=1),
                price=Decimal("70100"),
                volume=200
            )
            await collector.add_tick(next_minute_tick)

            # 처리 대기
            await asyncio.sleep(0.2)

            # 완성된 분봉 가져오기
            completed_bars = await collector.get_completed_bars(timeout=0.1)
            assert len(completed_bars) > 0

            # 캐시에 저장
            for bar in completed_bars:
                chart_data = bar.to_chart_data()
                await cache.put(bar.stock_code, chart_data.interval, chart_data)

            # 캐시에서 조회
            cached_data = await cache.get(
                "005930",
                ChartInterval.MINUTE_1,
                timestamp=now
            )
            assert cached_data is not None
            assert cached_data.stock_code == "005930"

        finally:
            await collector.stop()

    @pytest.mark.asyncio
    async def test_bar_aggregation_pipeline(self):
        """분봉 집계 파이프라인 테스트."""
        # 컴포넌트 초기화
        collector = MinuteBarCollector(supported_intervals=[1])
        cache = TimeSeriesCache()

        await collector.start()

        try:
            # 1분봉 데이터 생성 (10개)
            now = datetime(2024, 1, 1, 10, 0, 0, tzinfo=KST)

            for minute in range(10):
                # 각 분에 여러 틱
                for second in range(0, 60, 10):
                    tick = TickData(
                        stock_code="005930",
                        timestamp=now + timedelta(minutes=minute, seconds=second),
                        price=Decimal(f"{70000 + minute * 10}"),
                        volume=100
                    )
                    await collector.add_tick(tick)

            # 마지막 분봉 완료를 위한 다음 틱
            final_tick = TickData(
                stock_code="005930",
                timestamp=now + timedelta(minutes=10),
                price=Decimal("70100"),
                volume=100
            )
            await collector.add_tick(final_tick)

            # 처리 대기
            await asyncio.sleep(0.5)

            # 완성된 분봉들 가져오기
            completed_bars = []
            while True:
                bars = await collector.get_completed_bars(timeout=0.1)
                if not bars:
                    break
                completed_bars.extend(bars)

            # 1분봉이 10개 있어야 함
            assert len(completed_bars) >= 10

            # 5분봉으로 집계
            aggregated = DataAggregator.aggregate_bars(
                completed_bars[:10],
                ChartInterval.MINUTE_5
            )

            # 5분봉이 2개 생성되어야 함
            assert len(aggregated) == 2

            # 캐시에 저장
            for agg_data in aggregated:
                chart_data = agg_data.to_chart_data() if hasattr(agg_data, 'to_chart_data') else None
                if chart_data:
                    await cache.put(
                        agg_data.stock_code,
                        agg_data.interval,
                        chart_data
                    )

            # 캐시 통계 확인
            stats = cache.get_statistics()
            assert stats["entries"] > 0

        finally:
            await collector.stop()

    @pytest.mark.asyncio
    async def test_multi_level_cache_pipeline(self):
        """다단계 캐싱 파이프라인 테스트."""
        # 다단계 캐시 초기화
        multi_cache = MultiLevelCache(
            l1_size_mb=0.1,
            l2_size_mb=0.5,
            l3_size_mb=1.0
        )

        # 데이터 생성
        now = datetime.now(tz=KST)
        bars = []

        for i in range(100):
            from src.models.chart_data import ChartData
            chart = ChartData(
                stock_code="005930",
                interval=ChartInterval.MINUTE_1,
                timestamp=now + timedelta(minutes=i),
                open_price=Decimal("70000"),
                high_price=Decimal("70100"),
                low_price=Decimal("69900"),
                close_price=Decimal(f"{70000 + i}"),
                volume=1000
            )
            bars.append(chart)

        # L1에 최근 데이터 저장
        for bar in bars[-10:]:
            await multi_cache.put("005930", ChartInterval.MINUTE_1, bar)

        # L2에 중간 데이터 저장
        for bar in bars[50:90]:
            await multi_cache.l2_cache.put("005930", ChartInterval.MINUTE_1, bar)

        # L3에 과거 데이터 저장
        for bar in bars[:50]:
            await multi_cache.l3_cache.put("005930", ChartInterval.MINUTE_1, bar)

        # 최근 데이터 조회 (L1에서)
        recent_data = await multi_cache.get(
            "005930",
            ChartInterval.MINUTE_1,
            timestamp=bars[-1].timestamp
        )
        assert recent_data is not None

        # 중간 데이터 조회 (L2에서, L1으로 승격)
        mid_data = await multi_cache.get(
            "005930",
            ChartInterval.MINUTE_1,
            timestamp=bars[60].timestamp
        )
        assert mid_data is not None

        # 과거 데이터 조회 (L3에서, L2로 승격)
        old_data = await multi_cache.get(
            "005930",
            ChartInterval.MINUTE_1,
            timestamp=bars[10].timestamp
        )
        assert old_data is not None

        # 통계 확인
        stats = multi_cache.get_statistics()
        assert stats["L1"]["entries"] > 0

    @pytest.mark.asyncio
    async def test_real_time_analysis_pipeline(self):
        """실시간 분석 파이프라인 테스트."""
        # 컴포넌트 초기화
        collector = MinuteBarCollector(supported_intervals=[1])
        cache = TimeSeriesCache()

        await collector.start()

        try:
            # 실시간 틱 시뮬레이션
            now = datetime.now(tz=KST).replace(second=0, microsecond=0)
            chart_data_list = []

            # 20개 분봉 생성
            for minute in range(20):
                tick = TickData(
                    stock_code="005930",
                    timestamp=now + timedelta(minutes=minute),
                    price=Decimal(f"{70000 + minute * 10}"),
                    volume=1000
                )
                await collector.add_tick(tick)

                # 분봉 완료를 위한 다음 분 틱
                next_tick = TickData(
                    stock_code="005930",
                    timestamp=now + timedelta(minutes=minute + 1),
                    price=Decimal(f"{70010 + minute * 10}"),
                    volume=100
                )
                await collector.add_tick(next_tick)

            # 처리 대기
            await asyncio.sleep(0.5)

            # 완성된 분봉들 수집
            all_bars = []
            while True:
                bars = await collector.get_completed_bars(timeout=0.1)
                if not bars:
                    break
                all_bars.extend(bars)

            # ChartData로 변환
            for bar in all_bars:
                chart_data = bar.to_chart_data()
                chart_data_list.append(chart_data)
                await cache.put(bar.stock_code, chart_data.interval, chart_data)

            # 기술 지표 계산
            if len(chart_data_list) >= 14:
                # 이동평균
                ma = DataAggregator.calculate_moving_average(chart_data_list, 5)
                assert len(ma) == len(chart_data_list)

                # RSI
                rsi = DataAggregator.calculate_rsi(chart_data_list, 14)
                assert len(rsi) == len(chart_data_list)

                # 볼린저 밴드
                upper, middle, lower = DataAggregator.calculate_bollinger_bands(
                    chart_data_list, 10, 2
                )
                assert len(upper) == len(chart_data_list)

                # 통계
                stats = DataAggregator.calculate_statistics(chart_data_list)
                assert "mean_price" in stats
                assert "std_price" in stats

        finally:
            await collector.stop()

    @pytest.mark.asyncio
    async def test_cache_performance(self):
        """캐시 성능 테스트."""
        cache = TimeSeriesCache(max_size_mb=1)

        # 대량 데이터 저장
        now = datetime.now(tz=KST)
        insert_start = asyncio.get_event_loop().time()

        for i in range(1000):
            from src.models.chart_data import ChartData
            chart = ChartData(
                stock_code=f"{i // 100:06d}",  # 10개 종목
                interval=ChartInterval.MINUTE_1,
                timestamp=now + timedelta(minutes=i),
                open_price=Decimal("70000"),
                high_price=Decimal("70100"),
                low_price=Decimal("69900"),
                close_price=Decimal("70050"),
                volume=1000
            )
            await cache.put(
                chart.stock_code,
                chart.interval,
                chart
            )

        insert_time = asyncio.get_event_loop().time() - insert_start

        # 조회 성능
        query_start = asyncio.get_event_loop().time()

        for i in range(100):
            result = await cache.get(
                f"{i // 10:06d}",
                ChartInterval.MINUTE_1,
                timestamp=now + timedelta(minutes=i * 10)
            )

        query_time = asyncio.get_event_loop().time() - query_start

        # 성능 기준 (초 단위)
        assert insert_time < 5.0  # 1000개 삽입이 5초 이내
        assert query_time < 1.0  # 100개 조회가 1초 이내

        # 캐시 통계
        stats = cache.get_statistics()
        assert stats["entries"] > 0
        assert stats["size_bytes"] > 0

    @pytest.mark.asyncio
    async def test_concurrent_operations(self):
        """동시 작업 테스트."""
        collector = MinuteBarCollector()
        cache = TimeSeriesCache()

        await collector.start()

        try:
            # 여러 종목 동시 처리
            async def add_ticks_for_stock(stock_code: str):
                now = datetime.now(tz=KST).replace(second=0, microsecond=0)
                for i in range(10):
                    tick = TickData(
                        stock_code=stock_code,
                        timestamp=now + timedelta(seconds=i * 6),
                        price=Decimal(f"{70000 + i * 10}"),
                        volume=100
                    )
                    await collector.add_tick(tick)

            # 3개 종목 동시 처리
            await asyncio.gather(
                add_ticks_for_stock("005930"),
                add_ticks_for_stock("000660"),
                add_ticks_for_stock("035720")
            )

            # 처리 대기
            await asyncio.sleep(0.5)

            # 활성 바 확인
            active_bars = collector.get_active_bars()
            assert len(active_bars) >= 3  # 최소 3개 종목

            # 통계 확인
            stats = collector.get_statistics()
            assert stats["ticks_processed"] >= 30  # 3종목 * 10틱

        finally:
            await collector.stop()

    @pytest.mark.asyncio
    async def test_error_recovery(self):
        """에러 복구 테스트."""
        collector = MinuteBarCollector()

        # 시작/중지 반복
        for _ in range(3):
            await collector.start()
            assert collector.running

            # 일부 틱 처리
            tick = TickData(
                stock_code="005930",
                timestamp=datetime.now(tz=KST),
                price=Decimal("70000"),
                volume=100
            )
            await collector.add_tick(tick)

            await collector.stop()
            assert not collector.running

        # 최종 상태 확인
        stats = collector.get_statistics()
        assert stats["errors"] == 0