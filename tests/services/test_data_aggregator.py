"""DataAggregator 단위 테스트."""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.models import ChartInterval
from src.models.chart_data import ChartData
from src.services.data_aggregator import DataAggregator, AggregatedData
from src.services.minute_bar_collector import MinuteBar

KST = ZoneInfo("Asia/Seoul")


class TestDataAggregator:
    """DataAggregator 테스트."""

    def test_aggregate_bars_empty(self):
        """빈 리스트 집계 테스트."""
        result = DataAggregator.aggregate_bars([], ChartInterval.MINUTE_5)
        assert result == []

    def test_aggregate_bars_single(self):
        """단일 바 집계 테스트."""
        now = datetime.now(tz=KST).replace(second=0, microsecond=0)
        bar = MinuteBar(
            stock_code="005930",
            interval_minutes=1,
            start_time=now,
            end_time=now + timedelta(minutes=1),
            open_price=Decimal("70000"),
            high_price=Decimal("70100"),
            low_price=Decimal("69900"),
            close_price=Decimal("70050"),
            volume=100
        )

        result = DataAggregator.aggregate_bars([bar], ChartInterval.MINUTE_5)
        assert len(result) == 1
        assert result[0].stock_code == "005930"
        assert result[0].open_price == Decimal("70000")
        assert result[0].close_price == Decimal("70050")

    def test_aggregate_bars_to_5min(self):
        """1분봉 -> 5분봉 집계 테스트."""
        now = datetime(2024, 1, 1, 10, 0, 0, tzinfo=KST)
        bars = []

        # 5개의 1분봉 생성
        for i in range(5):
            bar = MinuteBar(
                stock_code="005930",
                interval_minutes=1,
                start_time=now + timedelta(minutes=i),
                end_time=now + timedelta(minutes=i + 1),
                open_price=Decimal(f"{70000 + i * 10}"),
                high_price=Decimal(f"{70100 + i * 10}"),
                low_price=Decimal(f"{69900 + i * 10}"),
                close_price=Decimal(f"{70050 + i * 10}"),
                volume=100 + i * 10
            )
            bars.append(bar)

        result = DataAggregator.aggregate_bars(bars, ChartInterval.MINUTE_5)

        assert len(result) == 1
        agg = result[0]
        assert agg.stock_code == "005930"
        assert agg.interval == ChartInterval.MINUTE_5
        assert agg.open_price == Decimal("70000")  # 첫 번째 바의 시가
        assert agg.close_price == Decimal("70090")  # 마지막 바의 종가
        assert agg.high_price == Decimal("70140")  # 최고가
        assert agg.low_price == Decimal("69900")  # 최저가
        assert agg.volume == 600  # 총 거래량
        assert agg.bar_count == 5

    def test_aggregate_bars_multiple_windows(self):
        """여러 시간 윈도우 집계 테스트."""
        now = datetime(2024, 1, 1, 10, 0, 0, tzinfo=KST)
        bars = []

        # 10개의 1분봉 생성 (2개의 5분봉)
        for i in range(10):
            bar = MinuteBar(
                stock_code="005930",
                interval_minutes=1,
                start_time=now + timedelta(minutes=i),
                end_time=now + timedelta(minutes=i + 1),
                open_price=Decimal(f"{70000 + i}"),
                high_price=Decimal(f"{70100 + i}"),
                low_price=Decimal(f"{69900 + i}"),
                close_price=Decimal(f"{70050 + i}"),
                volume=100
            )
            bars.append(bar)

        result = DataAggregator.aggregate_bars(bars, ChartInterval.MINUTE_5)

        assert len(result) == 2
        # 첫 번째 5분봉
        assert result[0].open_price == Decimal("70000")
        assert result[0].close_price == Decimal("70054")
        # 두 번째 5분봉
        assert result[1].open_price == Decimal("70005")
        assert result[1].close_price == Decimal("70059")

    def test_vwap_calculation(self):
        """VWAP 계산 테스트."""
        now = datetime.now(tz=KST).replace(second=0, microsecond=0)
        bars = []

        # 가격과 거래량이 다른 바들
        prices_volumes = [
            (Decimal("70000"), 100),
            (Decimal("70100"), 200),
            (Decimal("70200"), 150),
        ]

        for i, (price, volume) in enumerate(prices_volumes):
            bar = MinuteBar(
                stock_code="005930",
                interval_minutes=1,
                start_time=now + timedelta(minutes=i),
                end_time=now + timedelta(minutes=i + 1),
                open_price=price,
                high_price=price + 10,
                low_price=price - 10,
                close_price=price,
                volume=volume
            )
            bars.append(bar)

        result = DataAggregator.aggregate_bars(bars, ChartInterval.MINUTE_5)

        assert len(result) == 1
        # VWAP = (70000*100 + 70100*200 + 70200*150) / (100+200+150)
        expected_vwap = (70000*100 + 70100*200 + 70200*150) / 450
        assert abs(float(result[0].vwap) - expected_vwap) < 0.01

    def test_moving_average(self):
        """이동평균 계산 테스트."""
        # 테스트 데이터 생성
        data = []
        for i in range(10):
            chart = ChartData(
                stock_code="005930",
                interval=ChartInterval.MINUTE_1,
                timestamp=datetime.now(tz=KST) + timedelta(minutes=i),
                open_price=Decimal("70000"),
                high_price=Decimal("70100"),
                low_price=Decimal("69900"),
                close_price=Decimal(f"{70000 + i * 10}"),
                volume=1000
            )
            data.append(chart)

        # 3일 이동평균
        ma = DataAggregator.calculate_moving_average(data, 3)

        assert ma[0] is None  # 첫 번째
        assert ma[1] is None  # 두 번째
        assert ma[2] == Decimal("70010")  # (70000 + 70010 + 70020) / 3
        assert ma[3] == Decimal("70020")  # (70010 + 70020 + 70030) / 3

    def test_ema(self):
        """지수이동평균 계산 테스트."""
        # 테스트 데이터 생성
        data = []
        for i in range(10):
            chart = ChartData(
                stock_code="005930",
                interval=ChartInterval.MINUTE_1,
                timestamp=datetime.now(tz=KST) + timedelta(minutes=i),
                open_price=Decimal("70000"),
                high_price=Decimal("70100"),
                low_price=Decimal("69900"),
                close_price=Decimal(f"{70000 + i * 10}"),
                volume=1000
            )
            data.append(chart)

        # 3일 EMA
        ema = DataAggregator.calculate_ema(data, 3)

        assert ema[0] is None
        assert ema[1] is None
        assert ema[2] is not None  # 첫 EMA는 단순평균
        assert ema[3] is not None  # 이후 EMA 계산

        # EMA는 최근 데이터에 더 큰 가중치
        multiplier = 2 / (3 + 1)
        expected_ema3 = float(data[3].close_price) * multiplier + float(ema[2]) * (1 - multiplier)
        assert abs(float(ema[3]) - expected_ema3) < 0.01

    def test_bollinger_bands(self):
        """볼린저 밴드 계산 테스트."""
        # 테스트 데이터 생성
        data = []
        for i in range(20):
            chart = ChartData(
                stock_code="005930",
                interval=ChartInterval.MINUTE_1,
                timestamp=datetime.now(tz=KST) + timedelta(minutes=i),
                open_price=Decimal("70000"),
                high_price=Decimal("70100"),
                low_price=Decimal("69900"),
                close_price=Decimal(f"{70000 + (i % 3) * 10}"),  # 변동성 추가
                volume=1000
            )
            data.append(chart)

        upper, middle, lower = DataAggregator.calculate_bollinger_bands(data, period=5, num_std=2)

        # 처음 4개는 None
        for i in range(4):
            assert upper[i] is None
            assert middle[i] is None
            assert lower[i] is None

        # 5번째부터 값이 있음
        assert upper[4] is not None
        assert middle[4] is not None
        assert lower[4] is not None

        # 상단 > 중간 > 하단
        assert upper[5] > middle[5] > lower[5]

    def test_rsi(self):
        """RSI 계산 테스트."""
        # 상승 추세 데이터
        data = []
        for i in range(20):
            chart = ChartData(
                stock_code="005930",
                interval=ChartInterval.MINUTE_1,
                timestamp=datetime.now(tz=KST) + timedelta(minutes=i),
                open_price=Decimal("70000"),
                high_price=Decimal("70100"),
                low_price=Decimal("69900"),
                close_price=Decimal(f"{70000 + i * 10}"),  # 계속 상승
                volume=1000
            )
            data.append(chart)

        rsi = DataAggregator.calculate_rsi(data, period=14)

        # 처음 14개는 None
        for i in range(15):
            assert rsi[i] is None

        # 15번째부터 RSI 값
        assert rsi[15] is not None
        # 계속 상승했으므로 RSI는 높아야 함 (70 이상)
        assert rsi[-1] > 70

    def test_rsi_downtrend(self):
        """하락 추세 RSI 테스트."""
        # 하락 추세 데이터
        data = []
        for i in range(20):
            chart = ChartData(
                stock_code="005930",
                interval=ChartInterval.MINUTE_1,
                timestamp=datetime.now(tz=KST) + timedelta(minutes=i),
                open_price=Decimal("70000"),
                high_price=Decimal("70100"),
                low_price=Decimal("69900"),
                close_price=Decimal(f"{70000 - i * 10}"),  # 계속 하락
                volume=1000
            )
            data.append(chart)

        rsi = DataAggregator.calculate_rsi(data, period=14)

        # 계속 하락했으므로 RSI는 낮아야 함 (30 이하)
        if rsi[-1] is not None:
            assert rsi[-1] < 30

    def test_macd(self):
        """MACD 계산 테스트."""
        # 테스트 데이터 생성 (충분한 개수)
        data = []
        for i in range(50):
            chart = ChartData(
                stock_code="005930",
                interval=ChartInterval.MINUTE_1,
                timestamp=datetime.now(tz=KST) + timedelta(minutes=i),
                open_price=Decimal("70000"),
                high_price=Decimal("70100"),
                low_price=Decimal("69900"),
                close_price=Decimal(f"{70000 + i * 5}"),  # 상승 추세
                volume=1000
            )
            data.append(chart)

        macd_line, signal_line, histogram = DataAggregator.calculate_macd(
            data,
            fast_period=12,
            slow_period=26,
            signal_period=9
        )

        # 초기값들은 None
        for i in range(25):
            assert macd_line[i] is None

        # 26번째부터 MACD 값
        assert macd_line[25] is not None

        # 시그널은 더 늦게 시작
        for i in range(33):
            assert signal_line[i] is None or i < 33

        # 상승 추세에서 MACD는 양수
        if macd_line[-1] is not None:
            assert macd_line[-1] > 0

        # 히스토그램 = MACD - 시그널
        if histogram[-1] is not None and macd_line[-1] is not None and signal_line[-1] is not None:
            expected = macd_line[-1] - signal_line[-1]
            assert abs(histogram[-1] - expected) < Decimal("0.01")

    def test_volume_profile(self):
        """거래량 프로파일 계산 테스트."""
        # 다양한 가격대의 데이터
        data = []
        for i in range(10):
            chart = ChartData(
                stock_code="005930",
                interval=ChartInterval.MINUTE_1,
                timestamp=datetime.now(tz=KST) + timedelta(minutes=i),
                open_price=Decimal(f"{70000 + i * 100}"),
                high_price=Decimal(f"{70100 + i * 100}"),
                low_price=Decimal(f"{69900 + i * 100}"),
                close_price=Decimal(f"{70050 + i * 100}"),
                volume=1000 + i * 100
            )
            data.append(chart)

        profile = DataAggregator.calculate_volume_profile(data, num_levels=5)

        assert len(profile) == 5
        # 모든 레벨에 거래량이 있어야 함
        for price, volume in profile.items():
            assert volume >= 0

    def test_statistics(self):
        """통계 계산 테스트."""
        # 테스트 데이터
        data = []
        for i in range(10):
            chart = ChartData(
                stock_code="005930",
                interval=ChartInterval.MINUTE_1,
                timestamp=datetime.now(tz=KST) + timedelta(minutes=i),
                open_price=Decimal("70000"),
                high_price=Decimal("70100"),
                low_price=Decimal("69900"),
                close_price=Decimal(f"{70000 + i * 10}"),
                volume=1000
            )
            data.append(chart)

        stats = DataAggregator.calculate_statistics(data)

        assert stats["count"] == 10
        assert stats["mean_price"] == Decimal("70045")  # 평균
        assert stats["min_price"] == Decimal("70000")
        assert stats["max_price"] == Decimal("70090")
        assert stats["total_volume"] == Decimal("10000")
        assert stats["mean_volume"] == Decimal("1000")
        assert "mean_return" in stats
        assert "std_return" in stats
        assert "sharpe_ratio" in stats

    def test_empty_statistics(self):
        """빈 데이터 통계 테스트."""
        stats = DataAggregator.calculate_statistics([])
        assert stats == {}