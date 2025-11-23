"""데이터 수집 → 전략 평가 통합 테스트 (T077).

T077 테스트 범위:
- DataCollector가 시세 데이터를 수집하여 큐에 전달
- 전략 엔진이 큐에서 데이터를 수신하여 매수/매도 시그널 평가
- 전체 데이터 플로우가 정상적으로 동작하는지 검증
"""

import asyncio
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from src.config.settings import Settings
from src.models import ChartInterval, MarketType, OrderType, PriceType, Stock
from src.models.chart_data import ChartData
from src.models.strategy import BaseStrategy
from src.services.data_collector import DataCollector
from src.simulator.kiwoom_simulator import KiwoomSimulator

KST = ZoneInfo("Asia/Seoul")


# 테스트용 간단한 전략
class SimpleThresholdStrategy(BaseStrategy):
    """단순 임계값 기반 전략.

    매수: 현재가가 50,000원 이하일 때
    매도: 현재가가 55,000원 이상일 때
    """

    def __init__(self, buy_threshold: Decimal, sell_threshold: Decimal):
        """전략 초기화.

        Args:
            buy_threshold: 매수 임계가.
            sell_threshold: 매도 임계가.
        """
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    async def evaluate_buy_signal(self, stock: Stock) -> bool:
        """매수 시그널 평가.

        Args:
            stock: 종목 데이터.

        Returns:
            매수 시그널 여부.
        """
        return stock.current_price <= self.buy_threshold

    async def evaluate_sell_signal(self, stock: Stock) -> bool:
        """매도 시그널 평가.

        Args:
            stock: 종목 데이터.

        Returns:
            매도 시그널 여부.
        """
        return stock.current_price >= self.sell_threshold

    def calculate_position_size(self, available_balance: Decimal, stock_price: Decimal) -> int:
        """포지션 크기 계산.

        Args:
            available_balance: 사용 가능 잔고.
            stock_price: 주식 가격.

        Returns:
            매수 수량.
        """
        # 잔고의 50%를 사용
        budget = available_balance * Decimal("0.5")
        quantity = int(budget / stock_price)
        return max(quantity, 0)


# Mock Kiwoom 클라이언트 (가변 시세 지원)
class MockKiwoomClientWithPriceControl:
    """테스트용 Mock Kiwoom 클라이언트 (시세 조작 가능)."""

    def __init__(self):
        self.prices = {
            "005930": Decimal("52000.00"),  # 초기가: 52,000원
            "000660": Decimal("48000.00"),  # 초기가: 48,000원
        }

    def set_price(self, stock_code: str, price: Decimal):
        """시세 변경.

        Args:
            stock_code: 종목코드.
            price: 새로운 가격.
        """
        self.prices[stock_code] = price

    async def get_stock_price(self, stock_code: str) -> Stock:
        """종목 시세 조회.

        Args:
            stock_code: 종목코드.

        Returns:
            Stock 데이터.
        """
        return Stock(
            stock_code=stock_code,
            stock_name=f"종목{stock_code}",
            market=MarketType.KOSPI,
            current_price=self.prices.get(stock_code, Decimal("50000.00")),
            volume=1000000,
            updated_at=datetime.now(tz=KST)
        )

    async def get_chart_data(
        self,
        stock_code: str,
        interval: ChartInterval = ChartInterval.DAY
    ) -> list[ChartData]:
        """차트 데이터 조회 (Dummy).

        Args:
            stock_code: 종목코드.
            interval: 차트 주기.

        Returns:
            ChartData 리스트.
        """
        return []


# Fixtures
@pytest.fixture
def mock_config():
    """Mock 설정."""
    return Settings(
        kiwoom_appkey="test_key",
        kiwoom_appsecret="test_secret",
        initial_balance=Decimal("10000000"),
        daily_loss_limit=Decimal("500000"),
        max_position_concentration=Decimal("0.3")
    )


@pytest.fixture
def mock_client_with_control():
    """Mock Kiwoom 클라이언트 (가격 조작 가능)."""
    return MockKiwoomClientWithPriceControl()


@pytest.fixture
def market_data_queue():
    """시장 데이터 큐."""
    return asyncio.Queue()


# =============================================================================
# 통합 테스트
# =============================================================================

