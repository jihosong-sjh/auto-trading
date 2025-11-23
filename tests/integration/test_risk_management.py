"""위험 관리 통합 테스트 (간소화 버전).

RiskManager가 실제 Account와 Position 데이터로 정상 작동하는지 검증합니다.
"""

from decimal import Decimal

import pytest

from src.models.account import Account
from src.models.position import Position
from src.services.risk_manager import RiskManager


class TestRiskManagementSimple:
    """위험 관리 통합 테스트 (간소화)."""

    def test_daily_loss_limit_stops_trading(self):
        """일일 손실 한도 초과 시 거래 중단."""
        # Given
        risk_manager = RiskManager(
            daily_loss_limit_pct=Decimal("0.02"),  # 2% 손실 한도 (20만원)
            warning_threshold=Decimal("0.8")
        )

        # 초기 자금 1000만원, 현재 30만원 손실
        account = Account(
            account_number="12345678",
            name="테스트계좌",
            cash_balance=Decimal("9700000"),
            total_asset_value=Decimal("9700000"),
            daily_pnl=Decimal("-300000")  # -30만원 (한도 20만원 초과)
        )

        positions = []

        # When
        should_stop, message = risk_manager.should_stop_trading(account, positions)

        # Then
        assert should_stop is True
        assert message is not None
        assert "[STOP]" in message
        assert "일일 손실 한도를 초과했습니다" in message

    def test_daily_loss_limit_warning_only(self):
        """일일 손실 한도의 80% 도달 시 경고만 발생."""
        # Given
        risk_manager = RiskManager(
            daily_loss_limit_pct=Decimal("0.02"),  # 2% 손실 한도 (20만원)
            warning_threshold=Decimal("0.8")  # 80% 경고
        )

        # 초기 자금 1000만원, 현재 16만원 손실 (80%)
        account = Account(
            account_number="12345678",
            name="테스트계좌",
            cash_balance=Decimal("9840000"),
            total_asset_value=Decimal("9840000"),
            daily_pnl=Decimal("-160000")  # -16만원 (한도의 80%)
        )

        positions = []

        # When
        should_stop, message = risk_manager.should_stop_trading(account, positions)

        # Then
        assert should_stop is False  # 경고만, 중단 아님
        assert message is not None
        assert "[경고]" in message

    def test_position_concentration_exceeds(self):
        """포지션 집중도 초과 시 경고."""
        # Given
        risk_manager = RiskManager(
            max_position_concentration=Decimal("0.3")  # 30% 한도
        )

        account = Account(
            account_number="12345678",
            name="테스트계좌",
            cash_balance=Decimal("5000000"),
            total_asset_value=Decimal("10000000")
        )

        # 한 종목에 50% 집중 (5000만원 중 2500만원)
        positions = [
            Position(
                account_number="12345678",
                stock_code="005930",
                quantity=50,
                average_buy_price=Decimal("100000"),
                current_price=Decimal("100000")
            )  # 평가액: 500만원 (50%)
        ]

        # When
        exceeded, message = risk_manager.check_position_concentration(
            positions,
            account.total_asset_value
        )

        # Then
        assert exceeded is True
        assert message is not None
        assert "[주의]" in message
        assert "005930" in message

    def test_multiple_risks_detected(self):
        """여러 위험 요소 동시 감지."""
        # Given
        risk_manager = RiskManager(
            daily_loss_limit_pct=Decimal("0.02"),
            max_position_concentration=Decimal("0.3"),
            warning_threshold=Decimal("0.8")
        )

        # 손실 한도 경고 수준
        account = Account(
            account_number="12345678",
            name="테스트계좌",
            cash_balance=Decimal("4000000"),
            total_asset_value=Decimal("9850000"),
            daily_pnl=Decimal("-150000")  # -15만원 (75%)
        )

        # 집중도 초과 포지션
        positions = [
            Position(
                account_number="12345678",
                stock_code="005930",
                quantity=60,
                average_buy_price=Decimal("100000"),
                current_price=Decimal("97500")
            )  # 평가액: 585만원 (약 59%)
        ]

        # When
        should_stop, stop_message = risk_manager.should_stop_trading(account, positions)

        # Then
        # 손실 한도는 경고 수준이므로 중단 아님
        assert should_stop is False
        # 하지만 경고 메시지는 있어야 함
        assert stop_message is not None

    def test_no_risk_normal_scenario(self):
        """정상 시나리오 - 위험 없음."""
        # Given
        risk_manager = RiskManager(
            daily_loss_limit_pct=Decimal("0.02"),
            max_position_concentration=Decimal("0.3")
        )

        account = Account(
            account_number="12345678",
            name="테스트계좌",
            cash_balance=Decimal("7000000"),
            total_asset_value=Decimal("10050000"),
            daily_pnl=Decimal("50000")  # 수익
        )

        positions = [
            Position(
                account_number="12345678",
                stock_code="005930",
                quantity=20,
                average_buy_price=Decimal("100000"),
                current_price=Decimal("102500")
            )  # 평가액: 205만원 (20.5%)
        ]

        # When
        should_stop, message = risk_manager.should_stop_trading(account, positions)

        # Then
        assert should_stop is False
        # 수익 상태이므로 경고 없음 (집중도도 정상)

    def test_exact_loss_limit(self):
        """손실이 정확히 한도와 같을 때 중단."""
        # Given
        risk_manager = RiskManager(
            daily_loss_limit_pct=Decimal("0.02")  # 2%
        )

        # 초기 1000만원, 정확히 20만원 손실
        account = Account(
            account_number="12345678",
            name="테스트계좌",
            cash_balance=Decimal("9800000"),
            total_asset_value=Decimal("9800000"),
            daily_pnl=Decimal("-200000")  # 정확히 -20만원
        )

        positions = []

        # When
        should_stop, message = risk_manager.should_stop_trading(account, positions)

        # Then
        assert should_stop is True  # >= 조건이므로 중단
        assert "[STOP]" in message
