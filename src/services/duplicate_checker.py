"""중복 주문 체크 서비스.

동일 종목에 대해 이미 진행 중인 주문이 있는지 확인하여 중복 주문을 방지합니다.
"""

from typing import Dict, Optional

from ..models import OrderType, OrderStatus
from ..models.order import Order


class DuplicateOrderChecker:
    """중복 주문을 방지하는 클래스.
    
    동일 종목에 대해 동일 유형(매수/매도)의 진행 중인 주문이 있는지 확인합니다.
    """

    def __init__(self, pending_orders: Dict[str, Order]):
        """DuplicateOrderChecker를 초기화합니다.

        Args:
            pending_orders: 진행 중인 주문 딕셔너리 (order_id -> Order)
        """
        self.pending_orders = pending_orders

    def check_duplicate(
        self,
        stock_code: str,
        order_type: OrderType
    ) -> tuple[bool, Optional[str]]:
        """동일 종목/유형의 진행 중인 주문이 있는지 확인합니다.

        Args:
            stock_code: 종목 코드
            order_type: 주문 유형 (BUY/SELL)

        Returns:
            (중복 여부, 기존 주문 ID) 튜플.
            중복이면 (True, 기존_주문_ID), 중복 아니면 (False, None)

        Examples:
            >>> pending_orders = {"order1": Order(...)}
            >>> checker = DuplicateOrderChecker(pending_orders)
            >>> is_duplicate, existing_id = checker.check_duplicate("005930", OrderType.BUY)
        """
        # 종료 상태가 아닌 주문을 찾음
        terminal_states = {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED
        }

        for order_id, order in self.pending_orders.items():
            # 동일 종목이고, 동일 주문 유형이며, 종료 상태가 아닌 경우
            if (order.stock_code == stock_code and 
                order.order_type == order_type and
                order.status not in terminal_states):
                return True, order_id

        return False, None

    def get_pending_order_count(self, stock_code: str) -> int:
        """특정 종목에 대한 진행 중인 주문 개수를 반환합니다.

        Args:
            stock_code: 종목 코드

        Returns:
            진행 중인 주문 개수

        Examples:
            >>> checker = DuplicateOrderChecker(pending_orders)
            >>> count = checker.get_pending_order_count("005930")
        """
        terminal_states = {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED
        }

        count = 0
        for order in self.pending_orders.values():
            if (order.stock_code == stock_code and 
                order.status not in terminal_states):
                count += 1

        return count

    def has_pending_buy_order(self, stock_code: str) -> bool:
        """특정 종목에 대한 진행 중인 매수 주문이 있는지 확인합니다.

        Args:
            stock_code: 종목 코드

        Returns:
            진행 중인 매수 주문 존재 여부

        Examples:
            >>> checker = DuplicateOrderChecker(pending_orders)
            >>> has_buy = checker.has_pending_buy_order("005930")
        """
        is_duplicate, _ = self.check_duplicate(stock_code, OrderType.BUY)
        return is_duplicate

    def has_pending_sell_order(self, stock_code: str) -> bool:
        """특정 종목에 대한 진행 중인 매도 주문이 있는지 확인합니다.

        Args:
            stock_code: 종목 코드

        Returns:
            진행 중인 매도 주문 존재 여부

        Examples:
            >>> checker = DuplicateOrderChecker(pending_orders)
            >>> has_sell = checker.has_pending_sell_order("005930")
        """
        is_duplicate, _ = self.check_duplicate(stock_code, OrderType.SELL)
        return is_duplicate
