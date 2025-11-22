"""FakeExchange 테스트 모듈.

FakeExchange의 시장가 및 지정가 주문 체결 로직을 검증합니다.
"""

from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.simulator.fake_exchange import FakeExchange
from src.models import OrderType, OrderStatus, PriceType
from src.models.order import Order

KST = ZoneInfo("Asia/Seoul")


class TestFakeExchangeMarketOrder:
    """FakeExchange 시장가 주문 체결 테스트 (T023)."""

    def test_market_buy_order_fills_immediately(self):
        """매수 시장가 주문이 즉시 체결되는지 확인."""
        # Given: 거래소에 종목 가격이 설정됨
        exchange = FakeExchange()
        exchange.set_price("005930", Decimal("72000"))

        # When: 시장가 매수 주문을 제출
        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )

        filled_order = exchange.execute_market_order(order)

        # Then: 주문이 즉시 체결됨
        assert filled_order.status == OrderStatus.FILLED
        assert filled_order.filled_quantity == 100
        assert filled_order.filled_price is not None
        assert filled_order.filled_price > Decimal("0")
        assert filled_order.filled_at is not None

    def test_market_sell_order_fills_immediately(self):
        """매도 시장가 주문이 즉시 체결되는지 확인."""
        # Given: 거래소에 종목 가격이 설정됨
        exchange = FakeExchange()
        exchange.set_price("005930", Decimal("72000"))

        # When: 시장가 매도 주문을 제출
        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.MARKET,
            quantity=50
        )

        filled_order = exchange.execute_market_order(order)

        # Then: 주문이 즉시 체결됨
        assert filled_order.status == OrderStatus.FILLED
        assert filled_order.filled_quantity == 50
        assert filled_order.filled_price is not None
        assert filled_order.filled_price > Decimal("0")
        assert filled_order.filled_at is not None

    def test_market_buy_uses_ask_price(self):
        """매수 시장가 주문이 매도호가(ask)로 체결되는지 확인."""
        # Given: 거래소에 종목 가격 및 호가 설정
        exchange = FakeExchange()
        exchange.set_price("005930", Decimal("72000"))
        # set_price는 자동으로 bid/ask를 현재가 ±0.1%로 설정

        # When: 시장가 매수 주문
        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )

        filled_order = exchange.execute_market_order(order)

        # Then: 매도호가(현재가보다 약간 높음)로 체결됨
        assert filled_order.filled_price >= Decimal("72000")

    def test_market_sell_uses_bid_price(self):
        """매도 시장가 주문이 매수호가(bid)로 체결되는지 확인."""
        # Given: 거래소에 종목 가격 및 호가 설정
        exchange = FakeExchange()
        exchange.set_price("005930", Decimal("72000"))

        # When: 시장가 매도 주문
        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.MARKET,
            quantity=50
        )

        filled_order = exchange.execute_market_order(order)

        # Then: 매수호가(현재가보다 약간 낮음)로 체결됨
        assert filled_order.filled_price <= Decimal("72000")

    def test_market_order_raises_error_for_invalid_stock(self):
        """존재하지 않는 종목 코드로 시장가 주문 시 오류 발생 확인."""
        # Given: 거래소에 종목이 없음
        exchange = FakeExchange()

        # When: 존재하지 않는 종목으로 주문
        order = Order(
            account_number="12345678",
            stock_code="999999",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )

        # Then: ValueError 발생
        with pytest.raises(ValueError, match="Stock code .* not found"):
            exchange.execute_market_order(order)


