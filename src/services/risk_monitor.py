"""실시간 리스크 모니터링 서비스 (Phase 2).

이 모듈은 백그라운드 태스크로 실행되어 모든 포지션의 손절/익절 트리거를
1초마다 실시간으로 모니터링하고, 트리거 발생 시 자동 매도 주문을 실행합니다.
"""

import asyncio
import logging
from typing import Dict, Optional, TYPE_CHECKING

from ..models import Stock, Order, OrderType, PriceType, OrderStatus
from ..models.position import Position
from .risk_manager import RiskManager, TriggerAction

if TYPE_CHECKING:
    from .order_executor import OrderExecutor

logger = logging.getLogger(__name__)


class RiskMonitor:
    """실시간 리스크 모니터링 서비스.

    백그라운드 태스크로 실행되어 모든 포지션의 손절/익절 트리거를
    주기적으로 확인하고, 트리거 발생 시 자동 매도 주문을 실행합니다.

    Attributes:
        risk_manager: 위험 관리자 (손절/익절 트리거 체크 담당)
        order_executor: 주문 실행기 (매도 주문 제출 담당)
        positions: 현재 포지션 딕셔너리 (stock_code -> Position)
        client: 시세 조회용 클라이언트
        check_interval: 모니터링 주기 (초 단위, 기본값: 1초)
        running: 실행 상태 플래그
        monitor_task: 백그라운드 모니터링 태스크
    """

    def __init__(
        self,
        risk_manager: RiskManager,
        order_executor: "OrderExecutor",
        positions: Dict[str, Position],
        client,  # KiwoomClient or KiwoomSimulator
        check_interval: float = 1.0,
        price_type: PriceType = PriceType.MARKET
    ):
        """RiskMonitor 초기화.

        Args:
            risk_manager: 위험 관리자.
            order_executor: 주문 실행기.
            positions: 현재 포지션 딕셔너리.
            client: 시세 조회용 클라이언트.
            check_interval: 모니터링 주기 (초 단위, 기본값: 1초).
            price_type: 매도 주문 가격 타입 (기본값: MARKET).
        """
        self.risk_manager = risk_manager
        self.order_executor = order_executor
        self.positions = positions
        self.client = client
        self.check_interval = check_interval
        self.price_type = price_type

        self.running = False
        self.monitor_task: Optional[asyncio.Task] = None

        logger.info(
            f"RiskMonitor 초기화 완료 (check_interval={check_interval}초)"
        )

    async def run(self) -> None:
        """실시간 리스크 모니터링 실행.

        백그라운드 태스크로 실행되어 주기적으로 포지션을 모니터링합니다.
        """
        if self.monitor_task is not None and not self.monitor_task.done():
            logger.warning("RiskMonitor가 이미 실행 중입니다")
            return

        self.monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("RiskMonitor 시작됨")

    async def stop(self) -> None:
        """리스크 모니터링 중지."""
        if not self.running:
            return

        logger.info("RiskMonitor 중지 중...")
        self.running = False

        # 모니터링 태스크 취소 대기
        if self.monitor_task and not self.monitor_task.done():
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass

        logger.info("RiskMonitor 중지 완료")

    async def _monitor_loop(self) -> None:
        """모니터링 루프 (내부 메서드).

        주기적으로 모든 포지션의 현재가를 업데이트하고
        손절/익절 트리거를 확인하여 자동 매도 주문을 실행합니다.
        """
        self.running = True
        logger.info(
            f"RiskMonitor 모니터링 루프 시작 (주기: {self.check_interval}초)"
        )

        try:
            while self.running:
                try:
                    # 1. 모든 포지션의 현재가 업데이트
                    await self._update_all_positions_price()

                    # 2. 손절/익절 트리거 확인
                    triggered_list = self.risk_manager.monitor_all_positions(
                        list(self.positions.values())
                    )

                    # 3. 트리거된 포지션에 대해 자동 매도 주문 실행
                    for position, action, message in triggered_list:
                        logger.info(message)
                        await self._execute_sell_order(position, action)

                except Exception as e:
                    logger.error(
                        f"RiskMonitor 모니터링 루프 중 오류: {e}",
                        exc_info=True
                    )

                # 다음 체크까지 대기
                await asyncio.sleep(self.check_interval)

        except asyncio.CancelledError:
            logger.info("RiskMonitor 모니터링 루프 취소됨")
            raise

        finally:
            self.running = False
            logger.info("RiskMonitor 모니터링 루프 종료")

    async def _update_all_positions_price(self) -> None:
        """모든 포지션의 현재가를 업데이트합니다 (내부 메서드).

        실시간 시세 API를 호출하여 각 포지션의 현재가를 갱신합니다.
        """
        for stock_code, position in list(self.positions.items()):
            try:
                # 현재 시세 조회
                stock_info: Stock = await self.client.get_stock_price(stock_code)
                current_price = stock_info.current_price

                # 포지션 현재가 업데이트
                position.update_price(current_price)

            except Exception as e:
                logger.error(
                    f"포지션 {stock_code} 현재가 업데이트 실패: {e}"
                )

    async def _execute_sell_order(
        self,
        position: Position,
        action: TriggerAction
    ) -> None:
        """트리거된 포지션에 대해 매도 주문을 실행합니다 (내부 메서드).

        Args:
            position: 매도할 포지션.
            action: 트리거 액션 (STOP_LOSS 또는 TAKE_PROFIT).
        """
        try:
            # 매도 주문 가격 설정
            limit_price = None
            if self.price_type == PriceType.LIMIT:
                limit_price = position.current_price

            # Order 객체 생성 (전량 매도)
            sell_order = Order(
                account_number=position.account_number,
                stock_code=position.stock_code,
                order_type=OrderType.SELL,
                price_type=self.price_type,
                quantity=position.quantity,
                limit_price=limit_price,
                strategy_name=position.strategy_name
            )

            action_str = action.value if hasattr(action, 'value') else str(action)
            price_type_str = self.price_type.value if hasattr(self.price_type, 'value') else str(self.price_type)

            logger.info(
                f"[RiskMonitor] {action_str} 매도 주문 생성: "
                f"{sell_order.stock_code} {sell_order.quantity}주 "
                f"@ {price_type_str} "
                f"(ID: {sell_order.order_id})"
            )

            # 주문 실행
            success, error_msg, filled_order = await self.order_executor.execute_order(
                sell_order
            )

            if success:
                logger.info(
                    f"[RiskMonitor] {action_str} 매도 주문 체결 성공: "
                    f"{sell_order.order_id}"
                )
                if filled_order:
                    status_str = filled_order.status.value if hasattr(filled_order.status, 'value') else str(filled_order.status)
                    logger.info(
                        f"[RiskMonitor] 체결: {filled_order.filled_quantity}주 "
                        f"@ {filled_order.filled_price:,.0f}원 "
                        f"(Status: {status_str})"
                    )
            else:
                logger.error(
                    f"[RiskMonitor] {action_str} 매도 주문 실패: {error_msg}"
                )

        except Exception as e:
            logger.error(
                f"[RiskMonitor] 매도 주문 실행 중 오류: {e}",
                exc_info=True
            )
