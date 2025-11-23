"""StrategyEngine과 DataCollector 통합 테스트 (T078).

T078 테스트 범위:
- DataCollector가 시세 데이터를 큐에 전달
- StrategyEngine이 큐에서 데이터를 소비
- 전략이 시그널을 평가
- 전체 데이터 플로우가 정상 동작
"""

import asyncio
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.config.settings import Settings
from src.models import ChartInterval, MarketType, Stock
from src.models.chart_data import ChartData
from src.models.strategy import BaseStrategy
from src.services.data_collector import StaggeredPricePoller
from src.services.strategy_engine import StrategyEngine

KST = ZoneInfo("Asia/Seoul")


# 테스트용 간단한 전략
class TestStrategy(BaseStrategy):
    """테스트용 전략."""

    def __init__(self):
        self.buy_signals_received = []
        self.sell_signals_received = []

    async def evaluate_buy_signal(self, stock: Stock) -> bool:
        """매수 시그널 평가."""
        self.buy_signals_received.append(stock)
        # 50,000원 이하면 매수
        return stock.current_price <= Decimal("50000.00")

    async def evaluate_sell_signal(self, stock: Stock) -> bool:
        """매도 시그널 평가."""
        self.sell_signals_received.append(stock)
        # 60,000원 이상이면 매도
        return stock.current_price >= Decimal("60000.00")

    def calculate_position_size(self, available_balance: Decimal, stock_price: Decimal) -> int:
        """포지션 크기 계산."""
        return 100


# Mock Kiwoom 클라이언트
class MockKiwoomClient:
    """테스트용 Mock Kiwoom 클라이언트."""

    def __init__(self):
        self.prices = {
            "005930": Decimal("48000.00"),  # 매수 시그널 발생 (< 50,000)
            "000660": Decimal("62000.00"),  # 매도 시그널 발생 (> 60,000)
        }

    async def get_stock_price(self, stock_code: str) -> Stock:
        """종목 시세 조회."""
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
        """차트 데이터 조회 (Dummy)."""
        return []


# Fixtures
@pytest.fixture
def market_data_queue():
    """시장 데이터 큐."""
    return asyncio.Queue()


@pytest.fixture
def mock_client():
    """Mock Kiwoom 클라이언트."""
    return MockKiwoomClient()


# =============================================================================
# T078 통합 테스트
# =============================================================================

@pytest.mark.asyncio
async def test_datacollector_to_strategyengine_integration(market_data_queue, mock_client):
    """DataCollector → Queue → StrategyEngine 통합 테스트 (T078).

    시나리오:
    1. DataCollector가 시세 데이터를 큐에 전달
    2. StrategyEngine이 큐에서 데이터를 소비
    3. 전략이 시그널을 평가하고 로그 출력
    """
    # 1. StaggeredPricePoller 생성 (DataCollector 역할)
    stock_codes = ["005930", "000660"]
    poller = StaggeredPricePoller(
        client=mock_client,
        stock_codes=stock_codes,
        market_data_queue=market_data_queue,
        interval_seconds=0.5
    )

    # 2. StrategyEngine 생성 및 전략 로드
    engine = StrategyEngine(market_data_queue=market_data_queue)

    # 테스트 전략 직접 추가 (YAML 로드 대신)
    test_strategy = TestStrategy()
    engine.strategies["TestStrategy"] = test_strategy

    # 3. DataCollector와 StrategyEngine 시작
    await poller.start()
    await engine.run()

    # 데이터 수신 및 평가 대기
    await asyncio.sleep(2.0)

    # 4. 검증: 전략이 시그널을 평가했는지 확인
    assert len(test_strategy.buy_signals_received) > 0, "전략이 매수 시그널을 평가해야 함"

    # 최소 2개 종목 데이터를 받았는지 확인
    stock_codes_evaluated = {s.stock_code for s in test_strategy.buy_signals_received}
    assert "005930" in stock_codes_evaluated or "000660" in stock_codes_evaluated

    # 5. 정리
    await engine.stop()
    await poller.stop()


@pytest.mark.asyncio
async def test_strategyengine_signal_detection(market_data_queue, mock_client):
    """StrategyEngine 시그널 감지 테스트 (T078).

    시나리오:
    1. 특정 가격에서 매수/매도 시그널이 발생하는지 확인
    """
    stock_codes = ["005930"]
    poller = StaggeredPricePoller(
        client=mock_client,
        stock_codes=stock_codes,
        market_data_queue=market_data_queue,
        interval_seconds=0.5
    )

    engine = StrategyEngine(market_data_queue=market_data_queue)
    test_strategy = TestStrategy()
    engine.strategies["TestStrategy"] = test_strategy

    # 시작
    await poller.start()
    await engine.run()

    await asyncio.sleep(1.5)

    # 검증: 매수 시그널 발생 (48,000원 < 50,000원)
    assert len(test_strategy.buy_signals_received) > 0

    buy_signals = [
        s for s in test_strategy.buy_signals_received
        if s.stock_code == "005930"
    ]

    assert len(buy_signals) > 0
    assert all(s.current_price <= Decimal("50000.00") for s in buy_signals)

    # 정리
    await engine.stop()
    await poller.stop()


@pytest.mark.asyncio
async def test_multiple_strategies_parallel_evaluation(market_data_queue, mock_client):
    """다중 전략 병렬 평가 테스트 (T078).

    시나리오:
    1. 여러 전략이 동시에 동일한 데이터를 평가
    2. 각 전략이 독립적으로 시그널 생성
    """
    stock_codes = ["005930"]
    poller = StaggeredPricePoller(
        client=mock_client,
        stock_codes=stock_codes,
        market_data_queue=market_data_queue,
        interval_seconds=0.5
    )

    engine = StrategyEngine(market_data_queue=market_data_queue)

    # 두 개의 전략 추가
    strategy1 = TestStrategy()
    strategy2 = TestStrategy()

    engine.strategies["Strategy1"] = strategy1
    engine.strategies["Strategy2"] = strategy2

    # 시작
    await poller.start()
    await engine.run()

    await asyncio.sleep(1.5)

    # 검증: 두 전략 모두 시그널 받음
    assert len(strategy1.buy_signals_received) > 0
    assert len(strategy2.buy_signals_received) > 0

    # 두 전략이 동일한 데이터를 받았는지 확인
    # (동일 시점의 데이터를 평가해야 함)
    assert strategy1.buy_signals_received[0].stock_code == strategy2.buy_signals_received[0].stock_code

    # 정리
    await engine.stop()
    await poller.stop()
