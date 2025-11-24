"""RiskManager 단위 테스트."""

from decimal import Decimal

import pytest

from src.models.account import Account
from src.models.position import Position
from src.services.risk_manager import RiskManager, TriggerAction


class TestRiskManagerInitialization:
    """RiskManager 초기화 테스트."""

    def test_initialization_with_default_values(self):
        """기본값으로 초기화 성공."""
        # When
        risk_manager = RiskManager()

        # Then
        assert risk_manager.daily_loss_limit_pct == Decimal("0.02")
        assert risk_manager.max_position_concentration == Decimal("0.3")
        assert risk_manager.warning_threshold == Decimal("0.8")

    def test_initialization_with_custom_values(self):
        """커스텀 값으로 초기화 성공."""
        # When
        risk_manager = RiskManager(
            daily_loss_limit_pct=Decimal("0.05"),
            max_position_concentration=Decimal("0.2"),
            warning_threshold=Decimal("0.7")
        )

        # Then
        assert risk_manager.daily_loss_limit_pct == Decimal("0.05")
        assert risk_manager.max_position_concentration == Decimal("0.2")
        assert risk_manager.warning_threshold == Decimal("0.7")

    def test_initialization_with_invalid_daily_loss_limit(self):
        """잘못된 일일 손실 한도로 초기화 실패."""
        # When/Then
        with pytest.raises(ValueError, match="일일 손실 한도 비율은 0과 1 사이여야 합니다"):
            RiskManager(daily_loss_limit_pct=Decimal("1.5"))

        with pytest.raises(ValueError, match="일일 손실 한도 비율은 0과 1 사이여야 합니다"):
            RiskManager(daily_loss_limit_pct=Decimal("0"))

    def test_initialization_with_invalid_position_concentration(self):
        """잘못된 포지션 집중도로 초기화 실패."""
        # When/Then
        with pytest.raises(ValueError, match="포지션 집중도는 0과 1 사이여야 합니다"):
            RiskManager(max_position_concentration=Decimal("1.5"))

        with pytest.raises(ValueError, match="포지션 집중도는 0과 1 사이여야 합니다"):
            RiskManager(max_position_concentration=Decimal("0"))

    def test_initialization_with_invalid_warning_threshold(self):
        """잘못된 경고 임계값으로 초기화 실패."""
        # When/Then
        with pytest.raises(ValueError, match="경고 임계값은 0과 1 사이여야 합니다"):
            RiskManager(warning_threshold=Decimal("1.5"))

        with pytest.raises(ValueError, match="경고 임계값은 0과 1 사이여야 합니다"):
            RiskManager(warning_threshold=Decimal("0"))


