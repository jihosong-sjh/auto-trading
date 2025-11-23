"""키움증권 API Contract Test.

실제 KiwoomClient와 KiwoomSimulator가 동일한 데이터 모델을 반환하는지 검증합니다.
"""

import pytest
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo

from src.models import (
    Account,
    Order,
    OrderStatus,
    OrderType,
    Position,
    PriceType,
    Stock,
)
from src.simulator.kiwoom_simulator import KiwoomSimulator

KST = ZoneInfo("Asia/Seoul")


class TestAccountContract:
    """Account 응답 형식 계약 테스트 (T060)."""

    @pytest.mark.asyncio
    async def test_simulator_returns_valid_account(self):
        """Simulator가 유효한 Account 모델을 반환하는지 테스트."""
        # Given: Simulator 초기화
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))

        # When: 계좌 정보 조회
        account = await simulator.get_account()

        # Then: Account 모델 검증
        assert isinstance(account, Account)
        assert account.account_number == "99999999"
        assert account.cash_balance == Decimal("10000000")
        assert account.total_asset_value == Decimal("10000000")
        assert account.total_pnl == Decimal("0")
        assert account.daily_pnl == Decimal("0")
        assert isinstance(account.updated_at, datetime)

    def test_api_response_schema_matches_account_model(self):
        """실제 API 응답이 Account 모델과 호환되는지 테스트."""
        # Given: 실제 API의 예상 응답 (kt00001)
        api_response = {
            "account_number": "12345678",
            "name": "홍길동",
            "cash_balance": "5000000",
            "total_asset_value": "6000000",
            "total_pnl": "1000000",
            "daily_pnl": "50000",
            "daily_loss_limit": "300000",
            "updated_at": datetime.now(tz=KST),
        }

        # When: Account 모델로 파싱
        account = Account(**api_response)

        # Then: 파싱 성공 및 타입 검증
        assert isinstance(account, Account)
        assert account.account_number == "12345678"
        assert account.cash_balance == Decimal("5000000")
        assert account.total_asset_value == Decimal("6000000")


class TestOrderContract:
    """Order 응답 형식 계약 테스트 (T061)."""

    @pytest.mark.asyncio
    async def test_simulator_returns_valid_order(self):
        """Simulator가 유효한 Order 모델을 반환하는지 테스트."""
        # Given: Simulator 초기화 및 시세 설정
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
        simulator.exchange.set_price("005930", Decimal("70000"))

        # Given: 매수 주문
        order = Order(
            order_id="ORD001",
            account_number="99999999",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=10,
            created_at=datetime.now(tz=KST),
        )

        # When: 주문 제출
        filled_order = await simulator.submit_order(order)

        # Then: Order 모델 검증
        assert isinstance(filled_order, Order)
        assert filled_order.order_id == "ORD001"
        assert filled_order.status == OrderStatus.FILLED
        assert filled_order.filled_quantity == 10
        # 시장가 매수는 매도호가(ask)로 체결 = 70000 + 0.1% = 70070
        assert filled_order.filled_price == Decimal("70070.000")

    def test_api_response_schema_matches_order_model(self):
        """실제 API 응답이 Order 모델과 호환되는지 테스트."""
        # Given: 실제 API의 예상 응답 (kt10000/kt10001)
        api_response = {
            "order_id": "20231201-001",
            "account_number": "12345678",
            "stock_code": "005930",
            "order_type": OrderType.BUY,
            "price_type": PriceType.LIMIT,
            "quantity": 10,
            "limit_price": "70000",
            "status": OrderStatus.PENDING,
            "filled_quantity": 0,
            "filled_price": None,
            "created_at": datetime.now(tz=KST),
            "submitted_at": datetime.now(tz=KST),
            "filled_at": None,
        }

        # When: Order 모델로 파싱
        order = Order(**api_response)

        # Then: 파싱 성공 및 타입 검증
        assert isinstance(order, Order)
        assert order.order_id == "20231201-001"
        assert order.quantity == 10
        assert order.limit_price == Decimal("70000")


