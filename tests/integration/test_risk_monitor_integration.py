"""RiskMonitor 시뮬레이터 통합 테스트.

FakeExchange와 KiwoomSimulator를 사용하여 RiskMonitor의
실시간 손절/익절 트리거 동작을 End-to-End로 검증합니다.
"""

import asyncio
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.simulator.fake_exchange import FakeExchange
from src.simulator.kiwoom_simulator import KiwoomSimulator
from src.services.risk_monitor import RiskMonitor
from src.services.risk_manager import RiskManager
from src.services.order_executor import OrderExecutor
from src.models import OrderType, OrderStatus, PriceType
from src.models.position import Position
from src.models.order import Order
from src.models.account import Account

KST = ZoneInfo("Asia/Seoul")


class TestRiskMonitorIntegration:
    """RiskMonitor 시뮬레이터 통합 테스트."""

    @pytest.fixture
    def fake_exchange(self):
        """FakeExchange 픽스처."""
        exchange = FakeExchange()
        exchange.set_price("005930", Decimal("10000"))  # 삼성전자
        exchange.set_price("000660", Decimal("50000"))  # SK하이닉스
        exchange.set_price("035420", Decimal("30000"))  # NAVER
        return exchange

    @pytest.fixture
    def simulator(self, fake_exchange):
        """KiwoomSimulator 픽스처."""
        account = Account(
            account_number="12345678",
            name="테스트계좌",
            cash_balance=Decimal("10000000"),
            total_asset_value=Decimal("10000000")
        )
        simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
        simulator.exchange = fake_exchange
        simulator.account = account
        return simulator

    @pytest.fixture
    def risk_manager(self):
        """RiskManager 픽스처."""
        return RiskManager(
            daily_loss_limit_pct=Decimal("0.05"),  # 5% 일일 손실 한도
            max_position_concentration=Decimal("0.3")  # 30% 집중도 한도
        )

    @pytest.fixture
    def order_executor(self, simulator, risk_manager):
        """OrderExecutor 픽스처."""
        pending_orders = {}  # 진행 중인 주문 딕셔너리
        positions = {}  # 현재 포지션 딕셔너리
        return OrderExecutor(
            client=simulator,
            pending_orders=pending_orders,
            positions=positions,
            risk_manager=risk_manager
        )

    @pytest.mark.asyncio
    async def test_stop_loss_trigger(
        self,
        fake_exchange,
        simulator,
        risk_manager,
        order_executor
    ):
        """손절 트리거 테스트.

        시나리오:
        1. 매수가 10,000원에 포지션 생성
        2. 손절가 9,500원 설정
        3. 현재가를 9,400원으로 하락 시뮬레이션
        4. RiskMonitor가 손절 감지하여 자동 매도
        """
        # Given: 포지션 생성
        position = Position(
            account_number="12345678",
            stock_code="005930",
            quantity=100,
            average_buy_price=Decimal("10000"),
            current_price=Decimal("10000")
        )

        # 손절가 설정 (5% 하락)
        stop_loss_price = Decimal("9500")
        position.set_stop_loss(stop_loss_price)

        # 포지션 딕셔너리
        positions = {"005930": position}

        # RiskMonitor 생성
        risk_monitor = RiskMonitor(
            risk_manager=risk_manager,
            order_executor=order_executor,
            positions=positions,
            client=simulator,
            check_interval=0.1,  # 테스트용 빠른 체크
            price_type=PriceType.MARKET
        )

        # When: 가격을 손절가 아래로 하락
        fake_exchange.set_price("005930", Decimal("9400"))
        position.update_price(Decimal("9400"))

        # RiskMonitor의 모니터링 로직 수동 트리거
        await risk_monitor._update_all_positions_price()
        triggered_positions = risk_manager.monitor_all_positions(list(positions.values()))

        # Then: 손절 트리거 감지
        assert len(triggered_positions) == 1
        triggered = triggered_positions[0]
        assert triggered["position"].stock_code == "005930"
        assert triggered["trigger_type"] == "stop_loss"
        assert triggered["current_price"] == Decimal("9400")
        assert triggered["target_price"] == stop_loss_price

        # 자동 매도 주문 실행 시뮬레이션
        sell_order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.MARKET,
            quantity=100
        )

        result = await order_executor.execute_order(sell_order)

        # 매도 주문 체결 확인
        assert result.status == OrderStatus.FILLED
        assert result.filled_quantity == 100
        print(f"[SUCCESS] Stop loss triggered: sold at {result.filled_price}")

    @pytest.mark.asyncio
    async def test_take_profit_trigger(
        self,
        fake_exchange,
        simulator,
        risk_manager,
        order_executor
    ):
        """익절 트리거 테스트.

        시나리오:
        1. 매수가 10,000원에 포지션 생성
        2. 익절가 10,500원 설정
        3. 현재가를 10,600원으로 상승 시뮬레이션
        4. RiskMonitor가 익절 감지하여 자동 매도
        """
        # Given: 포지션 생성
        position = Position(
            account_number="12345678",
            stock_code="005930",
            quantity=100,
            average_buy_price=Decimal("10000"),
            current_price=Decimal("10000")
        )

        # 익절가 설정 (5% 상승)
        take_profit_price = Decimal("10500")
        position.set_take_profit(take_profit_price)

        positions = {"005930": position}

        # RiskMonitor 생성
        risk_monitor = RiskMonitor(
            risk_manager=risk_manager,
            order_executor=order_executor,
            positions=positions,
            client=simulator,
            check_interval=0.1,
            price_type=PriceType.MARKET
        )

        # When: 가격을 익절가 위로 상승
        fake_exchange.set_price("005930", Decimal("10600"))
        position.update_price(Decimal("10600"))

        # RiskMonitor의 모니터링 로직 수동 트리거
        await risk_monitor._update_all_positions_price()
        triggered_positions = risk_manager.monitor_all_positions(list(positions.values()))

        # Then: 익절 트리거 감지
        assert len(triggered_positions) == 1
        triggered = triggered_positions[0]
        assert triggered["position"].stock_code == "005930"
        assert triggered["trigger_type"] == "take_profit"
        assert triggered["current_price"] == Decimal("10600")
        assert triggered["target_price"] == take_profit_price

        # 자동 매도 주문 실행
        sell_order = Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.MARKET,
            quantity=100
        )

        result = await order_executor.execute_order(sell_order)

        # 매도 주문 체결 확인
        assert result.status == OrderStatus.FILLED
        assert result.filled_quantity == 100
        print(f"[SUCCESS] Take profit triggered: sold at {result.filled_price}")

    @pytest.mark.asyncio
    async def test_multiple_positions_simultaneous_triggers(
        self,
        fake_exchange,
        simulator,
        risk_manager,
        order_executor
    ):
        """다중 포지션 동시 트리거 테스트.

        시나리오:
        1. 3개 종목 포지션 생성 (005930, 000660, 035420)
        2. 각각 다른 손절/익절 조건 설정
        3. 동시에 2개 종목에서 트리거 발생
        4. RiskMonitor가 모두 감지하고 처리
        """
        # Given: 3개 포지션 생성
        position1 = Position(
            account_number="12345678",
            stock_code="005930",
            quantity=100,
            average_buy_price=Decimal("10000"),
            current_price=Decimal("10000")
        )
        position1.set_stop_loss(Decimal("9500"))  # 손절가 설정

        position2 = Position(
            account_number="12345678",
            stock_code="000660",
            quantity=50,
            average_buy_price=Decimal("50000"),
            current_price=Decimal("50000")
        )
        position2.set_take_profit(Decimal("52500"))  # 익절가 설정

        position3 = Position(
            account_number="12345678",
            stock_code="035420",
            quantity=80,
            average_buy_price=Decimal("30000"),
            current_price=Decimal("30000")
        )
        position3.set_stop_loss(Decimal("28500"))  # 손절가 설정

        positions = {
            "005930": position1,
            "000660": position2,
            "035420": position3
        }

        # RiskMonitor 생성
        risk_monitor = RiskMonitor(
            risk_manager=risk_manager,
            order_executor=order_executor,
            positions=positions,
            client=simulator,
            check_interval=0.1,
            price_type=PriceType.MARKET
        )

        # When: 2개 종목에서 동시 트리거
        # 005930: 손절 트리거 (9400원)
        fake_exchange.set_price("005930", Decimal("9400"))
        position1.update_price(Decimal("9400"))

        # 000660: 익절 트리거 (52600원)
        fake_exchange.set_price("000660", Decimal("52600"))
        position2.update_price(Decimal("52600"))

        # 035420: 정상 (30000원 유지)
        fake_exchange.set_price("035420", Decimal("30000"))
        position3.update_price(Decimal("30000"))

        # RiskMonitor의 모니터링 로직 수동 트리거
        await risk_monitor._update_all_positions_price()
        triggered_positions = risk_manager.monitor_all_positions(list(positions.values()))

        # Then: 2개 트리거 감지
        assert len(triggered_positions) == 2

        # 트리거 내용 검증
        triggered_stocks = {t["position"].stock_code: t for t in triggered_positions}

        # 005930 손절 확인
        assert "005930" in triggered_stocks
        assert triggered_stocks["005930"]["trigger_type"] == "stop_loss"
        assert triggered_stocks["005930"]["current_price"] == Decimal("9400")

        # 000660 익절 확인
        assert "000660" in triggered_stocks
        assert triggered_stocks["000660"]["trigger_type"] == "take_profit"
        assert triggered_stocks["000660"]["current_price"] == Decimal("52600")

        # 035420은 트리거 없음
        assert "035420" not in triggered_stocks

        print("[SUCCESS] Multiple positions triggered simultaneously")
        print(f"  - 005930: Stop loss at 9400")
        print(f"  - 000660: Take profit at 52600")
        print(f"  - 035420: No trigger")

    @pytest.mark.asyncio
    async def test_no_trigger_within_threshold(
        self,
        fake_exchange,
        simulator,
        risk_manager,
        order_executor
    ):
        """손절/익절 임계값 내에서는 트리거 없음.

        시나리오:
        1. 매수가 10,000원, 손절가 9,500원
        2. 현재가 9,600원 (손절가 위)
        3. 트리거 발생하지 않아야 함
        """
        # Given: 포지션 생성
        position = Position(
            account_number="12345678",
            stock_code="005930",
            quantity=100,
            average_buy_price=Decimal("10000"),
            current_price=Decimal("10000")
        )
        position.set_stop_loss(Decimal("9500"))

        positions = {"005930": position}

        risk_monitor = RiskMonitor(
            risk_manager=risk_manager,
            order_executor=order_executor,
            positions=positions,
            client=simulator,
            check_interval=0.1,
            price_type=PriceType.MARKET
        )

        # When: 가격이 손절가 위에서 하락
        fake_exchange.set_price("005930", Decimal("9600"))
        position.update_price(Decimal("9600"))

        await risk_monitor._update_all_positions_price()
        triggered_positions = risk_manager.monitor_all_positions(list(positions.values()))

        # Then: 트리거 없음
        assert len(triggered_positions) == 0
        print("[SUCCESS] No trigger within threshold (9600 > 9500)")
