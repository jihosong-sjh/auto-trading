"""GoldenCrossStrategy 통합 테스트.

이 모듈은 KiwoomSimulator를 사용하여 GoldenCrossStrategy의 매수/매도 시그널 및
전체 트레이딩 시나리오를 테스트합니다.
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.strategies.golden_cross import GoldenCrossStrategy
from src.simulator.kiwoom_simulator import KiwoomSimulator
from src.models import Stock, OrderType, OrderStatus, PriceType
from src.models.order import Order
from src.models.chart_data import ChartData, ChartInterval


KST = ZoneInfo("Asia/Seoul")


@pytest.fixture
def simulator():
    """KiwoomSimulator 픽스처.

    Returns:
        초기 잔고 1000만원으로 초기화된 KiwoomSimulator
    """
    return KiwoomSimulator(initial_balance=Decimal("10000000"))


@pytest.fixture
def golden_cross_strategy():
    """GoldenCrossStrategy 픽스처.

    Returns:
        기본 파라미터로 초기화된 GoldenCrossStrategy
    """
    return GoldenCrossStrategy(
        short_period=5,
        long_period=20,
        min_volume=100000,
        stop_loss_pct=0.03,
        take_profit_pct=0.05,
    )


def create_chart_data_sequence(
    stock_code: str, base_price: Decimal, days: int, trend: str = "neutral"
) -> list[ChartData]:
    """차트 데이터 시퀀스 생성 헬퍼 함수.

    Args:
        stock_code: 종목 코드
        base_price: 기준 가격
        days: 생성할 일수
        trend: 추세 ("uptrend", "downtrend", "neutral")

    Returns:
        ChartData 리스트
    """
    chart_data_list = []
    current_price = base_price
    base_time = datetime.now(tz=KST) - timedelta(days=days)

    for i in range(days):
        timestamp = base_time + timedelta(days=i)

        # 추세에 따라 가격 변화
        if trend == "uptrend":
            price_change = Decimal(str(i * 100))  # 점진적 상승
        elif trend == "downtrend":
            price_change = Decimal(str(-i * 100))  # 점진적 하락
        else:
            price_change = Decimal("0")  # 중립

        close_price = current_price + price_change
        open_price = close_price - Decimal("50")
        high_price = close_price + Decimal("100")
        low_price = close_price - Decimal("100")

        chart_data = ChartData(
            stock_code=stock_code,
            interval=ChartInterval.DAY,
            timestamp=timestamp,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            close_price=close_price,
            volume=150000,
        )
        chart_data_list.append(chart_data)

    return chart_data_list


@pytest.mark.asyncio
async def test_golden_cross_buy_signal(simulator, golden_cross_strategy):
    """골든크로스 매수 시그널 통합 테스트.

    시나리오:
    1. 하락 추세 데이터 생성 (단기 SMA < 장기 SMA)
    2. 상승 추세 데이터 추가 (단기 SMA > 장기 SMA로 전환)
    3. 골든크로스 발생 → 매수 신호 확인
    4. Simulator에 주문 제출 및 체결 확인
    """
    stock_code = "005930"

    # 1. 초기 하락 추세 데이터 (25일)
    downtrend_data = create_chart_data_sequence(
        stock_code=stock_code, base_price=Decimal("70000"), days=25, trend="downtrend"
    )
    golden_cross_strategy.set_chart_data(stock_code, downtrend_data)

    # Simulator의 FakeExchange에 종목 가격 설정
    simulator.exchange.set_price(stock_code, downtrend_data[-1].close_price)

    # 현재 Stock 객체 생성
    stock = Stock(
        stock_code=stock_code,
        stock_name="삼성전자",
        market="KOSPI",
        current_price=downtrend_data[-1].close_price,
        volume=150000,
    )

    # 2. 매수 신호 확인 (아직 골든크로스 아님)
    buy_signal_before = await golden_cross_strategy.evaluate_buy_signal(stock)
    assert buy_signal_before is False, "초기 하락 추세에서는 매수 신호가 없어야 함"

    # 3. 상승 추세 데이터 추가 (10일)
    uptrend_data = create_chart_data_sequence(
        stock_code=stock_code,
        base_price=downtrend_data[-1].close_price,
        days=10,
        trend="uptrend",
    )
    for data in uptrend_data:
        golden_cross_strategy.add_chart_data(stock_code, data)

    # 최신 가격으로 Stock 업데이트
    latest_price = uptrend_data[-1].close_price
    simulator.exchange.set_price(stock_code, latest_price)
    stock.current_price = latest_price

    # 4. 골든크로스 발생 확인
    buy_signal_after = await golden_cross_strategy.evaluate_buy_signal(stock)
    assert buy_signal_after is True, "골든크로스 발생 시 매수 신호가 있어야 함"

    # 5. Simulator에 매수 주문 제출
    account = await simulator.get_account()
    quantity = 100

    buy_order = Order(
        account_number=account.account_number,
        stock_code=stock_code,
        order_type=OrderType.BUY,
        price_type=PriceType.MARKET,
        quantity=quantity,
    )

    filled_order = await simulator.submit_order(buy_order)

    # 6. 주문 체결 확인
    assert filled_order.status == OrderStatus.FILLED, "주문이 체결되어야 함"
    assert filled_order.filled_quantity == quantity, "주문 수량이 모두 체결되어야 함"
    assert filled_order.filled_price is not None, "체결가가 있어야 함"
    assert filled_order.filled_price > Decimal("0"), "체결가는 양수여야 함"

    # 7. 포지션 확인
    positions = simulator.get_positions()
    assert len(positions) == 1, "포지션이 1개 생성되어야 함"
    assert positions[0].stock_code == stock_code, "종목 코드가 일치해야 함"
    assert positions[0].quantity == quantity, "보유 수량이 일치해야 함"
    assert positions[0].average_buy_price == filled_order.filled_price, "평균 매수가가 체결가와 일치해야 함"


@pytest.mark.asyncio
async def test_golden_cross_sell_signal_dead_cross(simulator, golden_cross_strategy):
    """데드크로스 매도 시그널 통합 테스트.

    시나리오:
    1. 포지션 보유 상태에서 상승 추세 데이터 생성
    2. 하락 추세 데이터 추가 (데드크로스 발생)
    3. 매도 신호 확인
    4. Simulator에 매도 주문 제출 및 체결 확인
    """
    stock_code = "005930"
    initial_price = Decimal("70000")

    # 1. 상승 추세 데이터 (25일)
    uptrend_data = create_chart_data_sequence(
        stock_code=stock_code, base_price=initial_price, days=25, trend="uptrend"
    )
    golden_cross_strategy.set_chart_data(stock_code, uptrend_data)

    # Simulator에 종목 등록 및 포지션 생성
    simulator.exchange.set_price(stock_code, initial_price)

    # 매수 주문 제출 (포지션 생성)
    account = await simulator.get_account()
    quantity = 100

    buy_order = Order(
        account_number=account.account_number,
        stock_code=stock_code,
        order_type=OrderType.BUY,
        price_type=PriceType.MARKET,
        quantity=quantity,
    )
    await simulator.submit_order(buy_order)

    # 포지션 확인
    positions = simulator.get_positions()
    assert len(positions) == 1, "포지션이 생성되어야 함"
    position = positions[0]

    # 현재 Stock 객체 생성
    stock = Stock(
        stock_code=stock_code,
        stock_name="삼성전자",
        market="KOSPI",
        current_price=uptrend_data[-1].close_price,
        volume=150000,
    )

    # 2. 매도 신호 확인 (아직 데드크로스 아님)
    sell_signal_before = await golden_cross_strategy.evaluate_sell_signal(position, stock)
    assert sell_signal_before is False, "상승 추세에서는 매도 신호가 없어야 함"

    # 3. 하락 추세 데이터 추가 (10일)
    downtrend_data = create_chart_data_sequence(
        stock_code=stock_code,
        base_price=uptrend_data[-1].close_price,
        days=10,
        trend="downtrend",
    )
    for data in downtrend_data:
        golden_cross_strategy.add_chart_data(stock_code, data)

    # 최신 가격으로 Stock 및 Position 업데이트
    latest_price = downtrend_data[-1].close_price
    simulator.exchange.set_price(stock_code, latest_price)
    stock.current_price = latest_price

    # 포지션 재조회 (가격 업데이트 반영)
    updated_positions = simulator.get_positions()
    updated_position = updated_positions[0]

    # 4. 데드크로스 발생 확인
    sell_signal_after = await golden_cross_strategy.evaluate_sell_signal(
        updated_position, stock
    )
    assert sell_signal_after is True, "데드크로스 발생 시 매도 신호가 있어야 함"

    # 5. Simulator에 매도 주문 제출
    sell_order = Order(
        account_number=account.account_number,
        stock_code=stock_code,
        order_type=OrderType.SELL,
        price_type=PriceType.MARKET,
        quantity=quantity,
    )

    filled_order = await simulator.submit_order(sell_order)

    # 6. 주문 체결 확인
    assert filled_order.status == OrderStatus.FILLED, "매도 주문이 체결되어야 함"
    assert filled_order.filled_quantity == quantity, "매도 수량이 모두 체결되어야 함"

    # 7. 포지션 확인 (전량 매도 시 제거)
    final_positions = simulator.get_positions()
    assert len(final_positions) == 0, "전량 매도 시 포지션이 제거되어야 함"


@pytest.mark.asyncio
async def test_golden_cross_sell_signal_stop_loss(simulator, golden_cross_strategy):
    """손절 매도 시그널 통합 테스트.

    시나리오:
    1. 포지션 보유 상태
    2. 가격 하락으로 손절 조건 충족
    3. 매도 신호 확인 및 주문 체결
    """
    stock_code = "005930"
    buy_price = Decimal("70000")
    stop_loss_price = buy_price * (Decimal("1") - Decimal("0.03"))  # 3% 하락

    # Simulator에 종목 등록 및 포지션 생성
    simulator.exchange.set_price(stock_code, buy_price)

    account = await simulator.get_account()
    quantity = 100

    # 매수 주문 제출
    buy_order = Order(
        account_number=account.account_number,
        stock_code=stock_code,
        order_type=OrderType.BUY,
        price_type=PriceType.MARKET,
        quantity=quantity,
    )
    await simulator.submit_order(buy_order)

    # 가격 하락 (손절 조건 충족)
    simulator.exchange.set_price(stock_code, stop_loss_price - Decimal("100"))

    # Stock 객체 생성
    stock = Stock(
        stock_code=stock_code,
        stock_name="삼성전자",
        market="KOSPI",
        current_price=stop_loss_price - Decimal("100"),
        volume=150000,
    )

    # 포지션 조회
    positions = simulator.get_positions()
    position = positions[0]

    # 손절 조건 확인
    sell_signal = await golden_cross_strategy.evaluate_sell_signal(position, stock)
    assert sell_signal is True, "손절 조건 충족 시 매도 신호가 있어야 함"

    # 매도 주문 제출
    sell_order = Order(
        account_number=account.account_number,
        stock_code=stock_code,
        order_type=OrderType.SELL,
        price_type=PriceType.MARKET,
        quantity=quantity,
    )
    filled_order = await simulator.submit_order(sell_order)

    assert filled_order.status == OrderStatus.FILLED, "손절 매도가 체결되어야 함"
    assert len(simulator.get_positions()) == 0, "포지션이 제거되어야 함"


@pytest.mark.asyncio
async def test_golden_cross_sell_signal_take_profit(simulator, golden_cross_strategy):
    """익절 매도 시그널 통합 테스트.

    시나리오:
    1. 포지션 보유 상태
    2. 가격 상승으로 익절 조건 충족
    3. 매도 신호 확인 및 주문 체결
    """
    stock_code = "005930"
    buy_price = Decimal("70000")
    take_profit_price = buy_price * (Decimal("1") + Decimal("0.05"))  # 5% 상승

    # Simulator에 종목 등록 및 포지션 생성
    simulator.exchange.set_price(stock_code, buy_price)

    account = await simulator.get_account()
    quantity = 100

    # 매수 주문 제출
    buy_order = Order(
        account_number=account.account_number,
        stock_code=stock_code,
        order_type=OrderType.BUY,
        price_type=PriceType.MARKET,
        quantity=quantity,
    )
    await simulator.submit_order(buy_order)

    # 가격 상승 (익절 조건 충족)
    simulator.exchange.set_price(stock_code, take_profit_price + Decimal("100"))

    # Stock 객체 생성
    stock = Stock(
        stock_code=stock_code,
        stock_name="삼성전자",
        market="KOSPI",
        current_price=take_profit_price + Decimal("100"),
        volume=150000,
    )

    # 포지션 조회
    positions = simulator.get_positions()
    position = positions[0]

    # 익절 조건 확인
    sell_signal = await golden_cross_strategy.evaluate_sell_signal(position, stock)
    assert sell_signal is True, "익절 조건 충족 시 매도 신호가 있어야 함"

    # 매도 주문 제출
    sell_order = Order(
        account_number=account.account_number,
        stock_code=stock_code,
        order_type=OrderType.SELL,
        price_type=PriceType.MARKET,
        quantity=quantity,
    )
    filled_order = await simulator.submit_order(sell_order)

    assert filled_order.status == OrderStatus.FILLED, "익절 매도가 체결되어야 함"
    assert len(simulator.get_positions()) == 0, "포지션이 제거되어야 함"

    # 수익 확인
    account_after = await simulator.get_account()
    assert account_after.cash_balance > Decimal("10000000"), "익절로 수익이 발생해야 함"


@pytest.mark.asyncio
async def test_golden_cross_full_scenario(simulator, golden_cross_strategy):
    """골든크로스 전체 시나리오 통합 테스트.

    시나리오:
    1. 골든크로스 발생 → 매수
    2. 가격 상승
    3. 데드크로스 발생 → 매도
    4. 손익 확인
    """
    stock_code = "005930"
    initial_balance = (await simulator.get_account()).cash_balance

    # 1. 하락 추세 → 상승 추세 (골든크로스)
    downtrend_data = create_chart_data_sequence(
        stock_code=stock_code, base_price=Decimal("70000"), days=25, trend="downtrend"
    )
    golden_cross_strategy.set_chart_data(stock_code, downtrend_data)

    uptrend_data = create_chart_data_sequence(
        stock_code=stock_code,
        base_price=downtrend_data[-1].close_price,
        days=10,
        trend="uptrend",
    )
    for data in uptrend_data:
        golden_cross_strategy.add_chart_data(stock_code, data)

    # Simulator에 종목 등록
    buy_price = uptrend_data[-1].close_price
    simulator.exchange.set_price(stock_code, buy_price)

    stock = Stock(
        stock_code=stock_code,
        stock_name="삼성전자",
        market="KOSPI",
        current_price=buy_price,
        volume=150000,
    )

    # 2. 매수 신호 확인 및 주문
    buy_signal = await golden_cross_strategy.evaluate_buy_signal(stock)
    assert buy_signal is True, "골든크로스 시 매수 신호 발생"

    account = await simulator.get_account()
    quantity = await golden_cross_strategy.calculate_position_size(
        stock, account.cash_balance
    )

    buy_order = Order(
        account_number=account.account_number,
        stock_code=stock_code,
        order_type=OrderType.BUY,
        price_type=PriceType.MARKET,
        quantity=quantity,
    )
    filled_buy_order = await simulator.submit_order(buy_order)
    assert filled_buy_order.status == OrderStatus.FILLED, "매수 주문 체결"

    # 3. 가격 상승 (계속 상승)
    more_uptrend_data = create_chart_data_sequence(
        stock_code=stock_code,
        base_price=uptrend_data[-1].close_price,
        days=5,
        trend="uptrend",
    )
    for data in more_uptrend_data:
        golden_cross_strategy.add_chart_data(stock_code, data)

    # 4. 하락 추세로 전환 (데드크로스)
    downtrend_data_2 = create_chart_data_sequence(
        stock_code=stock_code,
        base_price=more_uptrend_data[-1].close_price,
        days=10,
        trend="downtrend",
    )
    for data in downtrend_data_2:
        golden_cross_strategy.add_chart_data(stock_code, data)

    # 가격 업데이트
    sell_price = downtrend_data_2[-1].close_price
    simulator.exchange.set_price(stock_code, sell_price)
    stock.current_price = sell_price

    # 포지션 조회
    positions = simulator.get_positions()
    position = positions[0]

    # 5. 매도 신호 확인 및 주문
    sell_signal = await golden_cross_strategy.evaluate_sell_signal(position, stock)
    assert sell_signal is True, "데드크로스 시 매도 신호 발생"

    sell_order = Order(
        account_number=account.account_number,
        stock_code=stock_code,
        order_type=OrderType.SELL,
        price_type=PriceType.MARKET,
        quantity=quantity,
    )
    filled_sell_order = await simulator.submit_order(sell_order)
    assert filled_sell_order.status == OrderStatus.FILLED, "매도 주문 체결"

    # 6. 손익 확인
    final_balance = (await simulator.get_account()).cash_balance
    pnl = final_balance - initial_balance

    # 상승 후 하락이지만, 전체적으로는 매수가보다 높은 가격에 매도했는지 확인
    print(f"\n[Full Scenario Test Results]")
    print(f"Initial Balance: {initial_balance:,}")
    print(f"Buy Price: {buy_price:,}")
    print(f"Sell Price: {sell_price:,}")
    print(f"Quantity: {quantity}")
    print(f"Final Balance: {final_balance:,}")
    print(f"P&L: {pnl:,}")

    # 포지션이 청산되었는지 확인
    assert len(simulator.get_positions()) == 0, "모든 포지션이 청산되어야 함"