class TestRiskManagerDailyLossLimit:
    """일일 손실 한도 체크 테스트."""

    def test_check_daily_loss_limit_normal(self):
        """정상 범위 내 손익 - 경고 없음."""
        # Given
        risk_manager = RiskManager(
            daily_loss_limit_pct=Decimal("0.02"),  # 2% 손실 한도
            warning_threshold=Decimal("0.8")  # 80% 경고
        )

        account = Account(
            account_number="12345678",
            name="테스트계좌",
            cash_balance=Decimal("9900000"),
            total_asset_value=Decimal("9900000"),
            daily_pnl=Decimal("-100000")  # -10만원 손실 (1%)
        )

        # When
        exceeded, message = risk_manager.check_daily_loss_limit(account)

        # Then
        assert exceeded is False
        assert message is None

    def test_check_daily_loss_limit_warning(self):
        """손실 한도의 80% 도달 - 경고 발생."""
        # Given
        risk_manager = RiskManager(
            daily_loss_limit_pct=Decimal("0.02"),  # 2% 손실 한도
            warning_threshold=Decimal("0.8")  # 80% 경고
        )

        # 장 시작 자산: 1000만원
        # 손실 한도: 20만원 (2%)
        # 경고 임계: 16만원 (80%)
        account = Account(
            account_number="12345678",
            name="테스트계좌",
            cash_balance=Decimal("9840000"),
            total_asset_value=Decimal("9840000"),
            daily_pnl=Decimal("-160000")  # -16만원 손실 (80%)
        )

        # When
        exceeded, message = risk_manager.check_daily_loss_limit(account)

        # Then
        assert exceeded is False
        assert message is not None
        assert "[경고]" in message
        assert "80.0%" in message

    def test_check_daily_loss_limit_exceeded(self):
        """손실 한도 초과 - 비상 상황."""
        # Given
        risk_manager = RiskManager(
            daily_loss_limit_pct=Decimal("0.02"),  # 2% 손실 한도
            warning_threshold=Decimal("0.8")
        )

        # 장 시작 자산: 1000만원
        # 손실 한도: 20만원 (2%)
        account = Account(
            account_number="12345678",
            name="테스트계좌",
            cash_balance=Decimal("9800000"),
            total_asset_value=Decimal("9800000"),
            daily_pnl=Decimal("-200000")  # -20만원 손실 (2%)
        )

        # When
        exceeded, message = risk_manager.check_daily_loss_limit(account)

        # Then
        assert exceeded is True
        assert message is not None
        assert "[비상]" in message
        assert "일일 손실 한도를 초과했습니다" in message

    def test_check_daily_loss_limit_with_profit(self):
        """수익 상태 - 정상."""
        # Given
        risk_manager = RiskManager(
            daily_loss_limit_pct=Decimal("0.02"),
            warning_threshold=Decimal("0.8")
        )

        account = Account(
            account_number="12345678",
            name="테스트계좌",
            cash_balance=Decimal("10200000"),
            total_asset_value=Decimal("10200000"),
            daily_pnl=Decimal("200000")  # +20만원 수익
        )

        # When
        exceeded, message = risk_manager.check_daily_loss_limit(account)

        # Then
        assert exceeded is False
        assert message is None

    def test_check_daily_loss_limit_edge_case_exact_limit(self):
        """손실이 정확히 한도와 같은 경우 - 초과로 간주."""
        # Given
        risk_manager = RiskManager(
            daily_loss_limit_pct=Decimal("0.02"),
            warning_threshold=Decimal("0.8")
        )

        # 장 시작 자산: 1000만원
        # 손실 한도: 20만원
        account = Account(
            account_number="12345678",
            name="테스트계좌",
            cash_balance=Decimal("9800000"),
            total_asset_value=Decimal("9800000"),
            daily_pnl=Decimal("-200000")  # 정확히 -20만원
        )

        # When
        exceeded, message = risk_manager.check_daily_loss_limit(account)

        # Then
        assert exceeded is True  # >= 이므로 초과로 간주

    def test_check_daily_loss_limit_with_large_loss(self):
        """매우 큰 손실 - 한도 초과."""
        # Given
        risk_manager = RiskManager(
            daily_loss_limit_pct=Decimal("0.02"),
            warning_threshold=Decimal("0.8")
        )

        account = Account(
            account_number="12345678",
            name="테스트계좌",
            cash_balance=Decimal("9000000"),
            total_asset_value=Decimal("9000000"),
            daily_pnl=Decimal("-1000000")  # -100만원 손실 (10%)
        )

        # When
        exceeded, message = risk_manager.check_daily_loss_limit(account)

        # Then
        assert exceeded is True
        assert "[비상]" in message

    def test_check_daily_loss_limit_complex_scenario(self):
        """복잡한 시나리오: 손익과 자산 평가액 변동."""
        # Given
        risk_manager = RiskManager(
            daily_loss_limit_pct=Decimal("0.02"),
            warning_threshold=Decimal("0.8")
        )

        # 장 시작 자산: 2000만원
        # 현재 총 평가액: 1950만원
        # 당일 손익: -50만원
        # 손실 한도: 40만원 (2%)
        account = Account(
            account_number="12345678",
            name="테스트계좌",
            cash_balance=Decimal("5000000"),
            total_asset_value=Decimal("19500000"),
            daily_pnl=Decimal("-500000")  # -50만원 손실
        )

        # When
        exceeded, message = risk_manager.check_daily_loss_limit(account)

        # Then
        assert exceeded is True  # 50만원 > 40만원 (한도)
        assert "[비상]" in message


