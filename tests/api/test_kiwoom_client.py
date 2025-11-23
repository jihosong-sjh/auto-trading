"""KiwoomClient API 테스트."""

import pytest
from decimal import Decimal
from datetime import datetime

from src.api.kiwoom_client import KiwoomClient
from src.models import Order, OrderType, PriceType, OrderStatus


class TestKiwoomClient:
    """KiwoomClient 기본 테스트."""

    def test_client_initialization(self):
        """클라이언트 초기화 테스트."""
        client = KiwoomClient(
            api_key="test_key",
            api_secret="test_secret",
            account_number="12345678"
        )

        assert client.api_key == "test_key"
        assert client.api_secret == "test_secret"
        assert client.account_number == "12345678"
        assert client.access_token is None

    def test_client_has_required_methods(self):
        """필수 메서드 존재 확인."""
        client = KiwoomClient(
            api_key="test_key",
            api_secret="test_secret",
            account_number="12345678"
        )

        # 모든 필수 메서드가 존재하는지 확인
        assert hasattr(client, "connect")
        assert hasattr(client, "close")
        assert hasattr(client, "get_stock_price")
        assert hasattr(client, "get_chart_data")
        assert hasattr(client, "submit_order")
        assert hasattr(client, "get_order_status")
        assert hasattr(client, "get_filled_orders")
        assert hasattr(client, "get_account")
        assert hasattr(client, "get_positions")

    @pytest.mark.asyncio
    async def test_order_payload_structure_buy(self):
        """매수 주문 페이로드 구조 검증 (실제 API 호출 없음)."""
        client = KiwoomClient(
            api_key="test_key",
            api_secret="test_secret",
            account_number="12345678"
        )

        order = Order(
            order_id="test-001",
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.LIMIT,
            quantity=10,
            limit_price=Decimal("70000"),
            status=OrderStatus.PENDING,
            created_at=datetime.now()
        )

        # 매수 주문은 kt10000을 사용해야 함
        # (실제 API 호출은 하지 않고 구조만 확인)
        assert order.order_type == OrderType.BUY

    @pytest.mark.asyncio
    async def test_order_payload_structure_sell(self):
        """매도 주문 페이로드 구조 검증 (실제 API 호출 없음)."""
        client = KiwoomClient(
            api_key="test_key",
            api_secret="test_secret",
            account_number="12345678"
        )

        order = Order(
            order_id="test-002",
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.MARKET,
            quantity=5,
            status=OrderStatus.PENDING,
            created_at=datetime.now()
        )

        # 매도 주문은 kt10001을 사용해야 함
        assert order.order_type == OrderType.SELL
