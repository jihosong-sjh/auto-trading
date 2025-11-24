"""계좌 상태 조회 통합 테스트.

AccountService와 PositionService를 함께 사용하여
계좌 상태를 조회하는 통합 테스트입니다.
KiwoomSimulator를 사용하여 실제 시나리오를 테스트합니다.
"""

import pytest
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo

from src.simulator.kiwoom_simulator import KiwoomSimulator
from src.services.account_service import AccountService
from src.services.position_service import PositionService
from src.models import OrderType, PriceType
from src.models.order import Order

KST = ZoneInfo("Asia/Seoul")


@pytest.fixture
def simulator():
    """테스트용 KiwoomSimulator 인스턴스."""
    sim = KiwoomSimulator(
        initial_balance=Decimal("10000000.00"),  # 1천만원 (모의투자 계좌 한도)
        account_number="12345678"
    )

    # 초기 종목 가격 설정 (소액 종목 위주)
    sim.exchange.set_price("005930", Decimal("60000.00"))  # 삼성전자
    sim.exchange.set_price("035720", Decimal("40000.00"))  # 카카오
    sim.exchange.set_price("051910", Decimal("20000.00"))  # LG화학

    return sim


@pytest.fixture
def account_service(simulator):
    """테스트용 AccountService 인스턴스."""
    return AccountService(simulator)


@pytest.fixture
def position_service(simulator):
    """테스트용 PositionService 인스턴스."""
    return PositionService(simulator, simulator)


@pytest.mark.asyncio
async def test_초기_계좌_상태_조회(account_service, position_service):
    """시스템 시작 시 초기 계좌 상태 조회."""
    # When: 초기 계좌 정보 조회
    account = await account_service.get_account()

    # Then: 초기 예수금과 포지션이 정확함
    assert account.cash_balance == Decimal("10000000.00")
    assert account.total_asset_value == Decimal("10000000.00")
    assert account.daily_pnl == Decimal("0.00")

    # 포지션 없음
    positions = position_service.get_all_positions()
    assert len(positions) == 0


@pytest.mark.asyncio
async def test_매수_후_계좌_상태_조회(simulator, account_service, position_service):
    """매수 주문 체결 후 계좌 상태 조회."""
    # Given: 삼성전자 100주 매수 주문
    order = Order(
        account_number="12345678",
        stock_code="005930",
        order_type=OrderType.BUY,
        price_type=PriceType.MARKET,
        quantity=100
    )

    # When: 주문 체결
    filled_order = await simulator.submit_order(order)

    # Then: 계좌 잔고 감소 (실제 체결가 사용)
    account = await account_service.get_account(refresh=True)
    actual_cost = filled_order.filled_price * filled_order.filled_quantity
    expected_cash = Decimal("10000000.00") - actual_cost
    assert account.cash_balance == expected_cash

    # 포지션 생성됨
    positions = position_service.get_all_positions()
    assert len(positions) == 1

    position = positions[0]
    assert position.stock_code == "005930"
    assert position.quantity == 100
    # 슬리피지 고려하여 대략적인 범위 체크 (60,000원 기준)
    assert Decimal("59000") < position.average_buy_price < Decimal("61000")

    # 총 평가액 = 예수금 + 주식 평가액
    assert account.total_asset_value > Decimal("9900000")  # 대략 1000만원 유지


@pytest.mark.asyncio
async def test_여러_종목_매수_후_포지션_요약(simulator, account_service, position_service):
    """여러 종목을 매수한 후 포지션 요약 정보 조회."""
    # Given: 3개 종목 매수 (1000만원 범위 내에서 분산 투자)
    orders = [
        Order(
            account_number="12345678",
            stock_code="005930",  # 삼성전자: 60,000 x 50 = 3,000,000
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=50
        ),
        Order(
            account_number="12345678",
            stock_code="035720",  # 카카오: 40,000 x 75 = 3,000,000
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=75
        ),
        Order(
            account_number="12345678",
            stock_code="051910",  # LG화학: 20,000 x 150 = 3,000,000
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=150
        )
    ]

    for order in orders:
        await simulator.submit_order(order)

    # When: 포지션 요약 정보 조회
    summary = position_service.get_position_summary()

    # Then: 포지션 요약이 정확함
    assert summary["count"] == 3

    # 총 평가액 대략 9백만원 (슬리피지 고려)
    assert summary["total_value"] > Decimal("8900000")
    assert summary["total_value"] < Decimal("9200000")

    # 미실현 손익은 약 0에 가까움 (매수 직후, 슬리피지 손실 존재)
    assert summary["total_pnl"] < Decimal("10000")  # 슬리피지로 약간 손실


