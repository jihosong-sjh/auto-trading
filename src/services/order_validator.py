"""주문 검증 서비스.

주문이 실행되기 전에 예수금, 보유 수량, 일일 손실 한도 등을 검증합니다.
"""

from decimal import Decimal
from typing import Optional

from ..models import OrderType
from ..models.account import Account
from ..models.order import Order
from ..models.position import Position


class OrderValidator:
    """주문 실행 전 검증을 수행하는 클래스.
    
    예수금 확인, 수량 검증, 일일 손실 한도 체크 등을 담당합니다.
    """

    @staticmethod
    def validate_buy_order(
        account: Account,
        order: Order,
        current_price: Decimal
    ) -> tuple[bool, Optional[str]]:
        """매수 주문을 검증합니다.

        Args:
            account: 사용자 계좌 정보
            order: 검증할 주문
            current_price: 현재 주식 가격

        Returns:
            (검증 성공 여부, 오류 메시지) 튜플.
            검증 성공 시 (True, None), 실패 시 (False, 오류 메시지)

        Examples:
            >>> validator = OrderValidator()
            >>> account = Account(...)
            >>> order = Order(order_type=OrderType.BUY, quantity=100, ...)
            >>> is_valid, error_msg = validator.validate_buy_order(account, order, Decimal("50000"))
        """
        # 1. 예수금 확인
        estimated_cost = current_price * order.quantity
        if account.cash_balance < estimated_cost:
            return False, (
                f"예수금 부족: 잔고 {account.cash_balance:,}원 < "
                f"필요 금액 {estimated_cost:,}원"
            )

        # 2. 수량 확인 (최소 1주)
        if order.quantity < 1:
            return False, "주문 수량은 최소 1주 이상이어야 합니다"

        # 3. 일일 손실 한도 확인
        if account.is_daily_loss_limit_exceeded():
            return False, (
                f"일일 손실 한도 초과로 거래 중단: "
                f"당일 손익 {account.daily_pnl:,}원, "
                f"한도 -{account.daily_loss_limit:,}원"
            )

        return True, None

    @staticmethod
    def validate_sell_order(
        position: Optional[Position],
        order: Order
    ) -> tuple[bool, Optional[str]]:
        """매도 주문을 검증합니다.

        Args:
            position: 현재 보유 포지션 (없을 수 있음)
            order: 검증할 주문

        Returns:
            (검증 성공 여부, 오류 메시지) 튜플.
            검증 성공 시 (True, None), 실패 시 (False, 오류 메시지)

        Examples:
            >>> validator = OrderValidator()
            >>> position = Position(quantity=150, ...)
            >>> order = Order(order_type=OrderType.SELL, quantity=100, ...)
            >>> is_valid, error_msg = validator.validate_sell_order(position, order)
        """
        # 1. 포지션 존재 확인
        if not position:
            return False, f"종목 {order.stock_code}에 대한 보유 포지션이 없습니다"

        # 2. 매도 가능 수량 확인
        if order.quantity > position.quantity:
            return False, (
                f"보유 수량 부족: 보유 {position.quantity}주 < "
                f"매도 시도 {order.quantity}주"
            )

        # 3. 수량 확인 (최소 1주)
        if order.quantity < 1:
            return False, "주문 수량은 최소 1주 이상이어야 합니다"

        return True, None

    @staticmethod
    def validate_order_price(order: Order) -> tuple[bool, Optional[str]]:
        """주문 가격 정보를 검증합니다.

        Args:
            order: 검증할 주문

        Returns:
            (검증 성공 여부, 오류 메시지) 튜플.
            검증 성공 시 (True, None), 실패 시 (False, 오류 메시지)

        Examples:
            >>> validator = OrderValidator()
            >>> order = Order(price_type=PriceType.LIMIT, limit_price=Decimal("50000"), ...)
            >>> is_valid, error_msg = validator.validate_order_price(order)
        """
        # 지정가 주문인 경우 limit_price 필수
        from ..models import PriceType
        
        if order.price_type == PriceType.LIMIT:
            if order.limit_price is None:
                return False, "지정가 주문은 limit_price가 필수입니다"
            
            if order.limit_price <= 0:
                return False, f"주문 가격은 0보다 커야 합니다: {order.limit_price}"

        return True, None
