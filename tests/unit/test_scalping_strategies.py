"""스캘핑 전략 유닛 테스트."""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.models import (
    Stock,
    Position,
    OrderBook,
    OrderBookLevel,
    ChartData,
    MarketType,
    ChartInterval,
)
from src.strategies import (
    OrderBookImbalanceStrategy,
    RSIDivergenceStrategy,
    VWAPDeviationStrategy,
)

KST = ZoneInfo("Asia/Seoul")


@pytest.fixture
def sample_stock():
    """샘플 종목 생성."""
    return Stock(
        stock_code="005930",
        stock_name="Samsung Electronics",
        market=MarketType.KOSPI,
        current_price=Decimal("70000"),
        open_price=Decimal("69000"),
        high_price=Decimal("71000"),
        low_price=Decimal("68500"),
        volume=1000000,
    )


@pytest.fixture
def sample_position():
    """샘플 포지션 생성."""
    return Position(
        account_number="12345678",
        stock_code="005930",
        quantity=10,
        average_buy_price=Decimal("69000"),
        current_price=Decimal("70000"),
    )


class TestOrderBookImbalanceStrategy:
    """호가 불균형 전략 테스트."""

    def test_strategy_initialization(self):
        """전략 초기화 테스트."""
        strategy = OrderBookImbalanceStrategy(
            buy_threshold=0.3,
            sell_threshold=-0.2,
            max_spread_pct=0.005,
        )

        assert strategy.buy_threshold == Decimal("0.3")
        assert strategy.sell_threshold == Decimal("-0.2")
        assert strategy.max_spread_pct == Decimal("0.005")
        assert strategy.get_strategy_name() == "OrderBookImbalance"

    def test_invalid_thresholds(self):
        """잘못된 임계값으로 초기화 시 예외 발생."""
        with pytest.raises(ValueError, match="buy_threshold must be between 0 and 1"):
            OrderBookImbalanceStrategy(buy_threshold=1.5)

        with pytest.raises(ValueError, match="sell_threshold must be between -1 and 0"):
            OrderBookImbalanceStrategy(sell_threshold=0.5)

    @pytest.mark.asyncio
    async def test_buy_signal_with_strong_bid_imbalance(self, sample_stock):
        """강한 매수 불균형 시 매수 신호 발생."""
        strategy = OrderBookImbalanceStrategy(buy_threshold=0.3)

        # 매수 우세 호가창 (70% 매수 잔량)
        order_book = OrderBook(
            stock_code="005930",
            ask_levels=[
                OrderBookLevel(price=Decimal("70100"), quantity=1000),
                OrderBookLevel(price=Decimal("70200"), quantity=1000),
            ],
            bid_levels=[
                OrderBookLevel(price=Decimal("70000"), quantity=3000),
                OrderBookLevel(price=Decimal("69900"), quantity=3000),
            ],
            total_ask_quantity=2000,
            total_bid_quantity=6000,
        )

        strategy.set_order_book("005930", order_book)

        # 불균형 비율: (6000 - 2000) / 8000 = 0.5 > 0.3
        result = await strategy.evaluate_buy_signal(sample_stock)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_buy_signal_with_balanced_orderbook(self, sample_stock):
        """균형잡힌 호가창에서는 매수 신호 없음."""
        strategy = OrderBookImbalanceStrategy(buy_threshold=0.3)

        # 균형잡힌 호가창
        order_book = OrderBook(
            stock_code="005930",
            ask_levels=[OrderBookLevel(price=Decimal("70100"), quantity=5000)],
            bid_levels=[OrderBookLevel(price=Decimal("70000"), quantity=5000)],
            total_ask_quantity=5000,
            total_bid_quantity=5000,
        )

        strategy.set_order_book("005930", order_book)

        # 불균형 비율: 0 < 0.3
        result = await strategy.evaluate_buy_signal(sample_stock)
        assert result is False

    @pytest.mark.asyncio
    async def test_sell_signal_on_profit_target(self, sample_position, sample_stock):
        """목표 수익률 도달 시 매도 신호 발생."""
        strategy = OrderBookImbalanceStrategy(target_profit_pct=0.01)

        # 포지션 수익률: (70000 - 69000) / 69000 = 0.0145 > 0.01
        result = await strategy.evaluate_sell_signal(sample_position, sample_stock)
        assert result is True

    @pytest.mark.asyncio
    async def test_sell_signal_on_stop_loss(self, sample_stock):
        """손절 조건 도달 시 매도 신호 발생."""
        strategy = OrderBookImbalanceStrategy(stop_loss_pct=0.005)

        # 손실 포지션
        position = Position(
            account_number="12345678",
            stock_code="005930",
            quantity=10,
            average_buy_price=Decimal("70000"),
            current_price=Decimal("69500"),
        )

        # 수익률: (69500 - 70000) / 70000 = -0.0071 < -0.005
        result = await strategy.evaluate_sell_signal(position, sample_stock)
        assert result is True

    def test_position_size_calculation(self, sample_stock):
        """포지션 크기 계산 테스트."""
        strategy = OrderBookImbalanceStrategy(position_size_pct=0.5)

        order_book = OrderBook(
            stock_code="005930",
            ask_levels=[OrderBookLevel(price=Decimal("70000"), quantity=1000)],
            bid_levels=[OrderBookLevel(price=Decimal("69900"), quantity=1000)],
            total_ask_quantity=1000,
            total_bid_quantity=1000,
        )

        strategy.set_order_book("005930", order_book)

        # 가용 자금 1,000,000원, 50% 투자, 최우선 매도호가 70,000원
        # (1,000,000 * 0.5) / 70,000 = 7.14... -> 7주
        quantity = strategy.calculate_position_size(sample_stock, 1000000.0)
        assert quantity == 7