@pytest.mark.asyncio
async def test_가격_변동_후_손익_계산(simulator, account_service, position_service):
    """가격 변동 후 미실현 손익 계산."""
    # Given: 삼성전자 100주 매수 (60,000원)
    order = Order(
        account_number="12345678",
        stock_code="005930",
        order_type=OrderType.BUY,
        price_type=PriceType.MARKET,
        quantity=100
    )
    await simulator.submit_order(order)

    # When: 가격 상승 (60,000 -> 63,000)
    simulator.exchange.set_price("005930", Decimal("63000.00"))
    await position_service.update_position_prices()

    # Then: 미실현 손익이 양수 (가격 상승으로 수익)
    summary = position_service.get_position_summary()
    assert summary["total_pnl"] > Decimal("250000")  # 대략 30만원 수익
    assert summary["avg_return_rate"] > Decimal("0.04")  # 약 5% 수익률


@pytest.mark.asyncio
async def test_일부_매도_후_포지션_업데이트(simulator, account_service, position_service):
    """일부 매도 후 포지션이 정확히 업데이트되는지 확인."""
    # Given: 삼성전자 100주 매수
    buy_order = Order(
        account_number="12345678",
        stock_code="005930",
        order_type=OrderType.BUY,
        price_type=PriceType.MARKET,
        quantity=100
    )
    await simulator.submit_order(buy_order)

    initial_cash = (await account_service.get_account(refresh=True)).cash_balance

    # When: 50주 매도
    sell_order = Order(
        account_number="12345678",
        stock_code="005930",
        order_type=OrderType.SELL,
        price_type=PriceType.MARKET,
        quantity=50
    )
    await simulator.submit_order(sell_order)

    # Then: 포지션 수량 감소
    position = position_service.get_position_by_stock("005930")
    assert position is not None
    assert position.quantity == 50  # 100 - 50 = 50주 남음

    # 예수금 증가 (매도 후 잔고가 늘어남)
    account = await account_service.get_account(refresh=True)
    assert account.cash_balance > initial_cash  # 매도로 인한 예수금 증가


@pytest.mark.asyncio
async def test_전량_매도_후_포지션_삭제(simulator, account_service, position_service):
    """전량 매도 후 포지션이 삭제되는지 확인."""
    # Given: 삼성전자 100주 매수
    buy_order = Order(
        account_number="12345678",
        stock_code="005930",
        order_type=OrderType.BUY,
        price_type=PriceType.MARKET,
        quantity=100
    )
    await simulator.submit_order(buy_order)

    # When: 전량 매도
    sell_order = Order(
        account_number="12345678",
        stock_code="005930",
        order_type=OrderType.SELL,
        price_type=PriceType.MARKET,
        quantity=100
    )
    await simulator.submit_order(sell_order)

    # Then: 포지션 삭제됨
    position = position_service.get_position_by_stock("005930")
    assert position is None

    positions = position_service.get_all_positions()
    assert len(positions) == 0

    # 예수금 대략 원상복구 (슬리피지로 약간 손실)
    account = await account_service.get_account(refresh=True)
    assert account.cash_balance > Decimal("9900000")  # 슬리피지로 약간 손실


@pytest.mark.asyncio
async def test_손실_한도_체크(simulator, account_service):
    """일일 손실 한도 초과 여부 확인."""
    # Given: 계좌 정보 조회
    account = await account_service.get_account()
    initial_limit = account.daily_loss_limit

    # When: 큰 손실 발생 (한도: 75만원)
    await account_service.update_daily_pnl(Decimal("-800000.00"))

    # Then: 손실 한도 초과
    exceeded = await account_service.is_daily_loss_limit_exceeded()
    assert exceeded is True


