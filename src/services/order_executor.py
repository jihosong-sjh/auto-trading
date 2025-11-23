"""주문 실행 서비스.

주문 검증, 제출, 상태 추적을 담당하는 핵심 컴포넌트입니다.
T086: RiskManager 통합하여 주문 전 위험 검증을 수행합니다.
"""

from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional, Protocol
from zoneinfo import ZoneInfo

from ..models import OrderStatus, OrderType
from ..models.account import Account
from ..models.order import Order
from ..models.position import Position
from ..models.stock import Stock
from ..utils.logger import get_logger
from .duplicate_checker import DuplicateOrderChecker
from .order_validator import OrderValidator
from .risk_manager import RiskManager

KST = ZoneInfo("Asia/Seoul")
logger = get_logger(__name__)


class KiwoomClientProtocol(Protocol):
    """Kiwoom API 클라이언트 프로토콜.

    실제 KiwoomClient와 KiwoomSimulator가 이 인터페이스를 구현해야 합니다.
    """

    async def submit_order(self, order: Order) -> Order:
        """주문을 제출합니다.

        Args:
            order: 제출할 주문

        Returns:
            체결 결과가 반영된 주문 객체
        """
        ...

    async def get_account(self) -> Account:
        """계좌 정보를 조회합니다.

        Returns:
            계좌 정보
        """
        ...

    async def get_stock_price(self, stock_code: str) -> Stock:
        """현재 주식 가격을 조회합니다.

        Args:
            stock_code: 종목 코드

        Returns:
            Stock: 종목 정보 (현재가 포함)
        """
        ...


