"""가상 거래소 엔진 모듈.

실제 거래소의 호가창과 체결 로직을 메모리 상에서 시뮬레이션합니다.
"""

from decimal import Decimal
from typing import Dict, Optional
from datetime import datetime
from zoneinfo import ZoneInfo

from ..models import OrderType, OrderStatus, PriceType
from ..models.order import Order

KST = ZoneInfo("Asia/Seoul")


class FakeExchange:
    """가상 거래소 엔진.

    실제 거래소의 호가창과 체결 로직을 메모리 상에서 시뮬레이션합니다.

    Attributes:
        prices: 종목별 현재가 딕셔너리 {종목코드: 가격}.
        bid_prices: 매수호가 딕셔너리 {종목코드: 가격}.
        ask_prices: 매도호가 딕셔너리 {종목코드: 가격}.
    """

    def __init__(self) -> None:
        """FakeExchange 초기화."""
        self.prices: Dict[str, Decimal] = {}
        self.bid_prices: Dict[str, Decimal] = {}  # 매수호가 (살 수 있는 가격)
        self.ask_prices: Dict[str, Decimal] = {}  # 매도호가 (팔 수 있는 가격)

    def set_price(self, stock_code: str, price: Decimal) -> None:
        """종목의 현재가를 설정합니다.

        Args:
            stock_code: 종목코드 (6자리).
            price: 설정할 가격.

        Example:
            >>> exchange = FakeExchange()
            >>> exchange.set_price("005930", Decimal("72000"))
        """
        self.prices[stock_code] = price
        # 호가창 시뮬레이션 (현재가 기준 ±0.1%)
        spread = price * Decimal("0.001")
        self.bid_prices[stock_code] = price - spread  # 매수호가
        self.ask_prices[stock_code] = price + spread  # 매도호가

    def get_price(self, stock_code: str) -> Optional[Decimal]:
        """종목의 현재가를 조회합니다.

        Args:
            stock_code: 종목코드.

        Returns:
            현재가. 종목이 없으면 None.

        Example:
            >>> exchange = FakeExchange()
            >>> exchange.set_price("005930", Decimal("72000"))
            >>> exchange.get_price("005930")
            Decimal('72000')
        """
        return self.prices.get(stock_code)

    def get_current_price(self, stock_code: str) -> Optional[Decimal]:
        """종목의 현재가를 조회합니다 (get_price의 별칭).

        Args:
            stock_code: 종목코드.

        Returns:
            현재가. 종목이 없으면 None.
        """
        return self.get_price(stock_code)

    def execute_market_order(self, order: Order) -> Order:
        """시장가 주문을 즉시 체결합니다.

        시장가 주문은 현재가로 즉시 전량 체결됩니다.

        Args:
            order: 체결할 주문 객체.

        Returns:
            체결된 주문 객체 (상태 및 체결 정보 업데이트).

        Raises:
            ValueError: 종목 코드가 존재하지 않을 경우.

        Example:
            >>> exchange = FakeExchange()
            >>> exchange.set_price("005930", Decimal("72000"))
            >>> order = Order(
            ...     account_number="12345678",
            ...     stock_code="005930",
            ...     order_type=OrderType.BUY,
            ...     price_type=PriceType.MARKET,
            ...     quantity=100
            ... )
            >>> filled_order = exchange.execute_market_order(order)
            >>> filled_order.status
            <OrderStatus.FILLED: 'FILLED'>
        """
        stock_code = order.stock_code
        current_price = self.get_price(stock_code)

        if current_price is None:
            raise ValueError(f"Stock code {stock_code} not found in exchange")

        # 시장가 매수 → 매도호가로 체결
        # 시장가 매도 → 매수호가로 체결
        if order.order_type == OrderType.BUY:
            execution_price = self.ask_prices.get(stock_code, current_price)
        else:  # SELL
            execution_price = self.bid_prices.get(stock_code, current_price)

        # 주문 체결 정보 업데이트
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.filled_price = execution_price
        order.filled_at = datetime.now(tz=KST)

        return order

    def execute_limit_order(self, order: Order) -> Order:
        """지정가 주문을 조건 충족 시 체결합니다.

        지정가 주문은 다음 조건에서만 체결됩니다:
        - 매수 지정가: 현재가 <= 지정가
        - 매도 지정가: 현재가 >= 지정가

        Args:
            order: 체결할 주문 객체.

        Returns:
            체결된 주문 객체 (조건 충족 시 FILLED, 미충족 시 SUBMITTED 상태 유지).

        Raises:
            ValueError: 종목 코드가 존재하지 않거나 limit_price가 없을 경우.

        Example:
            >>> exchange = FakeExchange()
            >>> exchange.set_price("005930", Decimal("72000"))
            >>> order = Order(
            ...     account_number="12345678",
            ...     stock_code="005930",
            ...     order_type=OrderType.BUY,
            ...     price_type=PriceType.LIMIT,
            ...     quantity=100,
            ...     limit_price=Decimal("72500")
            ... )
            >>> filled_order = exchange.execute_limit_order(order)
            >>> filled_order.status
            <OrderStatus.FILLED: 'FILLED'>
        """
        stock_code = order.stock_code
        current_price = self.get_price(stock_code)

        if current_price is None:
            raise ValueError(f"Stock code {stock_code} not found in exchange")

        if order.limit_price is None:
            raise ValueError(f"Limit order must have limit_price")

        # 체결 조건 확인
        can_fill = False

        if order.order_type == OrderType.BUY:
            # 매수 지정가: 현재가 <= 지정가일 때 체결
            if current_price <= order.limit_price:
                can_fill = True
                execution_price = current_price
        else:  # SELL
            # 매도 지정가: 현재가 >= 지정가일 때 체결
            if current_price >= order.limit_price:
                can_fill = True
                execution_price = current_price

        if can_fill:
            # 주문 체결
            order.status = OrderStatus.FILLED
            order.filled_quantity = order.quantity
            order.filled_price = execution_price
            order.filled_at = datetime.now(tz=KST)
        else:
            # 조건 미충족 시 SUBMITTED 상태 유지
            if order.status == OrderStatus.PENDING:
                order.status = OrderStatus.SUBMITTED
                order.submitted_at = datetime.now(tz=KST)

        return order

    def tick(self) -> None:
        """시간 경과를 시뮬레이션합니다.

        호가 변동, 체결 대기 중인 주문 처리 등을 수행할 수 있습니다.
        현재는 기본 구현으로, 향후 확장 가능합니다.

        Example:
            >>> exchange = FakeExchange()
            >>> exchange.set_price("005930", Decimal("72000"))
            >>> exchange.tick()  # 시간 경과 시뮬레이션
        """
        # 현재는 호가창 갱신만 수행
        for stock_code, price in self.prices.items():
            spread = price * Decimal("0.001")
            self.bid_prices[stock_code] = price - spread
            self.ask_prices[stock_code] = price + spread

    def execute_order(self, order: Order) -> Order:
        """주문을 체결합니다.

        주문 유형(시장가/지정가)에 따라 적절한 체결 메서드를 호출합니다.

        Args:
            order: 체결할 주문 객체.

        Returns:
            체결된 주문 객체.

        Raises:
            ValueError: 유효하지 않은 주문 유형.
        """
        if order.price_type == PriceType.MARKET:
            return self.execute_market_order(order)
        elif order.price_type == PriceType.LIMIT:
            return self.execute_limit_order(order)
        else:
            raise ValueError(f"Invalid price type: {order.price_type}")