class TestRiskManagerPositionConcentration:
    """포지션 집중도 체크 테스트."""

    def test_check_position_concentration_normal(self):
        """정상 범위 내 포지션 집중도 - 문제 없음."""
        # Given
        risk_manager = RiskManager(
            max_position_concentration=Decimal("0.3")  # 30% 집중도 한도
        )

        positions = [
            Position(
                account_number="12345678",
                stock_code="005930",
                quantity=100,
                average_buy_price=Decimal("70000"),
                current_price=Decimal("72000")
            ),  # 평가액: 720만원
            Position(
                account_number="12345678",
                stock_code="000660",
                quantity=50,
                average_buy_price=Decimal("100000"),
                current_price=Decimal("105000")
            )  # 평가액: 525만원
        ]

        total_asset_value = Decimal("50000000")  # 총 5000만원

        # When
        exceeded, message = risk_manager.check_position_concentration(
            positions,
            total_asset_value
        )

        # Then
        assert exceeded is False
        assert message is None

    def test_check_position_concentration_exceeded(self):
        """포지션 집중도 초과 - 경고 발생."""
        # Given
        risk_manager = RiskManager(
            max_position_concentration=Decimal("0.3")  # 30% 집중도 한도
        )

        positions = [
            Position(
                account_number="12345678",
                stock_code="005930",
                quantity=500,
                average_buy_price=Decimal("70000"),
                current_price=Decimal("72000")
            )  # 평가액: 3600만원 (40%)
        ]

        total_asset_value = Decimal("90000000")  # 총 9000만원

        # When
        exceeded, message = risk_manager.check_position_concentration(
            positions,
            total_asset_value
        )

        # Then
        assert exceeded is True
        assert message is not None
        assert "[주의]" in message
        assert "005930" in message
        assert "40.0%" in message

    def test_check_position_concentration_exactly_at_limit(self):
        """포지션 집중도가 정확히 한도 - 정상."""
        # Given
        risk_manager = RiskManager(
            max_position_concentration=Decimal("0.3")
        )

        positions = [
            Position(
                account_number="12345678",
                stock_code="005930",
                quantity=300,
                average_buy_price=Decimal("100000"),
                current_price=Decimal("100000")
            )  # 평가액: 3000만원 (정확히 30%)
        ]

        total_asset_value = Decimal("100000000")  # 총 1억원

        # When
        exceeded, message = risk_manager.check_position_concentration(
            positions,
            total_asset_value
        )

        # Then
        assert exceeded is False  # <= 이므로 정상
        assert message is None

    def test_check_position_concentration_multiple_positions_one_exceeds(self):
        """여러 포지션 중 하나만 집중도 초과."""
        # Given
        risk_manager = RiskManager(
            max_position_concentration=Decimal("0.3")
        )

        positions = [
            Position(
                account_number="12345678",
                stock_code="005930",
                quantity=200,
                average_buy_price=Decimal("70000"),
                current_price=Decimal("75000")
            ),  # 평가액: 1500만원 (15%)
            Position(
                account_number="12345678",
                stock_code="000660",
                quantity=400,
                average_buy_price=Decimal("100000"),
                current_price=Decimal("110000")
            )  # 평가액: 4400만원 (44%)
        ]

        total_asset_value = Decimal("100000000")  # 총 1억원

        # When
        exceeded, message = risk_manager.check_position_concentration(
            positions,
            total_asset_value
        )

        # Then
        assert exceeded is True
        assert "000660" in message
        assert "44.0%" in message

    def test_check_position_concentration_empty_positions(self):
        """포지션이 없는 경우 - 정상."""
        # Given
        risk_manager = RiskManager(
            max_position_concentration=Decimal("0.3")
        )

        positions = []
        total_asset_value = Decimal("10000000")

        # When
        exceeded, message = risk_manager.check_position_concentration(
            positions,
            total_asset_value
        )

        # Then
        assert exceeded is False
        assert message is None

    def test_check_position_concentration_invalid_total_asset(self):
        """총 자산이 0 이하인 경우 - 예외 발생."""
        # Given
        risk_manager = RiskManager()

        positions = [
            Position(
                account_number="12345678",
                stock_code="005930",
                quantity=100,
                average_buy_price=Decimal("70000"),
                current_price=Decimal("72000")
            )
        ]

        # When/Then
        with pytest.raises(ValueError, match="총 자산 평가액은 0보다 커야 합니다"):
            risk_manager.check_position_concentration(positions, Decimal("0"))

        with pytest.raises(ValueError, match="총 자산 평가액은 0보다 커야 합니다"):
            risk_manager.check_position_concentration(positions, Decimal("-1000000"))

    def test_check_position_concentration_high_concentration_custom_limit(self):
        """커스텀 집중도 한도 테스트 - 20%."""
        # Given
        risk_manager = RiskManager(
            max_position_concentration=Decimal("0.2")  # 20% 한도
        )

        positions = [
            Position(
                account_number="12345678",
                stock_code="005930",
                quantity=250,
                average_buy_price=Decimal("80000"),
                current_price=Decimal("80000")
            )  # 평가액: 2000만원 (25%)
        ]

        total_asset_value = Decimal("80000000")  # 총 8000만원

        # When
        exceeded, message = risk_manager.check_position_concentration(
            positions,
            total_asset_value
        )

        # Then
        assert exceeded is True
        assert "25.0%" in message
        assert "20%" in message


