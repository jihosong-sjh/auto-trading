"""전략 실행 → 주문 생성 → 체결 통합 테스트.

Simulator를 사용하여 전체 거래 플로우를 검증합니다.
"""

from decimal import Decimal

import pytest

from src.models import OrderStatus, OrderType, PriceType
from src.models.order import Order
from src.services.order_executor import OrderExecutor
from src.simulator.kiwoom_simulator import KiwoomSimulator


class TestTradingFlowSync:
    """전략 실행부터 주문 체결까지 전체 플로우 테스트 (Sync)."""

    @pytest.mark.asyncio
    async def test_buy_order_execution_flow_sync(self):
        """매수 주문 실행 플로우 테스트 (동기식).

        1. Simulator 초기화 (초기 자금 1천만원)
        2. 종목 가격 설정
        3. 매수 주문 생성
        4. submit_order로 주문 실행
        5. 주문 체결 확인
        6. 계좌 잔고 감소 확인
        7. 포지션 생성 확인
        """
        # Given
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))

        # 삼성전자 가격 설정
        simulator.exchange.set_price("005930", Decimal("70000"))

        # 매수 주문 생성
        buy_order = Order(
            account_number="99999999",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )

        # When
        filled_order = await simulator.submit_order(buy_order)

        # Then
        assert filled_order.filled_quantity == 100
        # FakeExchange가 시장가 주문 시 슬리피지 추가 (약 0.1%)
        assert filled_order.filled_price > Decimal("70000")
        assert filled_order.status == OrderStatus.FILLED

        # 계좌 확인 (슬리피지 때문에 정확한 금액은 다를 수 있음)
        account = await simulator.get_account()
        assert account.cash_balance < Decimal("10000000")  # 초기 자금보다 적어야 함
        assert account.cash_balance > Decimal("2900000")  # 최소한 이 정도는 남아야 함

        # 포지션 확인
        positions_list = simulator.get_positions()
        assert len(positions_list) == 1
        assert positions_list[0].stock_code == "005930"
        assert positions_list[0].quantity == 100
        # 슬리피지로 인해 평균 매수가가 설정가보다 약간 높음
        assert positions_list[0].average_buy_price >= Decimal("70000")

    @pytest.mark.asyncio
    async def test_complete_trading_cycle_sync(self):
        """완전한 거래 사이클 테스트: 매수 → 보유 → 가격 상승 → 매도 → 수익 확인."""
        # Given
        initial_balance = Decimal("10000000")
        simulator = KiwoomSimulator(initial_balance=initial_balance)
        simulator.exchange.set_price("005930", Decimal("70000"))

        # 1. 매수 주문
        buy_order = Order(
            account_number="99999999",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=100
        )

        buy_filled = await simulator.submit_order(buy_order)
        assert buy_filled.status == OrderStatus.FILLED

        # 2. 가격 상승 (7만원 → 7.5만원)
        simulator.exchange.set_price("005930", Decimal("75000"))

        # 3. 전량 매도
        sell_order = Order(
            account_number="99999999",
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.MARKET,
            quantity=100
        )

        sell_filled = await simulator.submit_order(sell_order)
        assert sell_filled.status == OrderStatus.FILLED

        # 4. 수익 확인 (슬리피지 고려하여 범위로 검증)
        account = await simulator.get_account()
        # 초기 자금보다 증가했는지만 확인
        assert account.cash_balance > initial_balance

        # 5. 포지션 청산 확인
        positions_list = simulator.get_positions()
        assert len(positions_list) == 0  # 전량 매도로 포지션 없음

    @pytest.mark.asyncio
    async def test_limit_order_execution_sync(self):
        """지정가 주문 실행 테스트."""
        # Given
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
        simulator.exchange.set_price("005930", Decimal("70000"))

        # 지정가 매수 주문 (7만원에 매수)
        limit_buy_order = Order(
            account_number="99999999",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.LIMIT,
            limit_price=Decimal("70000"),
            quantity=100
        )

        # When
        filled_order = await simulator.submit_order(limit_buy_order)

        # Then
        assert filled_order.status == OrderStatus.FILLED
        assert filled_order.filled_price == Decimal("70000")

    @pytest.mark.asyncio
    async def test_limit_buy_order_not_filled_when_price_higher(self):
        """현재가가 지정가보다 높으면 지정가 매수 주문 미체결."""
        # Given
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
        simulator.exchange.set_price("005930", Decimal("75000"))  # 현재가 7.5만원

        # 지정가 매수 주문 (7만원에 매수 시도)
        limit_buy_order = Order(
            account_number="99999999",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.LIMIT,
            limit_price=Decimal("70000"),  # 현재가보다 낮음
            quantity=100
        )

        # When
        filled_order = await simulator.submit_order(limit_buy_order)

        # Then
        assert filled_order.status == OrderStatus.SUBMITTED  # 미체결
        assert filled_order.filled_quantity == 0