@pytest.mark.asyncio
async def test_손실_한도_미초과(simulator, account_service):
    """일일 손실이 한도 내일 때."""
    # Given: 계좌 정보 조회
    await account_service.get_account()

    # When: 작은 손실 발생 (한도: 75만원)
    await account_service.update_daily_pnl(Decimal("-300000.00"))

    # Then: 손실 한도 미초과
    exceeded = await account_service.is_daily_loss_limit_exceeded()
    assert exceeded is False


@pytest.mark.asyncio
async def test_수익_포지션과_손실_포지션_구분(simulator, position_service):
    """수익 중인 포지션과 손실 중인 포지션 구분."""
    # Given: 2개 종목 매수 (1000만원 범위 내)
    orders = [
        ("005930", 50),   # 삼성전자: 60,000 x 50 = 3,000,000
        ("035720", 100)   # 카카오: 40,000 x 100 = 4,000,000
    ]

    for stock_code, quantity in orders:
        order = Order(
            account_number="12345678",
            stock_code=stock_code,
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=quantity
        )
        await simulator.submit_order(order)

    # 가격 변동 시뮬레이션
    simulator.exchange.set_price("005930", Decimal("63000.00"))  # 삼성: 상승 (수익)
    simulator.exchange.set_price("035720", Decimal("38000.00"))  # 카카오: 하락 (손실)

    await position_service.update_position_prices()

    # When: 수익/손실 포지션 조회
    winning = position_service.get_winning_positions()
    losing = position_service.get_losing_positions()

    # Then: 정확히 구분됨
    assert len(winning) == 1  # 삼성전자
    assert len(losing) == 1   # 카카오

    # 수익 포지션: 삼성전자
    assert winning[0].stock_code == "005930"
    assert winning[0].unrealized_pnl > 0

    # 손실 포지션: 카카오
    assert losing[0].stock_code == "035720"
    assert losing[0].unrealized_pnl < 0


@pytest.mark.asyncio
async def test_포지션_집중도_계산(simulator, position_service):
    """포지션 집중도가 정확히 계산되는지 확인."""
    # Given: 3개 종목 매수 (1000만원 범위 내에서 다른 비중)
    orders = [
        ("005930", 50),    # 삼성전자: 50 * 60,000 = 3,000,000
        ("035720", 50),    # 카카오: 50 * 40,000 = 2,000,000
        ("051910", 200)    # LG화학: 200 * 20,000 = 4,000,000
    ]

    for stock_code, quantity in orders:
        order = Order(
            account_number="12345678",
            stock_code=stock_code,
            order_type=OrderType.BUY,
            price_type=PriceType.MARKET,
            quantity=quantity
        )
        await simulator.submit_order(order)

    # When: 집중도 계산
    concentrations = position_service.get_position_concentration()

    # Then: 각 포지션의 비중 확인
    assert len(concentrations) == 3

    # LG화학이 가장 큰 비중 (약 44%)
    assert concentrations["051910"] > Decimal("0.40")

    # 삼성전자가 그 다음 (약 33%)
    assert concentrations["005930"] > Decimal("0.30")

    # 카카오가 가장 작은 비중 (약 22%)
    assert concentrations["035720"] > Decimal("0.20")
    assert concentrations["035720"] < Decimal("0.25")


@pytest.mark.asyncio
async def test_계좌_총_손익_계산(simulator, account_service, position_service):
    """계좌의 총 손익(실현 + 미실현)을 정확히 계산."""
    # Given: 삼성전자 100주 매수
    order = Order(
        account_number="12345678",
        stock_code="005930",
        order_type=OrderType.BUY,
        price_type=PriceType.MARKET,
        quantity=100
    )
    await simulator.submit_order(order)

    # 가격 상승 (60,000 -> 63,000)
    simulator.exchange.set_price("005930", Decimal("63000.00"))
    await position_service.update_position_prices()

    # When: 미실현 손익 조회
    unrealized_pnl = position_service.calculate_total_unrealized_pnl()

    # Then: 미실현 손익이 양수 (약 30만원)
    assert unrealized_pnl > Decimal("250000")

    # 당일 손익에 반영
    daily_pnl = await account_service.calculate_daily_pnl(unrealized_pnl)
    assert daily_pnl > Decimal("250000")
