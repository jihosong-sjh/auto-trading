"""Phase 6 Integration Tests.

OrderExecutor order_event_queue 소비 및
StrategyEngine order_book_queue 소비 테스트.
"""

import asyncio
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from src.models import OrderStatus, OrderType, PriceType
from src.models.order import Order
from src.models.position import Position
from src.models.realtime_data import (
    BalanceUpdateData,
    OrderBookData,
    OrderExecutionData,
)
from src.services.order_executor import OrderExecutor
from src.strategies.order_book_imbalance import OrderBookImbalanceStrategy

KST = ZoneInfo("Asia/Seoul")


class TestOrderExecutorPhase6:
    """OrderExecutor Phase 6 테스트."""

    @pytest.fixture
    def mock_client(self):
        """Mock Kiwoom client."""
        client = MagicMock()
        client.get_account = AsyncMock(return_value=MagicMock(
            account_number="12345678",
            cash_balance=Decimal("10000000"),
            total_asset_value=Decimal("10000000"),
            daily_pnl=Decimal("0")
        ))
        client.get_stock_price = AsyncMock(return_value=MagicMock(
            stock_code="005930",
            current_price=Decimal("70000")
        ))
        return client

    @pytest.fixture
    def pending_orders(self):
        """Pending orders dictionary."""
        return {}

    @pytest.fixture
    def positions(self):
        """Positions dictionary."""
        return {}

    @pytest.fixture
    def order_event_queue(self):
        """Order event queue."""
        return asyncio.Queue()

    @pytest.fixture
    def executor(self, mock_client, pending_orders, positions, order_event_queue):
        """OrderExecutor instance."""
        return OrderExecutor(
            client=mock_client,
            pending_orders=pending_orders,
            positions=positions,
            order_event_queue=order_event_queue
        )

    @pytest.mark.asyncio
    async def test_handle_order_execution_event_filled(
        self, executor, pending_orders
    ):
        """주문 체결 이벤트 처리 테스트."""
        # 진행 중인 주문 추가
        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=10,
            order_id="ORD001"
        )
        order.status = OrderStatus.SUBMITTED
        pending_orders["ORD001"] = order

        # 체결 이벤트 생성
        event = OrderExecutionData(
            account_number="12345678",
            order_id="ORD001",
            stock_code="005930",
            order_status="체결",
            filled_quantity=10,
            filled_price=Decimal("70000"),
            unfilled_quantity=0,
            timestamp=datetime.now(KST)
        )

        # 이벤트 처리
        await executor._handle_order_execution_event(event)

        # 검증: 주문 상태 업데이트
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == 10
        assert order.filled_price == Decimal("70000")
        # 검증: pending에서 제거
        assert "ORD001" not in pending_orders

    @pytest.mark.asyncio
    async def test_handle_order_execution_event_rejected(
        self, executor, pending_orders
    ):
        """주문 거부 이벤트 처리 테스트."""
        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=10,
            order_id="ORD002"
        )
        order.status = OrderStatus.SUBMITTED
        pending_orders["ORD002"] = order

        event = OrderExecutionData(
            account_number="12345678",
            order_id="ORD002",
            stock_code="005930",
            order_status="거부",
            filled_quantity=0,
            filled_price=Decimal("0"),
            reject_reason="잔고 부족",
            timestamp=datetime.now(KST)
        )

        await executor._handle_order_execution_event(event)

        assert order.status == OrderStatus.REJECTED
        assert "ORD002" not in pending_orders

    @pytest.mark.asyncio
    async def test_handle_balance_update_new_position(
        self, executor, positions
    ):
        """신규 포지션 이벤트 처리 테스트."""
        event = BalanceUpdateData(
            account_number="12345678",
            stock_code="005930",
            action="I",  # 신규
            holding_quantity=10,
            average_price=Decimal("70000"),
            current_price=Decimal("71000"),
            timestamp=datetime.now(KST)
        )

        await executor._handle_balance_update_event(event)

        # 검증: 신규 포지션 생성
        assert "005930" in positions
        assert positions["005930"].quantity == 10
        assert positions["005930"].average_buy_price == Decimal("70000")

    @pytest.mark.asyncio
    async def test_handle_balance_update_position_closed(
        self, executor, positions
    ):
        """포지션 청산 이벤트 처리 테스트."""
        # 기존 포지션 추가
        positions["005930"] = Position(
            account_number="12345678",
            stock_code="005930",
            quantity=10,
            average_buy_price=Decimal("70000"),
            current_price=Decimal("71000")
        )

        event = BalanceUpdateData(
            account_number="12345678",
            stock_code="005930",
            action="D",  # 삭제
            holding_quantity=0,
            average_price=Decimal("0"),
            current_price=Decimal("71000"),
            realized_pnl=Decimal("10000"),
            realized_pnl_rate=Decimal("1.43"),
            timestamp=datetime.now(KST)
        )

        await executor._handle_balance_update_event(event)

        # 검증: 포지션 삭제
        assert "005930" not in positions

    @pytest.mark.asyncio
    async def test_run_consumes_events(self, executor, order_event_queue):
        """run() 메서드가 이벤트를 소비하는지 테스트."""
        # 이벤트 추가
        event = OrderExecutionData(
            account_number="12345678",
            order_id="ORD999",
            stock_code="005930",
            order_status="접수",
            filled_quantity=0,
            filled_price=Decimal("0"),
            timestamp=datetime.now(KST)
        )
        await order_event_queue.put(event)

        # run() 시작
        run_task = asyncio.create_task(executor.run())

        # 이벤트 처리 대기
        await asyncio.sleep(0.5)

        # 정지
        await executor.stop()
        run_task.cancel()

        try:
            await run_task
        except asyncio.CancelledError:
            pass

        # 검증: 큐가 비어있어야 함
        assert order_event_queue.empty()


