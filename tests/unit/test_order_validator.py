"""OrderValidator 단위 테스트."""

from decimal import Decimal

import pytest

from src.models import OrderType, PriceType
from src.models.account import Account
from src.models.order import Order
from src.models.position import Position
from src.services.order_validator import OrderValidator


class TestOrderValidatorBuyOrders:
    """매수 주문 검증 테스트."""

    def test_validate_buy_order_success(self):
        """정상적인 매수 주문 검증 성공."""
        # Given
        account = Account(
            account_number="12345678",
            name="테스트계좌",
            cash_balance=Decimal("10000000"),
            total_asset_value=Decimal("10000000"),
            daily_loss_limit=Decimal("500000")
        )

        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )

        current_price = Decimal("70000")

        # When
        validator = OrderValidator()
        is_valid, error_msg = validator.validate_buy_order(account, order, current_price)

        # Then
        assert is_valid is True
        assert error_msg is None

    def test_validate_buy_order_insufficient_balance(self):
        """예수금 부족으로 매수 주문 검증 실패."""
        # Given
        account = Account(
            account_number="12345678",
            name="테스트계좌",
            cash_balance=Decimal("1000000"),  # 100만원
            total_asset_value=Decimal("1000000"),
            daily_loss_limit=Decimal("500000")
        )

        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )

        current_price = Decimal("70000")  # 100주 = 700만원 필요

        # When
        validator = OrderValidator()
        is_valid, error_msg = validator.validate_buy_order(account, order, current_price)

        # Then
        assert is_valid is False
        assert "예수금 부족" in error_msg

    def test_validate_buy_order_daily_loss_limit_exceeded(self):
        """일일 손실 한도 초과로 매수 주문 검증 실패."""
        # Given
        account = Account(
            account_number="12345678",
            name="테스트계좌",
            cash_balance=Decimal("10000000"),
            total_asset_value=Decimal("10000000"),
            daily_pnl=Decimal("-600000"),  # -60만원 손실
            daily_loss_limit=Decimal("500000")  # 한도 50만원
        )

        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )

        current_price = Decimal("70000")

        # When
        validator = OrderValidator()
        is_valid, error_msg = validator.validate_buy_order(account, order, current_price)

        # Then
        assert is_valid is False
        assert "일일 손실 한도 초과" in error_msg


class TestOrderValidatorSellOrders:
    """매도 주문 검증 테스트."""

    def test_validate_sell_order_success(self):
        """정상적인 매도 주문 검증 성공."""
        # Given
        position = Position(
            account_number="12345678",
            stock_code="005930",
            quantity=150,
            average_buy_price=Decimal("70000"),
            current_price=Decimal("72000")
        )

        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.MARKET,
            quantity=100
        )

        # When
        validator = OrderValidator()
        is_valid, error_msg = validator.validate_sell_order(position, order)

        # Then
        assert is_valid is True
        assert error_msg is None

    def test_validate_sell_order_no_position(self):
        """포지션 없음으로 매도 주문 검증 실패."""
        # Given
        position = None  # 보유 포지션 없음

        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.MARKET,
            quantity=100
        )

        # When
        validator = OrderValidator()
        is_valid, error_msg = validator.validate_sell_order(position, order)

        # Then
        assert is_valid is False
        assert "보유 포지션이 없습니다" in error_msg

    def test_validate_sell_order_insufficient_quantity(self):
        """보유 수량 부족으로 매도 주문 검증 실패."""
        # Given
        position = Position(
            account_number="12345678",
            stock_code="005930",
            quantity=50,  # 50주만 보유
            average_buy_price=Decimal("70000"),
            current_price=Decimal("72000")
        )

        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.MARKET,
            quantity=100  # 100주 매도 시도
        )

        # When
        validator = OrderValidator()
        is_valid, error_msg = validator.validate_sell_order(position, order)

        # Then
        assert is_valid is False
        assert "보유 수량 부족" in error_msg


class TestOrderValidatorPriceValidation:
    """주문 가격 검증 테스트."""

    def test_validate_order_price_market_order(self):
        """시장가 주문은 limit_price 불필요."""
        # Given
        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
            # limit_price 없음
        )

        # When
        validator = OrderValidator()
        is_valid, error_msg = validator.validate_order_price(order)

        # Then
        assert is_valid is True
        assert error_msg is None

    def test_validate_order_price_limit_order_success(self):
        """지정가 주문에 limit_price가 있으면 성공."""
        # Given
        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.LIMIT,
            quantity=100,
            limit_price=Decimal("70000")
        )

        # When
        validator = OrderValidator()
        is_valid, error_msg = validator.validate_order_price(order)

        # Then
        assert is_valid is True
        assert error_msg is None

    def test_validate_order_price_limit_order_missing_price(self):
        """지정가 주문에 limit_price가 없으면 실패."""
        # Given
        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.LIMIT,
            quantity=100
            # limit_price 없음
        )

        # When
        validator = OrderValidator()
        is_valid, error_msg = validator.validate_order_price(order)

        # Then
        assert is_valid is False
        assert "limit_price가 필수입니다" in error_msg

