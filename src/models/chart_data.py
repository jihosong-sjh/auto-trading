"""ChartData 모델 정의."""

from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from zoneinfo import ZoneInfo

from . import ChartInterval

KST = ZoneInfo("Asia/Seoul")


class ChartData(BaseModel):
    """차트 데이터 (OHLCV).

    과거 가격 데이터를 저장합니다.

    Attributes:
        stock_code: 종목코드 (6자리).
        interval: 차트 주기 (일봉, 분봉 등).
        timestamp: 데이터 시점 (KST).
        open_price: 시가.
        high_price: 고가.
        low_price: 저가.
        close_price: 종가.
        volume: 거래량.
    """

    stock_code: str = Field(..., pattern=r"^\d{6}$", description="종목코드")
    interval: ChartInterval = Field(..., description="차트 주기")
    timestamp: datetime = Field(..., description="데이터 시점")
    open_price: Decimal = Field(..., gt=0, description="시가")
    high_price: Decimal = Field(..., gt=0, description="고가")
    low_price: Decimal = Field(..., gt=0, description="저가")
    close_price: Decimal = Field(..., gt=0, description="종가")
    volume: int = Field(..., ge=0, description="거래량")

    @field_validator("high_price")
    @classmethod
    def validate_high_price(cls, v: Decimal, info) -> Decimal:
        """고가 유효성 검증.

        Args:
            v: 고가.
            info: 검증 정보.

        Returns:
            검증된 고가.

        Raises:
            ValueError: 고가가 시가, 저가, 종가보다 낮은 경우.
        """
        open_price = info.data.get("open_price")
        low_price = info.data.get("low_price")
        close_price = info.data.get("close_price")

        if open_price and v < open_price:
            raise ValueError("High price must be >= open price")
        if low_price and v < low_price:
            raise ValueError("High price must be >= low price")
        if close_price and v < close_price:
            raise ValueError("High price must be >= close price")

        return v

    @field_validator("low_price")
    @classmethod
    def validate_low_price(cls, v: Decimal, info) -> Decimal:
        """저가 유효성 검증.

        Args:
            v: 저가.
            info: 검증 정보.

        Returns:
            검증된 저가.

        Raises:
            ValueError: 저가가 시가, 고가, 종가보다 높은 경우.
        """
        open_price = info.data.get("open_price")
        high_price = info.data.get("high_price")
        close_price = info.data.get("close_price")

        if open_price and v > open_price:
            raise ValueError("Low price must be <= open price")
        if high_price and v > high_price:
            raise ValueError("Low price must be <= high price")
        if close_price and v > close_price:
            raise ValueError("Low price must be <= close price")

        return v

    class Config:
        """Pydantic 설정."""

        frozen = True
        use_enum_values = True
        json_encoders = {Decimal: str, datetime: lambda v: v.isoformat()}
