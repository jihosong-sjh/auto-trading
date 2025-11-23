"""DuplicateOrderChecker 단위 테스트."""

from decimal import Decimal

import pytest

from src.models import OrderStatus, OrderType, PriceType
from src.models.order import Order
from src.services.duplicate_checker import DuplicateOrderChecker


class TestDuplicateOrderChecker:
    """중복 주문 체크 테스트."""

    def test_check_duplicate_no_pending_orders(self):
        """진행 중인 주문이 없으면 중복 아님."""
        # Given
        pending_orders = {}
        checker = DuplicateOrderChecker(pending_orders)

        # When
        is_duplicate, existing_order_id = checker.check_duplicate("005930", OrderType.BUY)

        # Then
        assert is_duplicate is False
        assert existing_order_id is None

    def test_check_duplicate_different_stock(self):
        """다른 종목의 주문은 중복 아님."""
        # Given
        order1 = Order(
            account_number="12345678",
            stock_code="005930",  # 삼성전자
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100,
            status=OrderStatus.SUBMITTED
        )

        pending_orders = {order1.order_id: order1}
        checker = DuplicateOrderChecker(pending_orders)

        # When - 다른 종목 체크
        is_duplicate, existing_order_id = checker.check_duplicate("000660", OrderType.BUY)  # SK하이닉스

        # Then
        assert is_duplicate is False
        assert existing_order_id is None

    def test_check_duplicate_different_order_type(self):
        """같은 종목이지만 다른 주문 유형(매수/매도)은 중복 아님."""
        # Given
        order1 = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,  # 매수
            price_type=PriceType.MARKET,
            quantity=100,
            status=OrderStatus.SUBMITTED
        )

        pending_orders = {order1.order_id: order1}
        checker = DuplicateOrderChecker(pending_orders)

        # When - 매도 주문 체크
        is_duplicate, existing_order_id = checker.check_duplicate("005930", OrderType.SELL)

        # Then
        assert is_duplicate is False
        assert existing_order_id is None

    def test_check_duplicate_same_stock_and_type(self):
        """같은 종목, 같은 주문 유형의 진행 중인 주문이 있으면 중복."""
        # Given
        order1 = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100,
            status=OrderStatus.SUBMITTED
        )

        pending_orders = {order1.order_id: order1}
        checker = DuplicateOrderChecker(pending_orders)

        # When
        is_duplicate, existing_order_id = checker.check_duplicate("005930", OrderType.BUY)

        # Then
        assert is_duplicate is True
        assert existing_order_id == order1.order_id

    def test_check_duplicate_terminal_state_not_duplicate(self):
        """종료 상태(FILLED, CANCELLED 등)의 주문은 중복으로 간주하지 않음."""
        # Given
        filled_order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100,
            status=OrderStatus.FILLED  # 종료 상태
        )

        pending_orders = {filled_order.order_id: filled_order}
        checker = DuplicateOrderChecker(pending_orders)

        # When
        is_duplicate, existing_order_id = checker.check_duplicate("005930", OrderType.BUY)

        # Then
        assert is_duplicate is False
        assert existing_order_id is None

    def test_check_duplicate_multiple_terminal_states(self):
        """여러 종료 상태 주문이 있어도 중복 아님."""
        # Given
        cancelled_order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100,
            status=OrderStatus.CANCELLED
        )

        rejected_order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=50,
            status=OrderStatus.REJECTED
        )

        failed_order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=30,
            status=OrderStatus.FAILED
        )

        pending_orders = {
            cancelled_order.order_id: cancelled_order,
            rejected_order.order_id: rejected_order,
            failed_order.order_id: failed_order
        }
        checker = DuplicateOrderChecker(pending_orders)

        # When
        is_duplicate, existing_order_id = checker.check_duplicate("005930", OrderType.BUY)

        # Then
        assert is_duplicate is False
        assert existing_order_id is None

    def test_get_pending_order_count_empty(self):
        """진행 중인 주문이 없으면 0 반환."""
        # Given
        pending_orders = {}
        checker = DuplicateOrderChecker(pending_orders)

        # When
        count = checker.get_pending_order_count("005930")

        # Then
        assert count == 0

    def test_get_pending_order_count_one_pending(self):
        """진행 중인 주문이 1개 있으면 1 반환."""
        # Given
        order1 = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100,
            status=OrderStatus.SUBMITTED
        )

        pending_orders = {order1.order_id: order1}
        checker = DuplicateOrderChecker(pending_orders)

        # When
        count = checker.get_pending_order_count("005930")

        # Then
        assert count == 1

    def test_get_pending_order_count_multiple_types(self):
        """같은 종목에 대한 매수/매도 주문 모두 카운트."""
        # Given
        buy_order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100,
            status=OrderStatus.SUBMITTED
        )

        sell_order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.MARKET,
            quantity=50,
            status=OrderStatus.SUBMITTED
        )

        pending_orders = {
            buy_order.order_id: buy_order,
            sell_order.order_id: sell_order
        }
        checker = DuplicateOrderChecker(pending_orders)

        # When
        count = checker.get_pending_order_count("005930")

        # Then
        assert count == 2

    def test_get_pending_order_count_excludes_terminal_states(self):
        """종료 상태의 주문은 카운트하지 않음."""
        # Given
        pending_order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100,
            status=OrderStatus.SUBMITTED
        )

        filled_order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=50,
            status=OrderStatus.FILLED
        )

        pending_orders = {
            pending_order.order_id: pending_order,
            filled_order.order_id: filled_order
        }
        checker = DuplicateOrderChecker(pending_orders)

        # When
        count = checker.get_pending_order_count("005930")

        # Then
        assert count == 1  # FILLED 주문은 제외

    def test_has_pending_buy_order_true(self):
        """진행 중인 매수 주문이 있으면 True."""
        # Given
        buy_order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100,
            status=OrderStatus.SUBMITTED
        )

        pending_orders = {buy_order.order_id: buy_order}
        checker = DuplicateOrderChecker(pending_orders)

        # When
        has_buy = checker.has_pending_buy_order("005930")

        # Then
        assert has_buy is True

    def test_has_pending_buy_order_false(self):
        """진행 중인 매수 주문이 없으면 False."""
        # Given
        pending_orders = {}
        checker = DuplicateOrderChecker(pending_orders)

        # When
        has_buy = checker.has_pending_buy_order("005930")

        # Then
        assert has_buy is False

    def test_has_pending_sell_order_true(self):
        """진행 중인 매도 주문이 있으면 True."""
        # Given
        sell_order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.MARKET,
            quantity=100,
            status=OrderStatus.SUBMITTED
        )

        pending_orders = {sell_order.order_id: sell_order}
        checker = DuplicateOrderChecker(pending_orders)

        # When
        has_sell = checker.has_pending_sell_order("005930")

        # Then
        assert has_sell is True

    def test_has_pending_sell_order_false(self):
        """진행 중인 매도 주문이 없으면 False."""
        # Given
        pending_orders = {}
        checker = DuplicateOrderChecker(pending_orders)

        # When
        has_sell = checker.has_pending_sell_order("005930")

        # Then
        assert has_sell is False