class TestStrategyEnginePhase6:
    """StrategyEngine Phase 6 테스트."""

    @pytest.fixture
    def order_book_queue(self):
        """Order book queue."""
        return asyncio.Queue()

    @pytest.fixture
    def order_book_strategy(self):
        """OrderBookImbalance strategy."""
        return OrderBookImbalanceStrategy(
            buy_threshold=0.3,
            sell_threshold=-0.2,
            max_spread_pct=0.005
        )

    def test_order_book_imbalance_strategy_set_order_book(
        self, order_book_strategy
    ):
        """OrderBookImbalanceStrategy.set_order_book() 테스트."""
        from src.models.order_book import OrderBook, OrderBookLevel

        order_book = OrderBook(
            stock_code="005930",
            ask_levels=[
                OrderBookLevel(price=Decimal("70100"), quantity=1000),
                OrderBookLevel(price=Decimal("70200"), quantity=2000),
            ],
            bid_levels=[
                OrderBookLevel(price=Decimal("70000"), quantity=3000),
                OrderBookLevel(price=Decimal("69900"), quantity=4000),
            ],
            total_ask_quantity=3000,
            total_bid_quantity=7000,
            timestamp=datetime.now(KST)
        )

        order_book_strategy.set_order_book("005930", order_book)

        # 검증
        cached = order_book_strategy.get_order_book("005930")
        assert cached is not None
        assert cached.stock_code == "005930"
        assert cached.total_bid_quantity == 7000

    @pytest.mark.asyncio
    async def test_order_book_imbalance_buy_signal(self, order_book_strategy):
        """호가 불균형 매수 신호 테스트."""
        from src.models.order_book import OrderBook, OrderBookLevel
        from src.models.stock import Stock

        # 매수 우세 호가창 설정 (30% 이상 불균형)
        order_book = OrderBook(
            stock_code="005930",
            ask_levels=[
                OrderBookLevel(price=Decimal("70100"), quantity=1000),
            ],
            bid_levels=[
                OrderBookLevel(price=Decimal("70000"), quantity=3000),
            ],
            total_ask_quantity=1000,
            total_bid_quantity=3000,  # 불균형 = (3000-1000)/4000 = 50%
            timestamp=datetime.now(KST)
        )
        order_book_strategy.set_order_book("005930", order_book)

        stock = Stock(
            stock_code="005930",
            stock_name="삼성전자",
            current_price=Decimal("70050"),
            market="KOSPI"
        )

        # 매수 신호 평가
        signal = await order_book_strategy.evaluate_buy_signal(stock)

        # 검증: 매수 우세(50% > 30%)이므로 신호 발생
        assert signal is True

    @pytest.mark.asyncio
    async def test_order_book_imbalance_no_signal(self, order_book_strategy):
        """호가 불균형 신호 없음 테스트."""
        from src.models.order_book import OrderBook, OrderBookLevel
        from src.models.stock import Stock

        # 균형 잡힌 호가창
        order_book = OrderBook(
            stock_code="005930",
            ask_levels=[
                OrderBookLevel(price=Decimal("70100"), quantity=2000),
            ],
            bid_levels=[
                OrderBookLevel(price=Decimal("70000"), quantity=2000),
            ],
            total_ask_quantity=2000,
            total_bid_quantity=2000,  # 불균형 = 0%
            timestamp=datetime.now(KST)
        )
        order_book_strategy.set_order_book("005930", order_book)

        stock = Stock(
            stock_code="005930",
            stock_name="삼성전자",
            current_price=Decimal("70050"),
            market="KOSPI"
        )

        signal = await order_book_strategy.evaluate_buy_signal(stock)

        # 검증: 불균형 없으므로 신호 없음
        assert signal is False