@pytest.mark.asyncio
async def test_data_collection_to_strategy_evaluation(
    mock_config,
    mock_client_with_control,
    market_data_queue
):
    """데이터 수집 → 전략 평가 통합 테스트.

    시나리오:
    1. StaggeredPricePoller가 005930 종목 시세를 폴링
    2. 큐에 데이터가 전달됨
    3. 전략이 큐에서 데이터를 받아 매수/매도 시그널 평가
    4. 시세 변동에 따라 시그널이 변경됨
    """
    # 1. StaggeredPricePoller 직접 사용 (DataCollector의 run() 없이)
    from src.services.data_collector import StaggeredPricePoller

    stock_codes = ["005930"]
    poller = StaggeredPricePoller(
        client=mock_client_with_control,
        stock_codes=stock_codes,
        market_data_queue=market_data_queue,
        interval_seconds=0.5  # 빠른 테스트
    )

    # 폴링 시작
    await poller.start()

    # 2. 큐에서 첫 번째 데이터 수신
    stock_data = await asyncio.wait_for(market_data_queue.get(), timeout=3.0)

    assert stock_data.stock_code == "005930"
    assert stock_data.current_price == Decimal("52000.00")

    # 3. 전략 평가 (매수 시그널 체크)
    strategy = SimpleThresholdStrategy(
        buy_threshold=Decimal("50000.00"),  # 50,000원 이하 매수
        sell_threshold=Decimal("55000.00")   # 55,000원 이상 매도
    )

    # 현재가 52,000원 → 매수 안 함
    buy_signal = await strategy.evaluate_buy_signal(stock_data)
    assert buy_signal is False

    # 4. 시세 변경: 48,000원으로 하락
    mock_client_with_control.set_price("005930", Decimal("48000.00"))

    # 다음 폴링 대기
    await asyncio.sleep(1.0)

    # 큐에서 업데이트된 데이터 수신
    stock_data_updated = await asyncio.wait_for(market_data_queue.get(), timeout=3.0)

    assert stock_data_updated.current_price == Decimal("48000.00")

    # 매수 시그널 체크 (48,000원 ≤ 50,000원 → 매수)
    buy_signal_updated = await strategy.evaluate_buy_signal(stock_data_updated)
    assert buy_signal_updated is True

    # 5. 시세 변경: 56,000원으로 상승
    mock_client_with_control.set_price("005930", Decimal("56000.00"))

    await asyncio.sleep(1.0)

    stock_data_high = await asyncio.wait_for(market_data_queue.get(), timeout=3.0)

    assert stock_data_high.current_price == Decimal("56000.00")

    # 매도 시그널 체크 (56,000원 ≥ 55,000원 → 매도)
    sell_signal = await strategy.evaluate_sell_signal(stock_data_high)
    assert sell_signal is True

    # 정리
    await poller.stop()


@pytest.mark.asyncio
async def test_multiple_stocks_data_flow(
    mock_config,
    mock_client_with_control,
    market_data_queue
):
    """다중 종목 데이터 플로우 테스트.

    시나리오:
    1. 두 종목(005930, 000660)을 동시 폴링
    2. 큐에서 두 종목 데이터 모두 수신
    3. 각 종목에 대해 전략 평가
    """
    stock_codes = ["005930", "000660"]
    collector = DataCollector(
        config=mock_config,
        client=mock_client_with_control,
        market_data_queue=market_data_queue,
        stock_codes=stock_codes
    )

    # 데이터 수집 시작
    collector_task = asyncio.create_task(collector.run())

    await asyncio.sleep(0.5)

    # 수신된 데이터 수집 (최소 2개 이상)
    received_stocks = []
    for _ in range(4):  # 2개 종목 x 2회 폴링
        try:
            stock = await asyncio.wait_for(market_data_queue.get(), timeout=2.0)
            received_stocks.append(stock)
        except asyncio.TimeoutError:
            break

    # 최소 2개 종목 데이터 수신 확인
    assert len(received_stocks) >= 2

    # 두 종목 모두 수신 확인
    stock_codes_received = {s.stock_code for s in received_stocks}
    assert "005930" in stock_codes_received
    assert "000660" in stock_codes_received

    # 전략 평가
    strategy = SimpleThresholdStrategy(
        buy_threshold=Decimal("50000.00"),
        sell_threshold=Decimal("55000.00")
    )

    for stock in received_stocks:
        buy_signal = await strategy.evaluate_buy_signal(stock)
        sell_signal = await strategy.evaluate_sell_signal(stock)

        # 시그널이 boolean 값인지 확인
        assert isinstance(buy_signal, bool)
        assert isinstance(sell_signal, bool)

    # 정리
    await collector.stop()
    try:
        await asyncio.wait_for(collector_task, timeout=2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass


@pytest.mark.asyncio
async def test_strategy_with_position_size_calculation(
    mock_config,
    mock_client_with_control,
    market_data_queue
):
    """포지션 크기 계산 통합 테스트.

    시나리오:
    1. 시세 데이터 수신
    2. 매수 시그널 발생 시 포지션 크기 계산
    """
    from src.services.data_collector import StaggeredPricePoller

    stock_codes = ["005930"]
    poller = StaggeredPricePoller(
        client=mock_client_with_control,
        stock_codes=stock_codes,
        market_data_queue=market_data_queue,
        interval_seconds=0.5
    )

    await poller.start()
    await asyncio.sleep(0.5)

    # 시세 데이터 수신
    stock_data = await asyncio.wait_for(market_data_queue.get(), timeout=3.0)

    # 전략 초기화
    strategy = SimpleThresholdStrategy(
        buy_threshold=Decimal("55000.00"),  # 현재가(52,000원)보다 높게 설정 → 매수
        sell_threshold=Decimal("60000.00")
    )

    # 매수 시그널 체크
    buy_signal = await strategy.evaluate_buy_signal(stock_data)
    assert buy_signal is True

    # 포지션 크기 계산 (잔고의 50% 사용)
    available_balance = Decimal("10000000")  # 1천만원
    position_size = strategy.calculate_position_size(available_balance, stock_data.current_price)

    # 기대값: (10,000,000 * 0.5) / 52,000 = 96.15... → 96주
    assert position_size == 96

    # 정리
    await poller.stop()