class TestPositionContract:
    """Position 응답 형식 계약 테스트 (T062)."""

    @pytest.mark.asyncio
    async def test_simulator_returns_valid_position(self):
        """Simulator가 유효한 Position 모델을 반환하는지 테스트."""
        # Given: Simulator 초기화 및 매수
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
        simulator.exchange.set_price("005930", Decimal("70000"))

        order = Order(
            order_id="ORD001",
            account_number="99999999",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=10,
            created_at=datetime.now(tz=KST),
        )
        await simulator.submit_order(order)

        # When: 포지션 조회
        positions = simulator.get_positions()

        # Then: Position 모델 검증
        assert len(positions) == 1
        position = positions[0]
        assert isinstance(position, Position)
        assert position.stock_code == "005930"
        assert position.quantity == 10
        # 시장가 매수는 70070에 체결되었으므로 평균매수가도 70070
        assert position.average_buy_price == Decimal("70070.000")
        # 현재가는 설정한 70000
        assert position.current_price == Decimal("70000")

    def test_api_response_schema_matches_position_model(self):
        """실제 API 응답이 Position 모델과 호환되는지 테스트."""
        # Given: 실제 API의 예상 응답 (kt00018)
        api_response = {
            "account_number": "12345678",
            "stock_code": "005930",
            "quantity": 10,
            "average_buy_price": "70000",
            "current_price": "72000",
            "opened_at": datetime.now(tz=KST),
            "updated_at": datetime.now(tz=KST),
        }

        # When: Position 모델로 파싱
        position = Position(**api_response)

        # Then: 파싱 성공 및 타입 검증
        assert isinstance(position, Position)
        assert position.stock_code == "005930"
        assert position.quantity == 10
        assert position.average_buy_price == Decimal("70000")
        assert position.current_price == Decimal("72000")


class TestStockContract:
    """Stock 응답 형식 계약 테스트 (T063)."""

    @pytest.mark.asyncio
    async def test_simulator_returns_valid_stock(self):
        """Simulator가 유효한 Stock 모델을 반환하는지 테스트."""
        # Given: Simulator 초기화 및 시세 설정
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
        simulator.exchange.set_price("005930", Decimal("70000"))

        # When: 시세 조회
        stock = await simulator.get_stock_price("005930")

        # Then: Stock 모델 검증
        assert isinstance(stock, Stock)
        assert stock.stock_code == "005930"
        assert stock.current_price == Decimal("70000")

    def test_api_response_schema_matches_stock_model(self):
        """실제 API 응답이 Stock 모델과 호환되는지 테스트."""
        # Given: 실제 API의 예상 응답 (ka10006)
        api_response = {
            "stock_code": "005930",
            "stock_name": "삼성전자",
            "market": "KOSPI",
            "current_price": "70000",
            "open_price": "69500",
            "high_price": "71000",
            "low_price": "69000",
            "volume": 1000000,
            "updated_at": datetime.now(tz=KST),
        }

        # When: Stock 모델로 파싱
        stock = Stock(**api_response)

        # Then: 파싱 성공 및 타입 검증
        assert isinstance(stock, Stock)
        assert stock.stock_code == "005930"
        assert stock.current_price == Decimal("70000")
        assert stock.volume == 1000000


class TestErrorContract:
    """에러 응답 형식 계약 테스트 (T064)."""

    @pytest.mark.asyncio
    async def test_simulator_raises_insufficient_balance_error(self):
        """Simulator가 예수금 부족 시 에러를 발생시키는지 테스트."""
        # Given: 잔액이 부족한 Simulator
        simulator = KiwoomSimulator(initial_balance=Decimal("1000"))
        simulator.exchange.set_price("005930", Decimal("70000"))

        # Given: 예수금 초과 매수 주문
        order = Order(
            order_id="ORD001",
            account_number="99999999",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=10,
            created_at=datetime.now(tz=KST),
        )

        # When/Then: 예수금 부족 에러 발생
        with pytest.raises(ValueError, match="Insufficient balance"):
            await simulator.submit_order(order)

    @pytest.mark.asyncio
    async def test_simulator_raises_invalid_stock_code_error(self):
        """Simulator가 잘못된 종목코드 시 에러를 발생시키는지 테스트."""
        # Given: Simulator 초기화
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))

        # When/Then: 등록되지 않은 종목 조회 시 에러 발생
        with pytest.raises(ValueError, match="Stock code .* not found"):
            await simulator.get_stock_price("999999")

    @pytest.mark.asyncio
    async def test_simulator_handles_injected_timeout_error(self):
        """Simulator가 타임아웃 에러를 시뮬레이션할 수 있는지 테스트."""
        # Given: Simulator 초기화 및 시세 설정
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
        simulator.exchange.set_price("005930", Decimal("70000"))

        # Given: 타임아웃 에러 주입
        simulator.inject_error("api_timeout")

        # Given: 매수 주문
        order = Order(
            order_id="ORD001",
            account_number="99999999",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=10,
            created_at=datetime.now(tz=KST),
        )

        # When/Then: 타임아웃 에러 발생
        with pytest.raises(TimeoutError, match="timeout"):
            await simulator.submit_order(order)
