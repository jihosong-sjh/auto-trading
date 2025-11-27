"""주식 종목 모델 정의."""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from . import MarketType

# KST 타임존
KST = ZoneInfo("Asia/Seoul")


def get_kst_now() -> datetime:
    """현재 KST 시간을 반환합니다.

    Returns:
        타임존이 적용된 현재 KST 시간.
    """
    return datetime.now(tz=KST)


class Stock(BaseModel):
    """주식 종목 정보 및 시세 데이터.

    Attributes:
        stock_code: 6자리 종목코드.
        stock_name: 종목명 (한글).
        market: 시장 구분 (KOSPI/KOSDAQ).
        current_price: 현재가.
        open_price: 시가.
        high_price: 고가.
        low_price: 저가.
        volume: 거래량.
        change: 전일 대비 변동액.
        change_rate: 전일 대비 변동률.
        updated_at: 마지막 가격 업데이트 시간 (KST).
    """

    stock_code: str = Field(..., pattern=r"^\d{6}$", description="6자리 종목코드")
    stock_name: str = Field(..., min_length=1, max_length=50, description="종목명")
    market: MarketType = Field(..., description="시장 구분 (KOSPI/KOSDAQ)")
    current_price: Decimal = Field(..., gt=0, description="현재가")
    open_price: Optional[Decimal] = Field(None, gt=0, description="시가")
    high_price: Optional[Decimal] = Field(None, description="고가")
    low_price: Optional[Decimal] = Field(None, description="저가")
    volume: int = Field(default=0, ge=0, description="거래량")
    change: Optional[Decimal] = Field(None, description="전일 대비 변동액")
    change_rate: Optional[Decimal] = Field(None, description="전일 대비 변동률")
    updated_at: datetime = Field(default_factory=get_kst_now, description="마지막 업데이트 시간")

    @field_validator("high_price")
    @classmethod
    def validate_high_price(cls, v: Optional[Decimal], info) -> Optional[Decimal]:
        """고가가 시가보다 높은지 검증합니다.

        Args:
            v: 검증할 고가.
            info: 다른 필드 값을 포함하는 검증 정보.

        Returns:
            검증된 고가.

        Raises:
            ValueError: 고가가 시가보다 낮을 경우.
        """
        if v is not None:
            open_price = info.data.get("open_price")
            if open_price and v < open_price:
                raise ValueError("고가는 시가보다 낮을 수 없습니다")
        return v

    @field_validator("low_price")
    @classmethod
    def validate_low_price(cls, v: Optional[Decimal], info) -> Optional[Decimal]:
        """저가가 시가보다 낮은지 검증합니다.

        Args:
            v: 검증할 저가.
            info: 다른 필드 값을 포함하는 검증 정보.

        Returns:
            검증된 저가.

        Raises:
            ValueError: 저가가 시가보다 높을 경우.
        """
        if v is not None:
            open_price = info.data.get("open_price")
            if open_price and v > open_price:
                raise ValueError("저가는 시가보다 높을 수 없습니다")
        return v

    def get_price_change_rate(self) -> Decimal:
        """시가 대비 현재가 등락률을 계산합니다.

        Returns:
            등락률 (0.05 = 5% 상승, -0.03 = 3% 하락).
            시가 정보가 없으면 0을 반환합니다.
        """
        if not self.open_price or self.open_price == 0:
            return Decimal("0")
        return (self.current_price - self.open_price) / self.open_price

    class Config:
        """Pydantic 설정."""

        frozen = False  # 가격 업데이트를 위해 변경 가능
        use_enum_values = True
        json_encoders = {Decimal: str, datetime: lambda v: v.isoformat()}