class TestDataFlow:
    """데이터 흐름 통합 테스트."""

    @pytest.mark.asyncio
    async def test_order_event_queue_flow(self):
        """order_event_queue 데이터 흐름 테스트."""
        # Setup
        order_event_queue = asyncio.Queue()
        pending_orders = {}
        positions = {}

        mock_client = MagicMock()
        mock_client.get_account = AsyncMock(return_value=MagicMock(
            account_number="12345678",
            cash_balance=Decimal("10000000")
        ))

        mock_account_service = MagicMock()
        mock_account_service.refresh_account = AsyncMock()

        executor = OrderExecutor(
            client=mock_client,
            pending_orders=pending_orders,
            positions=positions,
            order_event_queue=order_event_queue,
            account_service=mock_account_service
        )

        # 주문 추가
        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=10,
            order_id="TEST001"
        )
        order.status = OrderStatus.SUBMITTED
        pending_orders["TEST001"] = order

        # 이벤트 큐에 체결 이벤트 추가
        event = OrderExecutionData(
            account_number="12345678",
            order_id="TEST001",
            stock_code="005930",
            order_status="체결",
            filled_quantity=10,
            filled_price=Decimal("70000"),
            unfilled_quantity=0,
            timestamp=datetime.now(KST)
        )
        await order_event_queue.put(event)

        # 잔고 업데이트 이벤트도 추가
        balance_event = BalanceUpdateData(
            account_number="12345678",
            stock_code="005930",
            action="I",
            holding_quantity=10,
            average_price=Decimal("70000"),
            current_price=Decimal("70500"),
            timestamp=datetime.now(KST)
        )
        await order_event_queue.put(balance_event)

        # Executor 실행
        run_task = asyncio.create_task(executor.run())
        await asyncio.sleep(0.5)
        await executor.stop()
        run_task.cancel()

        try:
            await run_task
        except asyncio.CancelledError:
            pass

        # 검증
        assert "TEST001" not in pending_orders  # 체결 완료로 제거됨
        assert order.status == OrderStatus.FILLED
        assert "005930" in positions  # 포지션 생성됨
        assert positions["005930"].quantity == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