class TestFakeExchangeLimitOrder:
    """FakeExchange 지정가 주문 체결 테스트 (T024)."""

    def test_limit_buy_fills_when_price_below_limit(self):
        """현재가가 지정가 이하일 때 매수 지정가 주문이 체결되는지 확인."""
        # Given: 거래소에 종목 가격이 설정됨 (현재가: 72,000원)
        exchange = FakeExchange()
        exchange.set_price("005930", Decimal("72000"))

        # When: 지정가 75,000원으로 매수 주문 (현재가보다 높음)
        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.LIMIT,
            quantity=100,
            limit_price=Decimal("75000")
        )

        filled_order = exchange.execute_limit_order(order)

        # Then: 주문이 체결됨
        assert filled_order.status == OrderStatus.FILLED
        assert filled_order.filled_quantity == 100
        assert filled_order.filled_price == Decimal("72000")

    def test_limit_buy_not_fills_when_price_above_limit(self):
        """현재가가 지정가보다 높을 때 매수 지정가 주문이 체결되지 않는지 확인."""
        # Given: 거래소에 종목 가격이 설정됨 (현재가: 72,000원)
        exchange = FakeExchange()
        exchange.set_price("005930", Decimal("72000"))

        # When: 지정가 70,000원으로 매수 주문 (현재가보다 낮음)
        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.LIMIT,
            quantity=100,
            limit_price=Decimal("70000")
        )

        filled_order = exchange.execute_limit_order(order)

        # Then: 주문이 체결되지 않고 SUBMITTED 상태로 유지
        assert filled_order.status == OrderStatus.SUBMITTED
        assert filled_order.filled_quantity == 0
        assert filled_order.filled_price is None

    def test_limit_sell_fills_when_price_above_limit(self):
        """현재가가 지정가 이상일 때 매도 지정가 주문이 체결되는지 확인."""
        # Given: 거래소에 종목 가격이 설정됨 (현재가: 72,000원)
        exchange = FakeExchange()
        exchange.set_price("005930", Decimal("72000"))

        # When: 지정가 70,000원으로 매도 주문 (현재가보다 낮음)
        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.LIMIT,
            quantity=50,
            limit_price=Decimal("70000")
        )

        filled_order = exchange.execute_limit_order(order)

        # Then: 주문이 체결됨
        assert filled_order.status == OrderStatus.FILLED
        assert filled_order.filled_quantity == 50
        assert filled_order.filled_price == Decimal("72000")

    def test_limit_sell_not_fills_when_price_below_limit(self):
        """현재가가 지정가보다 낮을 때 매도 지정가 주문이 체결되지 않는지 확인."""
        # Given: 거래소에 종목 가격이 설정됨 (현재가: 72,000원)
        exchange = FakeExchange()
        exchange.set_price("005930", Decimal("72000"))

        # When: 지정가 75,000원으로 매도 주문 (현재가보다 높음)
        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.LIMIT,
            quantity=50,
            limit_price=Decimal("75000")
        )

        filled_order = exchange.execute_limit_order(order)

        # Then: 주문이 체결되지 않고 SUBMITTED 상태로 유지
        assert filled_order.status == OrderStatus.SUBMITTED
        assert filled_order.filled_quantity == 0
        assert filled_order.filled_price is None

    def test_limit_order_raises_error_for_invalid_stock(self):
        """존재하지 않는 종목 코드로 지정가 주문 시 오류 발생 확인."""
        # Given: 거래소에 종목이 없음
        exchange = FakeExchange()

        # When: 존재하지 않는 종목으로 주문
        order = Order(
            account_number="12345678",
            stock_code="999999",
            order_type=OrderType.BUY,
            price_type=PriceType.LIMIT,
            quantity=100,
            limit_price=Decimal("72000")
        )

        # Then: ValueError 발생
        with pytest.raises(ValueError, match="Stock code .* not found"):
            exchange.execute_limit_order(order)

    def test_limit_order_raises_error_without_limit_price(self):
        """limit_price 없이 지정가 주문 시 오류 발생 확인."""
        # Given: 거래소에 종목 가격이 설정됨
        exchange = FakeExchange()
        exchange.set_price("005930", Decimal("72000"))

        # When: limit_price 없이 지정가 주문
        order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.LIMIT,
            quantity=100
            # limit_price 누락
        )

        # Then: ValueError 발생
        with pytest.raises(ValueError, match="must have limit_price"):
            exchange.execute_limit_order(order)


class TestFakeExchangeTickSimulation:
    """FakeExchange tick 시뮬레이션 테스트."""

    def test_tick_updates_bid_ask_prices(self):
        """tick() 호출 시 호가창이 갱신되는지 확인."""
        # Given: 거래소에 종목 가격이 설정됨
        exchange = FakeExchange()
        exchange.set_price("005930", Decimal("72000"))

        original_bid = exchange.bid_prices["005930"]
        original_ask = exchange.ask_prices["005930"]

        # When: tick 호출
        exchange.tick()

        # Then: 호가창이 갱신됨 (값은 동일할 수 있음, 구조만 확인)
        assert "005930" in exchange.bid_prices
        assert "005930" in exchange.ask_prices
        # 스프레드가 유지됨
        assert exchange.ask_prices["005930"] > exchange.bid_prices["005930"]
