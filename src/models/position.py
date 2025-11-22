"""포지션 모델 정의."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, computed_field

from .stock import get_kst_now


class Position(BaseModel):
    """계좌에서 보유 중인 주식 포지션.

    Attributes:
        account_number: 이 포지션을 보유한 계좌번호.
        stock_code: 포지션의 종목코드.
        quantity: 보유 수량.
        average_buy_price: 주당 평균 매수가.
        current_price: 주당 현재 시장가.
        strategy_name: 이 포지션을 생성한 전략명.
        opened_at: 포지션 개설 시간.
        updated_at: 마지막 업데이트 시간.
    """

    account_number: str = Field(..., pattern=r"^\d{8}$", description="계좌번호")
    stock_code: str = Field(..., pattern=r"^\d{6}$", description="종목코드")
    quantity: int = Field(..., gt=0, description="보유 수량")
    average_buy_price: Decimal = Field(..., gt=0, description="평균 매수가")
    current_price: Decimal = Field(..., gt=0, description="현재가")
    strategy_name: Optional[str] = Field(
        None, min_length=1, max_length=100, description="전략명"
    )
    opened_at: datetime = Field(default_factory=get_kst_now, description="포지션 개설 시간")
    updated_at: datetime = Field(default_factory=get_kst_now, description="마지막 업데이트 시간")

    @computed_field
    @property
    def evaluation_amount(self) -> Decimal:
        """현재 평가 금액을 계산합니다.

        Returns:
            현재가 기준 총 포지션 가치.
        """
        return self.current_price * self.quantity

    @computed_field
    @property
    def unrealized_pnl(self) -> Decimal:
        """미실현 손익을 계산합니다.

        Returns:
            미실현 손익 (수익이면 양수, 손실이면 음수).
        """
        return (self.current_price - self.average_buy_price) * self.quantity

    @computed_field
    @property
    def return_rate(self) -> Decimal:
        """수익률을 계산합니다.

        Returns:
            수익률 (0.05 = 5% 수익, -0.03 = 3% 손실).
        """
        return (self.current_price - self.average_buy_price) / self.average_buy_price

    def update_price(self, new_price: Decimal) -> None:
        """현재가와 타임스탬프를 업데이트합니다.

        Args:
            new_price: 새로운 현재가.
        """
        self.current_price = new_price
        self.updated_at = get_kst_now()

    def add_quantity(self, additional_quantity: int, buy_price: Decimal) -> None:
        """포지션 수량을 추가하고 평균 매수가를 재계산합니다.

        Args:
            additional_quantity: 추가할 주식 수량.
            buy_price: 추가 주식의 매수가.
        """
        total_cost = (self.average_buy_price * self.quantity) + (
            buy_price * additional_quantity
        )
        self.quantity += additional_quantity
        self.average_buy_price = total_cost / self.quantity
        self.updated_at = get_kst_now()

    def reduce_quantity(self, reduce_quantity: int) -> None:
        """포지션 수량을 감소시킵니다 (부분 매도).

        Args:
            reduce_quantity: 감소시킬 주식 수량.

        Raises:
            ValueError: 감소 수량이 현재 수량을 초과할 경우.
        """
        if reduce_quantity > self.quantity:
            raise ValueError("감소 수량은 현재 수량을 초과할 수 없습니다")
        self.quantity -= reduce_quantity
        self.updated_at = get_kst_now()

    class Config:
        """Pydantic 설정."""

        frozen = False  # 포지션 업데이트를 위해 변경 가능
        json_encoders = {Decimal: str, datetime: lambda v: v.isoformat()}
