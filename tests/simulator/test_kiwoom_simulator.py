"""KiwoomSimulator 테스트 모듈.

KiwoomSimulator의 잔고 관리, 포지션 관리, 오류 시나리오를 검증합니다.
"""

from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.simulator.kiwoom_simulator import KiwoomSimulator
from src.models import OrderType, OrderStatus, PriceType
from src.models.order import Order

KST = ZoneInfo("Asia/Seoul")


class TestKiwoomSimulatorBalanceManagement:
    """KiwoomSimulator 잔고 관리 테스트 (T025)."""

    def test_buy_order_decreases_cash_balance(self):
        """매수 주문 체결 후 예수금이 감소하는지 확인."""
        # Given: 시뮬레이터 초기화 (초기 예수금: 10,000,000원)
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
        simulator.exchange.set_price("005930", Decimal("72000"))

        # When: 100주 매수 주문 (예상 비용: 72,000 * 100 = 7,200,000원)
        order = Order(
            account_number=simulator.account.account_number,
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )

        simulator.submit_order(order)

        # Then: 예수금이 감소함
        account = simulator.get_account()
        # 매수 시 ask price로 체결되므로 약간 더 높은 가격
        assert account.cash_balance < Decimal("10000000")
        assert account.cash_balance > Decimal("2000000")  # 최소한 2백만원은 남음

    def test_sell_order_increases_cash_balance(self):
        """매도 주문 체결 후 예수금이 증가하는지 확인."""
        # Given: 시뮬레이터에 포지션 생성 (매수 후)
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
        simulator.exchange.set_price("005930", Decimal("72000"))

        # 먼저 100주 매수
        buy_order = Order(
            account_number=simulator.account.account_number,
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )
        simulator.submit_order(buy_order)

        # 매수 후 잔고 확인
        account_after_buy = simulator.get_account()
        balance_after_buy = account_after_buy.cash_balance

        # When: 50주 매도 주문
        sell_order = Order(
            account_number=simulator.account.account_number,
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.MARKET,
            quantity=50
        )
        simulator.submit_order(sell_order)

        # Then: 예수금이 증가함
        account_after_sell = simulator.get_account()
        assert account_after_sell.cash_balance > balance_after_buy

    def test_total_asset_value_calculation(self):
        """총 평가액이 예수금 + 포지션 평가액으로 정확히 계산되는지 확인."""
        # Given: 시뮬레이터 초기화 및 매수
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
        simulator.exchange.set_price("005930", Decimal("72000"))

        order = Order(
            account_number=simulator.account.account_number,
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )
        simulator.submit_order(order)

        # When: 계좌 정보 조회
        account = simulator.get_account()
        positions = simulator.get_positions()

        # Then: 총 평가액 = 예수금 + 포지션 평가액
        total_position_value = sum(pos.evaluation_amount for pos in positions)
        expected_total = account.cash_balance + total_position_value

        assert account.total_asset_value == expected_total

    def test_insufficient_balance_rejects_order(self):
        """예수금 부족 시 주문이 거부되는지 확인."""
        # Given: 시뮬레이터 초기화 (예수금: 1,000,000원)
        simulator = KiwoomSimulator(initial_balance=Decimal("1000000"))
        simulator.exchange.set_price("005930", Decimal("72000"))

        # When: 예수금을 초과하는 주문 (100주 * 72,000 = 7,200,000원)
        order = Order(
            account_number=simulator.account.account_number,
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )

        # Then: ValueError 발생
        with pytest.raises(ValueError, match="Insufficient balance"):
            simulator.submit_order(order)