class TestRiskManagerStopLossTakeProfit:
    """Phase 5: Stop-Loss/Take-Profit 모니터링 테스트."""

    def test_check_position_trigger_stop_loss_triggered(self):
        """손절가 트리거 발생 - 현재가가 손절가 이하."""
        # Given
        risk_manager = RiskManager()

        position = Position(
            account_number="12345678",
            stock_code="005930",
            quantity=100,
            average_buy_price=Decimal("70000"),
            current_price=Decimal("63000"),  # 10% 하락
            stop_loss_price=Decimal("63000"),  # 손절가 설정
            take_profit_price=Decimal("77000")
        )

        # When
        triggered, action, message = risk_manager.check_position_trigger(position)

        # Then
        assert triggered is True
        assert action == TriggerAction.STOP_LOSS
        assert message is not None
        assert "[STOP-LOSS]" in message
        assert "005930" in message
        assert "63,000" in message

    def test_check_position_trigger_take_profit_triggered(self):
        """익절가 트리거 발생 - 현재가가 익절가 이상."""
        # Given
        risk_manager = RiskManager()

        position = Position(
            account_number="12345678",
            stock_code="005930",
            quantity=100,
            average_buy_price=Decimal("70000"),
            current_price=Decimal("77000"),  # 10% 상승
            stop_loss_price=Decimal("63000"),
            take_profit_price=Decimal("77000")  # 익절가 설정
        )

        # When
        triggered, action, message = risk_manager.check_position_trigger(position)

        # Then
        assert triggered is True
        assert action == TriggerAction.TAKE_PROFIT
        assert message is not None
        assert "[TAKE-PROFIT]" in message
        assert "005930" in message
        assert "77,000" in message

    def test_check_position_trigger_no_trigger(self):
        """트리거 없음 - 현재가가 정상 범위."""
        # Given
        risk_manager = RiskManager()

        position = Position(
            account_number="12345678",
            stock_code="005930",
            quantity=100,
            average_buy_price=Decimal("70000"),
            current_price=Decimal("70000"),  # 변동 없음
            stop_loss_price=Decimal("63000"),
            take_profit_price=Decimal("77000")
        )

        # When
        triggered, action, message = risk_manager.check_position_trigger(position)

        # Then
        assert triggered is False
        assert action is None
        assert message is None

    def test_check_position_trigger_no_stop_loss_set(self):
        """손절가가 설정되지 않은 경우 - 트리거 없음."""
        # Given
        risk_manager = RiskManager()

        position = Position(
            account_number="12345678",
            stock_code="005930",
            quantity=100,
            average_buy_price=Decimal("70000"),
            current_price=Decimal("60000"),  # 큰 하락이지만 손절가 미설정
            stop_loss_price=None,  # 손절가 미설정
            take_profit_price=Decimal("77000")
        )

        # When
        triggered, action, message = risk_manager.check_position_trigger(position)

        # Then
        assert triggered is False
        assert action is None
        assert message is None

    def test_check_position_trigger_stop_loss_priority_over_take_profit(self):
        """손절가와 익절가 동시 트리거 시 손절가 우선."""
        # Given
        risk_manager = RiskManager()

        # 비현실적이지만 테스트를 위해: 손절가와 익절가 모두 트리거
        position = Position(
            account_number="12345678",
            stock_code="005930",
            quantity=100,
            average_buy_price=Decimal("70000"),
            current_price=Decimal("70000"),
            stop_loss_price=Decimal("70000"),  # 현재가와 동일 (트리거)
            take_profit_price=Decimal("70000")  # 현재가와 동일 (트리거)
        )

        # When
        triggered, action, message = risk_manager.check_position_trigger(position)

        # Then
        assert triggered is True
        assert action == TriggerAction.STOP_LOSS  # 손절가 우선
        assert "[STOP-LOSS]" in message

    def test_monitor_all_positions_multiple_triggers(self):
        """여러 포지션 중 일부만 트리거 발생."""
        # Given
        risk_manager = RiskManager()

        positions = [
            Position(
                account_number="12345678",
                stock_code="005930",
                quantity=100,
                average_buy_price=Decimal("70000"),
                current_price=Decimal("63000"),  # 손절 트리거
                stop_loss_price=Decimal("63000"),
                take_profit_price=Decimal("77000")
            ),
            Position(
                account_number="12345678",
                stock_code="000660",
                quantity=50,
                average_buy_price=Decimal("100000"),
                current_price=Decimal("105000"),  # 정상 범위
                stop_loss_price=Decimal("90000"),
                take_profit_price=Decimal("110000")
            ),
            Position(
                account_number="12345678",
                stock_code="035720",
                quantity=200,
                average_buy_price=Decimal("50000"),
                current_price=Decimal("55000"),  # 익절 트리거
                stop_loss_price=Decimal("45000"),
                take_profit_price=Decimal("55000")
            )
        ]

        # When
        triggered_list = risk_manager.monitor_all_positions(positions)

        # Then
        assert len(triggered_list) == 2

        # 첫 번째: 005930 손절
        pos1, action1, msg1 = triggered_list[0]
        assert pos1.stock_code == "005930"
        assert action1 == TriggerAction.STOP_LOSS
        assert "[STOP-LOSS]" in msg1

        # 두 번째: 035720 익절
        pos2, action2, msg2 = triggered_list[1]
        assert pos2.stock_code == "035720"
        assert action2 == TriggerAction.TAKE_PROFIT
        assert "[TAKE-PROFIT]" in msg2

    def test_monitor_all_positions_no_triggers(self):
        """모든 포지션이 정상 범위 - 트리거 없음."""
        # Given
        risk_manager = RiskManager()

        positions = [
            Position(
                account_number="12345678",
                stock_code="005930",
                quantity=100,
                average_buy_price=Decimal("70000"),
                current_price=Decimal("70000"),
                stop_loss_price=Decimal("63000"),
                take_profit_price=Decimal("77000")
            ),
            Position(
                account_number="12345678",
                stock_code="000660",
                quantity=50,
                average_buy_price=Decimal("100000"),
                current_price=Decimal("105000"),
                stop_loss_price=Decimal("90000"),
                take_profit_price=Decimal("110000")
            )
        ]

        # When
        triggered_list = risk_manager.monitor_all_positions(positions)

        # Then
        assert len(triggered_list) == 0

    def test_monitor_all_positions_empty_list(self):
        """포지션이 없는 경우 - 빈 리스트 반환."""
        # Given
        risk_manager = RiskManager()
        positions = []

        # When
        triggered_list = risk_manager.monitor_all_positions(positions)

        # Then
        assert len(triggered_list) == 0

    def test_stop_loss_message_includes_loss_info(self):
        """손절 메시지에 손실 정보 포함 확인."""
        # Given
        risk_manager = RiskManager()

        position = Position(
            account_number="12345678",
            stock_code="005930",
            quantity=100,
            average_buy_price=Decimal("70000"),
            current_price=Decimal("63000"),  # 7000원 * 100주 = 70만원 손실
            stop_loss_price=Decimal("63000")
        )

        # When
        triggered, action, message = risk_manager.check_position_trigger(position)

        # Then
        assert triggered is True
        assert "700,000" in message  # 예상 손실 70만원
        assert "-10.00%" in message  # 손실률 10%

    def test_take_profit_message_includes_profit_info(self):
        """익절 메시지에 수익 정보 포함 확인."""
        # Given
        risk_manager = RiskManager()

        position = Position(
            account_number="12345678",
            stock_code="005930",
            quantity=100,
            average_buy_price=Decimal("70000"),
            current_price=Decimal("77000"),  # 7000원 * 100주 = 70만원 수익
            take_profit_price=Decimal("77000")
        )

        # When
        triggered, action, message = risk_manager.check_position_trigger(position)

        # Then
        assert triggered is True
        assert "700,000" in message  # 예상 수익 70만원
        assert "10.00%" in message  # 수익률 10%