class OrderExecutor:
    """주문 실행기.

    주문 검증, 제출, 상태 추적을 담당합니다.
    """

    def __init__(
        self,
        client: KiwoomClientProtocol,
        pending_orders: Dict[str, Order],
        positions: Dict[str, Position],
        risk_manager: Optional[RiskManager] = None
    ):
        """OrderExecutor를 초기화합니다.

        Args:
            client: Kiwoom API 클라이언트 (실제 또는 Simulator)
            pending_orders: 진행 중인 주문 딕셔너리 (order_id -> Order)
            positions: 현재 포지션 딕셔너리 (stock_code -> Position)
            risk_manager: 위험 관리자 (T086). None이면 기본 설정으로 생성.
        """
        self.client = client
        self.pending_orders = pending_orders
        self.positions = positions
        self.validator = OrderValidator()
        self.duplicate_checker = DuplicateOrderChecker(pending_orders)
        
        # T086: RiskManager 통합
        self.risk_manager = risk_manager or RiskManager(
            daily_loss_limit_pct=Decimal("0.02"),  # 기본값: 2%
            max_position_concentration=Decimal("0.3"),  # 기본값: 30%
            warning_threshold=Decimal("0.8")  # 기본값: 80%
        )

    async def execute_order(self, order: Order) -> tuple[bool, Optional[str], Optional[Order]]:
        """주문을 검증하고 실행합니다.

        Args:
            order: 실행할 주문

        Returns:
            (성공 여부, 오류 메시지, 체결된 주문) 튜플.
            성공 시 (True, None, 체결된_주문), 실패 시 (False, 오류_메시지, None)

        Examples:
            >>> executor = OrderExecutor(client, pending_orders, positions)
            >>> order = Order(...)
            >>> success, error, filled_order = await executor.execute_order(order)
        """
        logger.info(
            f"주문 실행 시작: {order.order_type.value} {order.stock_code} "
            f"{order.quantity}주 (주문ID: {order.order_id})"
        )

        try:
            # 1. 가격 정보 검증
            is_valid, error_msg = self.validator.validate_order_price(order)
            if not is_valid:
                logger.warning(f"주문 가격 검증 실패: {error_msg}")
                return False, error_msg, None

            # 2. 중복 주문 체크
            is_duplicate, existing_order_id = self.duplicate_checker.check_duplicate(
                order.stock_code,
                order.order_type
            )
            if is_duplicate:
                error_msg = (
                    f"중복 주문 차단: 종목 {order.stock_code}에 대한 "
                    f"{order.order_type.value} 주문이 이미 진행 중입니다 "
                    f"(기존 주문ID: {existing_order_id})"
                )
                logger.warning(error_msg)
                return False, error_msg, None

            # 3. 계좌 정보 조회
            account = await self.client.get_account()

            # T086: 4. 위험 관리 검증 (주문 전)
            should_stop, risk_message = self.risk_manager.should_stop_trading(
                account,
                list(self.positions.values())
            )

            if should_stop:
                logger.error(f"[위험 관리] 거래 중단: {risk_message}")
                order.status = OrderStatus.REJECTED
                order.error_message = f"[위험 관리] {risk_message}"
                return False, risk_message, None

            # 경고 메시지가 있다면 로그 출력 (중단은 아님)
            if risk_message:
                logger.warning(f"[위험 관리] 경고: {risk_message}")

            # 5. 현재 가격 조회
            stock_info = await self.client.get_stock_price(order.stock_code)
            current_price = stock_info.current_price

            # # 6. 주문 유형별 검증
            if order.order_type == OrderType.BUY:
                is_valid, error_msg = self.validator.validate_buy_order(
                    account,
                    order,
                    current_price
                )
            else:  # SELL
                position = self.positions.get(order.stock_code)
                is_valid, error_msg = self.validator.validate_sell_order(
                    position,
                    order
                )

            if not is_valid:
                logger.warning(f"주문 검증 실패: {error_msg}")
                order.status = OrderStatus.REJECTED
                order.error_message = error_msg
                return False, error_msg, None

            # # 7. 주문 제출
            logger.info(f"주문 제출 중: {order.order_id}")
            order.status = OrderStatus.SUBMITTED
            order.submitted_at = datetime.now(tz=KST)

            # 진행 중인 주문에 추가
            self.pending_orders[order.order_id] = order

            # API 호출
            filled_order = await self.client.submit_order(order)

            # # 8. 체결 결과 처리
            if filled_order.status == OrderStatus.FILLED:
                logger.info(
                    f"주문 체결 완료: {filled_order.order_id} - "
                    f"{filled_order.filled_quantity}주 @ {filled_order.filled_price:,}원"
                )
                # 진행 중인 주문에서 제거
                self.pending_orders.pop(filled_order.order_id, None)
                return True, None, filled_order

            elif filled_order.status in {OrderStatus.REJECTED, OrderStatus.FAILED}:
                error_msg = filled_order.error_message or "주문 실패"
                logger.error(f"주문 실패: {filled_order.order_id} - {error_msg}")
                # 진행 중인 주문에서 제거
                self.pending_orders.pop(filled_order.order_id, None)
                return False, error_msg, filled_order

            else:
                # SUBMITTED, PARTIALLY_FILLED 상태는 계속 진행 중
                logger.info(
                    f"주문 진행 중: {filled_order.order_id} - "
                    f"상태: {filled_order.status.value}"
                )
                return True, None, filled_order

        except Exception as e:
            error_msg = f"주문 실행 중 예외 발생: {str(e)}"
            logger.error(error_msg, exc_info=True)
            order.status = OrderStatus.FAILED
            order.error_message = error_msg
            self.pending_orders.pop(order.order_id, None)
            return False, error_msg, None

    async def cancel_order(self, order_id: str) -> tuple[bool, Optional[str]]:
        """주문을 취소합니다.

        Args:
            order_id: 취소할 주문 ID

        Returns:
            (성공 여부, 오류 메시지) 튜플.
            성공 시 (True, None), 실패 시 (False, 오류_메시지)

        Examples:
            >>> executor = OrderExecutor(client, pending_orders, positions)
            >>> success, error = await executor.cancel_order("order_123")
        """
        logger.info(f"주문 취소 요청: {order_id}")

        order = self.pending_orders.get(order_id)
        if not order:
            error_msg = f"주문을 찾을 수 없습니다: {order_id}"
            logger.warning(error_msg)
            return False, error_msg

        # 이미 종료 상태인 주문은 취소 불가
        if order.status in {OrderStatus.FILLED, OrderStatus.CANCELLED,
                           OrderStatus.REJECTED, OrderStatus.FAILED}:
            error_msg = f"주문 상태가 {order.status.value}이므로 취소할 수 없습니다"
            logger.warning(error_msg)
            return False, error_msg

        try:
            # 실제 구현에서는 client.cancel_order(order_id)를 호출해야 함
            # 여기서는 간소화하여 상태만 변경
            order.status = OrderStatus.CANCELLED
            self.pending_orders.pop(order_id, None)
            logger.info(f"주문 취소 완료: {order_id}")
            return True, None

        except Exception as e:
            error_msg = f"주문 취소 중 예외 발생: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg

    def get_order_status(self, order_id: str) -> Optional[Order]:
        """주문 상태를 조회합니다.

        Args:
            order_id: 조회할 주문 ID

        Returns:
            주문 객체 (없으면 None)

        Examples:
            >>> executor = OrderExecutor(client, pending_orders, positions)
            >>> order = executor.get_order_status("order_123")
        """
        return self.pending_orders.get(order_id)

    def get_pending_orders_by_stock(self, stock_code: str) -> list[Order]:
        """특정 종목의 진행 중인 주문 목록을 반환합니다.

        Args:
            stock_code: 종목 코드

        Returns:
            진행 중인 주문 리스트

        Examples:
            >>> executor = OrderExecutor(client, pending_orders, positions)
            >>> orders = executor.get_pending_orders_by_stock("005930")
        """
        return [
            order for order in self.pending_orders.values()
            if order.stock_code == stock_code
        ]
