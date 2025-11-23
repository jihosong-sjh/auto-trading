"""KiwoomSimulator: In-Memory Fake Kiwoom API.

이 모듈은 실제 Kiwoom API와 동일한 인터페이스를 가지지만,
모든 동작이 메모리 상에서 이루어지는 Fake Object를 구현합니다.
"""

from decimal import Decimal
from typing import Dict, List, Optional
from datetime import datetime
from zoneinfo import ZoneInfo

from ..models import OrderType, OrderStatus, PriceType
from ..models.account import Account
from ..models.position import Position
from ..models.order import Order
from ..models.stock import Stock, MarketType
from .fake_exchange import FakeExchange

KST = ZoneInfo("Asia/Seoul")


class KiwoomSimulator:
    """In-Memory Fake Kiwoom API.
    
    실제 KiwoomClient와 동일한 인터페이스를 가지지만,
    모든 동작이 메모리 상에서 이루어지는 Fake Object입니다.
    
    Attributes:
        initial_balance: 초기 예수금.
        account: 계좌 정보.
        positions: 보유 포지션 (종목코드 -> Position).
        order_history: 주문 이력 (주문ID -> Order).
        exchange: FakeExchange 인스턴스.
    """
    
    def __init__(self, initial_balance: Decimal, account_number: str = "99999999"):
        """KiwoomSimulator 초기화.
        
        Args:
            initial_balance: 초기 예수금.
            account_number: 계좌번호 (기본값: "99999999").
        """
        self.account = Account(
            account_number=account_number,
            name="Test Account",
            cash_balance=initial_balance,
            total_asset_value=initial_balance,
            total_pnl=Decimal("0"),
            daily_pnl=Decimal("0"),
            daily_loss_limit=initial_balance * Decimal("0.05"),  # 초기 자금의 5%
            updated_at=datetime.now(tz=KST)
        )
        
        # 포지션: 종목코드 -> Position
        self.positions: Dict[str, Position] = {}
        
        # 주문 이력: 주문ID -> Order
        self.order_history: Dict[str, Order] = {}
        
        # FakeExchange 인스턴스
        self.exchange = FakeExchange()

        # 오류 주입 플래그
        self._injected_error: Optional[str] = None

    async def get_account(self) -> Account:
        """계좌 정보 조회.

        현재 예수금, 총 평가액, 총 손익을 반환합니다.

        Returns:
            Account: 계좌 정보.
        """
        # 총 평가액 재계산: 예수금 + 모든 포지션 평가액
        total_position_value = sum(
            position.evaluation_amount for position in self.positions.values()
        )

        self.account.total_asset_value = self.account.cash_balance + total_position_value

        # 총 손익 재계산: 모든 포지션의 미실현 손익 합계
        total_unrealized_pnl = sum(
            position.unrealized_pnl for position in self.positions.values()
        )

        self.account.total_pnl = total_unrealized_pnl
        self.account.updated_at = datetime.now(tz=KST)

        return self.account

    def get_positions(self) -> List[Position]:
        """현재 보유 중인 모든 포지션 조회.

        각 포지션의 현재가는 FakeExchange에서 조회됩니다.

        Returns:
            List[Position]: 보유 포지션 목록.
        """
        # 모든 포지션의 현재가를 FakeExchange에서 업데이트
        for stock_code, position in self.positions.items():
            current_price = self.exchange.get_current_price(stock_code)
            if current_price is not None:
                position.current_price = current_price
                position.updated_at = datetime.now(tz=KST)

        return list(self.positions.values())

    async def submit_order(self, order: Order) -> Order:
        """주문 제출 및 체결 시뮬레이션.

        매수 주문 시 예수금 확인, 매도 주문 시 보유 수량 확인 후
        FakeExchange에 주문을 전달하여 체결하고, 잔고 및 포지션을 업데이트합니다.

        Args:
            order: 제출할 주문.

        Returns:
            Order: 체결된 주문 (상태 및 체결 정보 업데이트됨).

        Raises:
            ValueError: 예수금 부족, 보유 수량 부족, 잘못된 종목 코드 등의 오류 시.
            TimeoutError: API 타임아웃 에러.
        """
        # 주입된 오류 확인
        self._check_injected_error()

        # 주문 상태를 SUBMITTED로 변경
        order.status = OrderStatus.SUBMITTED
        order.submitted_at = datetime.now(tz=KST)

        # 종목 코드 유효성 확인
        current_price = self.exchange.get_current_price(order.stock_code)
        if current_price is None:
            order.status = OrderStatus.REJECTED
            order.error_message = f"Invalid stock code: {order.stock_code}"
            self.order_history[order.order_id] = order
            raise ValueError(order.error_message)

        # 매수 주문 처리
        if order.order_type == OrderType.BUY:
            # 예수금 확인
            estimated_cost = current_price * order.quantity
            if self.account.cash_balance < estimated_cost:
                order.status = OrderStatus.REJECTED
                order.error_message = (
                    f"Insufficient balance: {self.account.cash_balance} < {estimated_cost}"
                )
                self.order_history[order.order_id] = order
                raise ValueError(order.error_message)

            # FakeExchange에 주문 전달하여 체결
            filled_order = self.exchange.execute_order(order)

            # 체결 성공 시 잔고 및 포지션 업데이트
            if filled_order.status == OrderStatus.FILLED:
                total_cost = filled_order.filled_price * filled_order.filled_quantity
                self.account.cash_balance -= total_cost

                # 포지션 생성 또는 수량 추가
                if order.stock_code in self.positions:
                    position = self.positions[order.stock_code]
                    position.add_quantity(filled_order.filled_quantity, filled_order.filled_price)
                else:
                    new_position = Position(
                        account_number=self.account.account_number,
                        stock_code=order.stock_code,
                        quantity=filled_order.filled_quantity,
                        average_buy_price=filled_order.filled_price,
                        current_price=current_price,
                        strategy_name=order.strategy_name,
                        opened_at=datetime.now(tz=KST),
                        updated_at=datetime.now(tz=KST)
                    )
                    self.positions[order.stock_code] = new_position

            self.order_history[filled_order.order_id] = filled_order
            return filled_order

        # 매도 주문 처리
        elif order.order_type == OrderType.SELL:
            # 보유 수량 확인
            if order.stock_code not in self.positions:
                order.status = OrderStatus.REJECTED
                order.error_message = f"No position found for stock {order.stock_code}"
                self.order_history[order.order_id] = order
                raise ValueError(order.error_message)

            position = self.positions[order.stock_code]
            if order.quantity > position.quantity:
                order.status = OrderStatus.REJECTED
                order.error_message = (
                    f"Insufficient quantity: {position.quantity} < {order.quantity}"
                )
                self.order_history[order.order_id] = order
                raise ValueError(order.error_message)

            # FakeExchange에 주문 전달하여 체결
            filled_order = self.exchange.execute_order(order)

            # 체결 성공 시 잔고 및 포지션 업데이트
            if filled_order.status == OrderStatus.FILLED:
                total_proceeds = filled_order.filled_price * filled_order.filled_quantity
                self.account.cash_balance += total_proceeds

                # 포지션 수량 감소 또는 제거
                position.reduce_quantity(filled_order.filled_quantity)
                if position.quantity == 0:
                    del self.positions[order.stock_code]

            self.order_history[filled_order.order_id] = filled_order
            return filled_order

        else:
            order.status = OrderStatus.FAILED
            order.error_message = f"Invalid order type: {order.order_type}"
            self.order_history[order.order_id] = order
            raise ValueError(order.error_message)

    async def get_stock_price(self, stock_code: str) -> Stock:
        """종목의 현재 시세 조회.

        FakeExchange에서 현재가를 조회하여 Stock 객체로 반환합니다.

        Args:
            stock_code: 종목코드.

        Returns:
            Stock: 종목 정보.

        Raises:
            ValueError: 종목 코드가 존재하지 않을 경우.
            TimeoutError: API 타임아웃 에러.
        """
        # 주입된 오류 확인
        self._check_injected_error()

        current_price = self.exchange.get_current_price(stock_code)

        if current_price is None:
            raise ValueError(f"Stock code {stock_code} not found in exchange")

        # Stock 객체 생성
        stock = Stock(
            stock_code=stock_code,
            stock_name=f"Stock-{stock_code}",  # 시뮬레이터에서는 간단한 이름 사용
            market=MarketType.KOSPI,  # 기본값
            current_price=current_price,
            open_price=current_price,  # 시뮬레이터에서는 현재가와 동일
            high_price=current_price,
            low_price=current_price,
            volume=0,  # 시뮬레이터에서는 거래량 미사용
            updated_at=datetime.now(tz=KST)
        )

        return stock

    def inject_error(self, error_type: str) -> None:
        """오류 시나리오를 주입합니다.

        테스트를 위해 의도적으로 오류를 발생시킬 수 있습니다.

        Args:
            error_type: 주입할 오류 유형.
                - "insufficient_balance": 예수금 부족 에러
                - "invalid_stock_code": 잘못된 종목 코드 에러
                - "api_timeout": API 타임아웃 에러
                - None: 오류 주입 해제

        Example:
            >>> sim = KiwoomSimulator(Decimal("1000000"))
            >>> sim.inject_error("api_timeout")
            >>> # 다음 API 호출에서 타임아웃 에러 발생
        """
        self._injected_error = error_type

    def _check_injected_error(self) -> None:
        """주입된 오류를 확인하고 발생시킵니다.

        Raises:
            ValueError: 주입된 오류 유형에 따른 예외.
            TimeoutError: API 타임아웃 에러.
        """
        if self._injected_error == "insufficient_balance":
            # 예수금을 0으로 설정하여 주문 실패 유도
            self.account.cash_balance = Decimal("0")

        elif self._injected_error == "invalid_stock_code":
            raise ValueError("Injected error: Invalid stock code")

        elif self._injected_error == "api_timeout":
            raise TimeoutError("Injected error: API request timeout")

        # 오류 주입은 1회성
        self._injected_error = None