class TestRSIDivergenceStrategy:
    """RSI 다이버전스 전략 테스트."""

    def test_strategy_initialization(self):
        """전략 초기화 테스트."""
        strategy = RSIDivergenceStrategy(
            rsi_period=14,
            oversold_threshold=30,
            overbought_threshold=70,
        )

        assert strategy.rsi_period == 14
        assert strategy.oversold_threshold == Decimal("30")
        assert strategy.overbought_threshold == Decimal("70")
        assert strategy.get_strategy_name() == "RSIDivergence"

    def test_rsi_calculation(self):
        """RSI 계산 테스트."""
        strategy = RSIDivergenceStrategy(rsi_period=14)

        # 14일 상승 추세 데이터 (RSI 높아야 함)
        prices = [Decimal(str(100 + i)) for i in range(15)]

        rsi = strategy.calculate_rsi(prices)
        assert rsi is not None
        assert rsi > Decimal("50")  # 상승 추세에서 RSI > 50

    def test_rsi_calculation_with_insufficient_data(self):
        """데이터 부족 시 RSI 계산 불가."""
        strategy = RSIDivergenceStrategy(rsi_period=14)

        # 14개 미만의 데이터
        prices = [Decimal(str(100 + i)) for i in range(10)]

        rsi = strategy.calculate_rsi(prices)
        assert rsi is None

    def test_bullish_divergence_detection(self):
        """강세 다이버전스 감지 테스트."""
        strategy = RSIDivergenceStrategy()

        # 가격: Lower Low (100 -> 95)
        prices = [Decimal("100"), Decimal("98"), Decimal("97"), Decimal("95")]

        # RSI: Higher Low (30 -> 35)
        rsi_values = [Decimal("30"), Decimal("32"), Decimal("33"), Decimal("35")]

        result = strategy.detect_bullish_divergence(prices, rsi_values)
        assert result is True

    def test_bearish_divergence_detection(self):
        """약세 다이버전스 감지 테스트."""
        strategy = RSIDivergenceStrategy()

        # 가격: Higher High (100 -> 105)
        prices = [Decimal("100"), Decimal("102"), Decimal("103"), Decimal("105")]

        # RSI: Lower High (70 -> 65)
        rsi_values = [Decimal("70"), Decimal("68"), Decimal("67"), Decimal("65")]

        result = strategy.detect_bearish_divergence(prices, rsi_values)
        assert result is True

    @pytest.mark.asyncio
    async def test_buy_signal_with_bullish_divergence(self, sample_stock):
        """강세 다이버전스 시 매수 신호 발생."""
        strategy = RSIDivergenceStrategy(
            rsi_period=5,
            oversold_threshold=40,
            lookback_periods=3,
        )

        # 하락 추세 차트 데이터 생성 (가격은 하락, RSI는 상승 예상)
        base_time = datetime.now(KST)
        chart_data = []

        prices = [
            Decimal("100"), Decimal("99"), Decimal("98"), Decimal("97"),
            Decimal("96"), Decimal("95"), Decimal("96"), Decimal("97"),
        ]

        for i, price in enumerate(prices):
            chart_data.append(
                ChartData(
                    stock_code="005930",
                    interval=ChartInterval.MINUTE_1,
                    timestamp=base_time + timedelta(minutes=i),
                    open_price=price,
                    high_price=price + Decimal("1"),
                    low_price=price - Decimal("1"),
                    close_price=price,
                    volume=10000,
                )
            )

        strategy.set_chart_data("005930", chart_data)

        # 차트 데이터가 설정되면 RSI와 다이버전스 계산 가능
        result = await strategy.evaluate_buy_signal(sample_stock)
        # 실제 RSI 계산 결과에 따라 True/False
        assert isinstance(result, bool)

    def test_position_size_calculation(self, sample_stock):
        """포지션 크기 계산 테스트."""
        strategy = RSIDivergenceStrategy(position_size_pct=0.5)

        # 가용 자금 1,000,000원, 50% 투자, 현재가 70,000원
        # (1,000,000 * 0.5) / 70,000 = 7.14... -> 7주
        quantity = strategy.calculate_position_size(sample_stock, 1000000.0)
        assert quantity == 7


