"""위험 관리 서비스 모듈.

이 모듈은 자동매매 시스템의 위험 관리 기능을 제공합니다.
일일 손실 한도(%), 포지션 집중도 체크, 거래 중단 판단 등의 기능을 포함합니다.
Phase 5: 실시간 Stop-Loss/Take-Profit 모니터링 기능 추가.
"""

from decimal import Decimal
from enum import Enum
from typing import List, Optional, Tuple

from ..models.account import Account
from ..models.position import Position


class TriggerAction(str, Enum):
    """포지션 트리거 액션 타입.

    Attributes:
        STOP_LOSS: 손절 트리거 발생.
        TAKE_PROFIT: 익절 트리거 발생.
    """
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"


class RiskManager:
    """위험 관리자 클래스.

    일일 손실 한도(비율), 포지션 집중도 등의 위험 요소를 관리하고
    거래 중단 여부를 판단합니다.

    Attributes:
        daily_loss_limit_pct: 일일 손실 한도 비율 (0.0~1.0, 기본값 0.02 = 2%)
        max_position_concentration: 종목별 최대 집중도 (0.0~1.0, 기본값 0.3 = 30%)
        warning_threshold: 손실 한도 경고 임계값 (0.0~1.0, 기본값 0.8 = 80%)

    Example:
        >>> risk_manager = RiskManager(
        ...     daily_loss_limit_pct=Decimal("0.02"),  # 자산의 2% 손실 시 중단
        ...     max_position_concentration=Decimal("0.3"),
        ...     warning_threshold=Decimal("0.8")
        ... )
    """

    def __init__(
        self,
        daily_loss_limit_pct: Decimal = Decimal("0.02"),
        max_position_concentration: Decimal = Decimal("0.3"),
        warning_threshold: Decimal = Decimal("0.8")
    ):
        """RiskManager 초기화.

        Args:
            daily_loss_limit_pct: 일일 손실 한도 비율 (기본값 0.02 = 2%)
            max_position_concentration: 종목별 최대 집중도 (기본값 0.3 = 30%)
            warning_threshold: 손실 한도 경고 임계값 (기본값 0.8 = 80%)
        """
        if not (0 < daily_loss_limit_pct <= 1):
            raise ValueError("일일 손실 한도 비율은 0과 1 사이여야 합니다")

        if not (0 < max_position_concentration <= 1):
            raise ValueError("포지션 집중도는 0과 1 사이여야 합니다")

        if not (0 < warning_threshold <= 1):
            raise ValueError("경고 임계값은 0과 1 사이여야 합니다")

        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.max_position_concentration = max_position_concentration
        self.warning_threshold = warning_threshold

    def check_daily_loss_limit(
        self,
        account: Account
    ) -> Tuple[bool, Optional[str]]:
        """일일 손실 한도를 체크합니다.

        계좌의 `장 시작 전 추정 자산` 대비 당일 손익(daily_pnl) 비율을 계산합니다.
        
        Logic:
            장 시작 자산 = 현재 총자산(total_asset_value) - 당일 손익(daily_pnl)
            손실 한도 금액 = 장 시작 자산 * 손실 한도 비율

        Args:
            account: 체크할 계좌 정보

        Returns:
            Tuple[bool, Optional[str]]:
                - bool: 손실 한도 초과 여부 (True: 초과/중단, False: 정상)
                - Optional[str]: 메시지
        """
        # 장 시작 전 자산 역산 (현재 자산 - 당일 손익)
        # 예: 현재 960만, 손익 -40만 -> 시작 자산 1000만
        start_of_day_asset = account.total_asset_value - account.daily_pnl
        
        if start_of_day_asset <= 0:
            # 자산 데이터 오류 시 안전을 위해 보수적으로 현재 자산 기준 처리 혹은 예외
            start_of_day_asset = account.total_asset_value

        # 허용 가능한 최대 손실 금액 계산
        loss_limit_amount = start_of_day_asset * self.daily_loss_limit_pct
        
        # 현재 손실 금액 (양수로 변환)
        current_loss = abs(account.daily_pnl) if account.daily_pnl < 0 else Decimal("0")

        # 1. 손실 한도 초과 확인
        if current_loss >= loss_limit_amount:
            message = (
                f"[비상] 일일 손실 한도를 초과했습니다.\n"
                f"- 설정 비율: {self.daily_loss_limit_pct * 100}%\n"
                f"- 한도 금액: {loss_limit_amount:,.0f}원\n"
                f"- 현재 손실: {current_loss:,.0f}원"
            )
            return True, message

        # 2. 손실 한도의 80% 도달 확인 (경고)
        warning_amount = loss_limit_amount * self.warning_threshold
        if current_loss >= warning_amount:
            usage_pct = (current_loss / loss_limit_amount) * 100
            message = (
                f"[경고] 일일 손실 한도의 {usage_pct:.1f}%에 도달했습니다.\n"
                f"- 현재 손실: {current_loss:,.0f}원 / 한도: {loss_limit_amount:,.0f}원"
            )
            return False, message

        # 정상 범위
        return False, None

    def check_position_concentration(
        self,
        positions: List[Position],
        total_asset_value: Decimal
    ) -> Tuple[bool, Optional[str]]:
        """포지션 집중도를 체크합니다."""
        if total_asset_value <= 0:
            raise ValueError("총 자산 평가액은 0보다 커야 합니다")

        if not positions:
            return False, None

        for position in positions:
            position_value = position.evaluation_amount
            concentration = position_value / total_asset_value

            if concentration > self.max_position_concentration:
                message = (
                    f"[주의] 종목 {position.stock_code} 집중도 초과\n"
                    f"- 현재: {concentration * 100:.1f}% (한도: {self.max_position_concentration * 100:.0f}%)"
                )
                return True, message

        return False, None

    def should_stop_trading(
        self,
        account: Account,
        positions: List[Position]
    ) -> Tuple[bool, Optional[str]]:
        """거래 중단 여부를 판단합니다."""
        messages = []
        should_stop = False

        # 1. 일일 손실 한도 체크
        loss_exceeded, loss_message = self.check_daily_loss_limit(account)
        if loss_message:
            messages.append(loss_message)
        
        # 손실 한도 초과 시 즉시 중단 (True)
        if loss_exceeded:
            return True, f"[STOP] 거래 강제 종료 사유 발생: {loss_message}"

        # 2. 포지션 집중도 체크 (경고만 수집)
        _, concentration_message = self.check_position_concentration(
            positions,
            account.total_asset_value
        )
        if concentration_message:
            messages.append(concentration_message)

        # 경고 메시지가 있다면 합쳐서 반환, 중단은 아님
        if messages:
            return False, " | ".join(messages)

        return False, None

    def check_position_trigger(
        self,
        position: Position
    ) -> Tuple[bool, Optional[TriggerAction], Optional[str]]:
        """단일 포지션의 손절/익절 트리거를 확인합니다.

        Args:
            position: 확인할 포지션.

        Returns:
            Tuple[bool, Optional[TriggerAction], Optional[str]]:
                - bool: 트리거 발생 여부
                - Optional[TriggerAction]: 트리거 액션 타입 (STOP_LOSS 또는 TAKE_PROFIT)
                - Optional[str]: 트리거 메시지

        Examples:
            >>> position = Position(...)
            >>> triggered, action, message = risk_manager.check_position_trigger(position)
            >>> if triggered:
            ...     print(f"Action: {action}, Message: {message}")
        """
        # 1. 손절가 트리거 확인 (우선순위 높음)
        if position.check_stop_loss_triggered():
            loss_amount = (position.average_buy_price - position.current_price) * position.quantity
            loss_rate = ((position.current_price - position.average_buy_price)
                        / position.average_buy_price * 100)

            message = (
                f"[STOP-LOSS] 종목 {position.stock_code} 손절 트리거 발생\n"
                f"- 현재가: {position.current_price:,.0f}원\n"
                f"- 손절가: {position.stop_loss_price:,.0f}원\n"
                f"- 평균 매수가: {position.average_buy_price:,.0f}원\n"
                f"- 손실률: {loss_rate:.2f}%\n"
                f"- 예상 손실: {loss_amount:,.0f}원"
            )
            return True, TriggerAction.STOP_LOSS, message

        # 2. 익절가 트리거 확인
        if position.check_take_profit_triggered():
            profit_amount = (position.current_price - position.average_buy_price) * position.quantity
            profit_rate = ((position.current_price - position.average_buy_price)
                          / position.average_buy_price * 100)

            message = (
                f"[TAKE-PROFIT] 종목 {position.stock_code} 익절 트리거 발생\n"
                f"- 현재가: {position.current_price:,.0f}원\n"
                f"- 익절가: {position.take_profit_price:,.0f}원\n"
                f"- 평균 매수가: {position.average_buy_price:,.0f}원\n"
                f"- 수익률: {profit_rate:.2f}%\n"
                f"- 예상 수익: {profit_amount:,.0f}원"
            )
            return True, TriggerAction.TAKE_PROFIT, message

        return False, None, None

    def monitor_all_positions(
        self,
        positions: List[Position]
    ) -> List[Tuple[Position, TriggerAction, str]]:
        """모든 포지션의 손절/익절 트리거를 실시간 모니터링합니다.

        Args:
            positions: 모니터링할 포지션 리스트.

        Returns:
            트리거된 포지션 리스트: [(Position, TriggerAction, message), ...]
            트리거가 없으면 빈 리스트 반환.

        Examples:
            >>> positions = [position1, position2, position3]
            >>> triggered_list = risk_manager.monitor_all_positions(positions)
            >>> for position, action, message in triggered_list:
            ...     print(f"Position {position.stock_code}: {action.value}")
            ...     # 자동 매도 주문 실행
        """
        triggered_positions = []

        for position in positions:
            triggered, action, message = self.check_position_trigger(position)
            if triggered:
                triggered_positions.append((position, action, message))

        return triggered_positions