class TestKiwoomSimulatorPositionManagement:
    """KiwoomSimulator 포지션 관리 테스트 (T026)."""

    def test_buy_order_creates_position(self):
        """매수 주문 체결 후 포지션이 생성되는지 확인."""
        # Given: 시뮬레이터 초기화
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
        simulator.exchange.set_price("005930", Decimal("72000"))

        # When: 매수 주문
        order = Order(
            account_number=simulator.account.account_number,
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )
        simulator.submit_order(order)

        # Then: 포지션이 생성됨
        positions = simulator.get_positions()
        assert len(positions) == 1
        assert positions[0].stock_code == "005930"
        assert positions[0].quantity == 100
        assert positions[0].average_buy_price > Decimal("0")

    def test_additional_buy_increases_position_quantity(self):
        """추가 매수 시 포지션 수량이 증가하는지 확인."""
        # Given: 시뮬레이터에 기존 포지션 생성 (초기 예수금 충분히 설정)
        simulator = KiwoomSimulator(initial_balance=Decimal("20000000"))
        simulator.exchange.set_price("005930", Decimal("50000"))

        # 첫 번째 매수: 100주
        order1 = Order(
            account_number=simulator.account.account_number,
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )
        simulator.submit_order(order1)

        # When: 추가 매수: 50주
        order2 = Order(
            account_number=simulator.account.account_number,
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=50
        )
        simulator.submit_order(order2)

        # Then: 포지션 수량이 150주로 증가
        positions = simulator.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == 150

    def test_sell_order_decreases_position_quantity(self):
        """매도 주문 체결 후 포지션 수량이 감소하는지 확인."""
        # Given: 시뮬레이터에 포지션 생성
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
        simulator.exchange.set_price("005930", Decimal("72000"))

        # 매수: 100주
        buy_order = Order(
            account_number=simulator.account.account_number,
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )
        simulator.submit_order(buy_order)

        # When: 매도: 30주
        sell_order = Order(
            account_number=simulator.account.account_number,
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.MARKET,
            quantity=30
        )
        simulator.submit_order(sell_order)

        # Then: 포지션 수량이 70주로 감소
        positions = simulator.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == 70

    def test_full_sell_removes_position(self):
        """전량 매도 시 포지션이 제거되는지 확인."""
        # Given: 시뮬레이터에 포지션 생성
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
        simulator.exchange.set_price("005930", Decimal("72000"))

        # 매수: 100주
        buy_order = Order(
            account_number=simulator.account.account_number,
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )
        simulator.submit_order(buy_order)

        # When: 전량 매도: 100주
        sell_order = Order(
            account_number=simulator.account.account_number,
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.MARKET,
            quantity=100
        )
        simulator.submit_order(sell_order)

        # Then: 포지션이 제거됨
        positions = simulator.get_positions()
        assert len(positions) == 0

    def test_insufficient_position_quantity_rejects_sell(self):
        """보유 수량 부족 시 매도 주문이 거부되는지 확인."""
        # Given: 시뮬레이터에 포지션 생성 (50주 보유)
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
        simulator.exchange.set_price("005930", Decimal("72000"))

        buy_order = Order(
            account_number=simulator.account.account_number,
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=50
        )
        simulator.submit_order(buy_order)

        # When: 보유 수량을 초과하는 매도 주문 (100주)
        sell_order = Order(
            account_number=simulator.account.account_number,
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.MARKET,
            quantity=100
        )

        # Then: ValueError 발생
        with pytest.raises(ValueError, match="Insufficient quantity"):
            simulator.submit_order(sell_order)

    def test_sell_without_position_rejects_order(self):
        """포지션 없이 매도 주문 시 거부되는지 확인."""
        # Given: 시뮬레이터 초기화 (포지션 없음)
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
        simulator.exchange.set_price("005930", Decimal("72000"))

        # When: 매도 주문
        sell_order = Order(
            account_number=simulator.account.account_number,
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.MARKET,
            quantity=100
        )

        # Then: ValueError 발생
        with pytest.raises(ValueError, match="No position found"):
            simulator.submit_order(sell_order)


class TestKiwoomSimulatorErrorScenarios:
    """KiwoomSimulator 오류 시나리오 테스트 (T027)."""

    def test_injected_insufficient_balance_error(self):
        """예수금 부족 에러 주입 시 주문이 거부되는지 확인."""
        # Given: 시뮬레이터 초기화
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
        simulator.exchange.set_price("005930", Decimal("72000"))

        # When: 예수금 부족 에러 주입
        simulator.inject_error("insufficient_balance")

        order = Order(
            account_number=simulator.account.account_number,
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )

        # Then: ValueError 발생 (예수금 부족)
        with pytest.raises(ValueError, match="Insufficient balance"):
            simulator.submit_order(order)

    def test_injected_invalid_stock_code_error(self):
        """잘못된 종목 코드 에러 주입 시 오류 발생 확인."""
        # Given: 시뮬레이터 초기화
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
        simulator.exchange.set_price("005930", Decimal("72000"))

        # When: 잘못된 종목 코드 에러 주입
        simulator.inject_error("invalid_stock_code")

        order = Order(
            account_number=simulator.account.account_number,
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )

        # Then: ValueError 발생
        with pytest.raises(ValueError, match="Invalid stock code"):
            simulator.submit_order(order)

    def test_injected_api_timeout_error(self):
        """API 타임아웃 에러 주입 시 TimeoutError 발생 확인."""
        # Given: 시뮬레이터 초기화
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
        simulator.exchange.set_price("005930", Decimal("72000"))

        # When: API 타임아웃 에러 주입
        simulator.inject_error("api_timeout")

        order = Order(
            account_number=simulator.account.account_number,
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )

        # Then: TimeoutError 발생
        with pytest.raises(TimeoutError, match="timeout"):
            simulator.submit_order(order)

    def test_invalid_stock_code_without_injection(self):
        """실제로 존재하지 않는 종목 코드로 주문 시 오류 발생 확인."""
        # Given: 시뮬레이터 초기화 (종목 가격 설정 안 함)
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))

        # When: 존재하지 않는 종목으로 주문
        order = Order(
            account_number=simulator.account.account_number,
            stock_code="999999",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )

        # Then: ValueError 발생
        with pytest.raises(ValueError, match="Invalid stock code"):
            simulator.submit_order(order)

    def test_get_stock_price_for_nonexistent_stock(self):
        """존재하지 않는 종목의 시세 조회 시 오류 발생 확인."""
        # Given: 시뮬레이터 초기화
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))

        # When: 존재하지 않는 종목 조회
        # Then: ValueError 발생
        with pytest.raises(ValueError, match="not found"):
            simulator.get_stock_price("999999")

    def test_error_injection_can_be_cleared(self):
        """오류 주입을 None으로 설정하여 해제할 수 있는지 확인."""
        # Given: 시뮬레이터 초기화
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
        simulator.exchange.set_price("005930", Decimal("72000"))

        # When: API 타임아웃 에러 주입
        simulator.inject_error("api_timeout")

        # 첫 번째 호출에서 타임아웃 에러 발생
        with pytest.raises(TimeoutError):
            simulator.get_stock_price("005930")

        # 오류 주입 해제
        simulator._injected_error = None

        # Then: 오류 해제 후 정상 작동
        stock = simulator.get_stock_price("005930")
        assert stock.stock_code == "005930"
        assert stock.current_price == Decimal("72000")