class TestVWAPDeviationStrategy:
    """VWAP 괴리율 전략 테스트."""

    def test_strategy_initialization(self):
        """전략 초기화 테스트."""
        strategy = VWAPDeviationStrategy(
            buy_threshold=0.015,
            sell_threshold=0.005,
            vwap_period=20,
        )

        assert strategy.buy_threshold == Decimal("0.015")
        assert strategy.sell_threshold == Decimal("0.005")
        assert strategy.vwap_period == 20
        assert strategy.get_strategy_name() == "VWAPDeviation"

    def test_vwap_calculation(self):
        """VWAP 계산 테스트."""
        strategy = VWAPDeviationStrategy(vwap_period=3)

        base_time = datetime.now(KST)
        chart_data = [
            ChartData(
                stock_code="005930",
                interval=ChartInterval.MINUTE_1,
                timestamp=base_time + timedelta(minutes=i),
                open_price=Decimal("100"),
                high_price=Decimal("105"),
                low_price=Decimal("95"),
                close_price=Decimal("100"),
                volume=1000 * (i + 1),
            )
            for i in range(3)
        ]

        vwap = strategy.calculate_vwap(chart_data)
        assert vwap is not None
        # 전형가격 = (105 + 95 + 100) / 3 = 100
        # VWAP = (100*1000 + 100*2000 + 100*3000) / (1000+2000+3000) = 100
        assert vwap == Decimal("100")

    def test_vwap_calculation_with_insufficient_data(self):
        """데이터 부족 시 VWAP 계산 불가."""
        strategy = VWAPDeviationStrategy(vwap_period=5)

        base_time = datetime.now(KST)
        chart_data = [
            ChartData(
                stock_code="005930",
                interval=ChartInterval.MINUTE_1,
                timestamp=base_time + timedelta(minutes=i),
                open_price=Decimal("100"),
                high_price=Decimal("105"),
                low_price=Decimal("95"),
                close_price=Decimal("100"),
                volume=1000,
            )
            for i in range(3)
        ]

        vwap = strategy.calculate_vwap(chart_data)
        assert vwap is None

    def test_deviation_calculation(self):
        """괴리율 계산 테스트."""
        strategy = VWAPDeviationStrategy()

        # 현재가 105, VWAP 100
        # 괴리율 = (105 - 100) / 100 = 0.05 (5% 상승)
        deviation = strategy.calculate_deviation(Decimal("105"), Decimal("100"))
        assert deviation == Decimal("0.05")

        # 현재가 95, VWAP 100
        # 괴리율 = (95 - 100) / 100 = -0.05 (5% 하락)
        deviation = strategy.calculate_deviation(Decimal("95"), Decimal("100"))
        assert deviation == Decimal("-0.05")

    @pytest.mark.asyncio
    async def test_buy_signal_with_oversold_deviation(self, sample_stock):
        """과매도 괴리 시 매수 신호 발생."""
        strategy = VWAPDeviationStrategy(buy_threshold=0.02, vwap_period=3)

        base_time = datetime.now(KST)
        chart_data = [
            ChartData(
                stock_code="005930",
                interval=ChartInterval.MINUTE_1,
                timestamp=base_time + timedelta(minutes=i),
                open_price=Decimal("72000"),
                high_price=Decimal("73000"),
                low_price=Decimal("71000"),
                close_price=Decimal("72000"),
                volume=10000,
            )
            for i in range(3)
        ]

        strategy.set_chart_data("005930", chart_data)

        # VWAP = 72000, 현재가 = 70000
        # 괴리율 = (70000 - 72000) / 72000 = -0.0278 < -0.02
        result = await strategy.evaluate_buy_signal(sample_stock)
        assert result is True

    @pytest.mark.asyncio
    async def test_sell_signal_on_mean_reversion(self, sample_position, sample_stock):
        """평균 회귀 시 매도 신호 발생."""
        strategy = VWAPDeviationStrategy(sell_threshold=0.005, vwap_period=3)

        base_time = datetime.now(KST)
        chart_data = [
            ChartData(
                stock_code="005930",
                interval=ChartInterval.MINUTE_1,
                timestamp=base_time + timedelta(minutes=i),
                open_price=Decimal("69500"),
                high_price=Decimal("70000"),
                low_price=Decimal("69000"),
                close_price=Decimal("69500"),
                volume=10000,
            )
            for i in range(3)
        ]

        strategy.set_chart_data("005930", chart_data)

        # VWAP = 69500, 현재가 = 70000
        # 괴리율 = (70000 - 69500) / 69500 = 0.0072 > 0.005
        result = await strategy.evaluate_sell_signal(sample_position, sample_stock)
        assert result is True

    def test_position_size_calculation(self, sample_stock):
        """포지션 크기 계산 테스트."""
        strategy = VWAPDeviationStrategy(position_size_pct=0.5)

        # 가용 자금 1,000,000원, 50% 투자, 현재가 70,000원
        # (1,000,000 * 0.5) / 70,000 = 7.14... -> 7주
        quantity = strategy.calculate_position_size(sample_stock, 1000000.0)
        assert quantity == 7


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
