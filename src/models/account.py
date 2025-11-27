"""계좌 모델 정의."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from .stock import KST, get_kst_now


class Account(BaseModel):
    """사용자 증권 계좌 정보.

    Attributes:
        account_number: 8자리 계좌번호.
        name: 계좌명.
        cash_balance: 예수금 (현금 잔고).
        total_asset_value: 총 평가 금액 (현금 + 주식 평가액).
        total_pnl: 총 손익 (실현 + 미실현).
        daily_pnl: 당일 손익.
        daily_loss_limit: 일일 손실 한도.
        updated_at: 마지막 업데이트 시간 (KST).
    """

    account_number: str = Field(
        ..., pattern=r"^\d{8}$", description="8자리 계좌번호"
    )
    name: str = Field(default="", max_length=50, description="계좌명")
    cash_balance: Decimal = Field(..., ge=0, description="예수금 (KRW)")
    total_asset_value: Decimal = Field(..., description="총 평가 금액")
    total_pnl: Decimal = Field(default=Decimal("0"), description="총 손익")
    daily_pnl: Decimal = Field(default=Decimal("0"), description="당일 손익")
    daily_loss_limit: Decimal = Field(default=Decimal("0"), ge=0, description="일일 손실 한도")
    updated_at: datetime = Field(default_factory=get_kst_now, description="마지막 업데이트 시간")

    @field_validator("total_asset_value")
    @classmethod
    def validate_total_asset_value(cls, v: Decimal, info) -> Decimal:
        """총 평가 금액을 검증합니다.

        Note:
            API 응답에서 cash_balance(주문가능금액)와 total_asset_value(예수금)의
            관계가 항상 일관되지 않을 수 있으므로 (미수금, D+1/D+2 결제 등)
            검증을 수행하지 않고 값을 그대로 반환합니다.

        Args:
            v: 검증할 총 평가 금액.
            info: 다른 필드 값을 포함하는 검증 정보.

        Returns:
            검증된 총 평가 금액.
        """
        return v

    def is_daily_loss_limit_exceeded(self) -> bool:
        """일일 손실 한도 초과 여부를 확인합니다.

        Returns:
            일일 손익이 손실 한도를 초과한 경우 True.
        """
        return self.daily_pnl < -self.daily_loss_limit

    class Config:
        """Pydantic 설정."""

        frozen = False  # 잔고 업데이트를 위해 변경 가능
        json_encoders = {Decimal: str, datetime: lambda v: v.isoformat()}
