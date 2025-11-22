"""주문 모델 정의."""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from . import OrderStatus, OrderType, PriceType
from .stock import get_kst_now


class Order(BaseModel):
    """주식 매수/매도 주문.

    Attributes:
        order_id: 고유 주문 식별자 (UUID).
        account_number: 주문을 생성한 계좌번호.
        stock_code: 대상 종목코드.
        order_type: 매수 또는 매도.
        price_type: 시장가 또는 지정가.
        quantity: 주문 수량.
        limit_price: 지정가 (LIMIT 주문 시 필수).
        status: 현재 주문 상태.
        filled_quantity: 체결된 수량.
        filled_price: 평균 체결가.
        strategy_name: 이 주문을 생성한 전략명.
        created_at: 주문 생성 시간.
        submitted_at: API 제출 시간.
        filled_at: 주문 체결 완료 시간.
        error_message: 주문 실패 시 오류 메시지.
    """

    order_id: str = Field(
        default_factory=lambda: str(uuid4()), description="고유 주문 ID"
    )
    account_number: str = Field(..., pattern=r"^\d{8}$", description="계좌번호")
    stock_code: str = Field(..., pattern=r"^\d{6}$", description="종목코드")
    order_type: OrderType = Field(..., description="주문 유형 (매수/매도)")
    price_type: PriceType = Field(..., description="가격 유형 (시장가/지정가)")
    quantity: int = Field(..., gt=0, description="주문 수량")
    limit_price: Optional[Decimal] = Field(
        None, gt=0, description="지정가 (LIMIT 주문 시 필수)"
    )
    status: OrderStatus = Field(default=OrderStatus.PENDING, description="주문 상태")
    filled_quantity: int = Field(default=0, ge=0, description="체결된 수량")
    filled_price: Optional[Decimal] = Field(None, gt=0, description="평균 체결가")
    strategy_name: Optional[str] = Field(
        None, min_length=1, max_length=100, description="전략명"
    )
    created_at: datetime = Field(default_factory=get_kst_now, description="주문 생성 시간")
    submitted_at: Optional[datetime] = Field(None, description="API 제출 시간")
    filled_at: Optional[datetime] = Field(None, description="체결 완료 시간")
    error_message: Optional[str] = Field(None, max_length=500, description="오류 메시지")

    @field_validator("limit_price")
    @classmethod
    def validate_limit_price(cls, v: Optional[Decimal], info) -> Optional[Decimal]:
        """LIMIT 주문의 경우 limit_price가 제공되었는지 검증합니다.

        Args:
            v: 검증할 지정가.
            info: 다른 필드 값을 포함하는 검증 정보.

        Returns:
            검증된 지정가.

        Raises:
            ValueError: LIMIT 주문에 limit_price가 없을 경우.
        """
        price_type = info.data.get("price_type")
        if price_type == PriceType.LIMIT and v is None:
            raise ValueError("LIMIT 주문은 limit_price를 반드시 지정해야 합니다")
        return v

    @field_validator("filled_quantity")
    @classmethod
    def validate_filled_quantity(cls, v: int, info) -> int:
        """체결 수량이 주문 수량을 초과하지 않는지 검증합니다.

        Args:
            v: 검증할 체결 수량.
            info: 다른 필드 값을 포함하는 검증 정보.

        Returns:
            검증된 체결 수량.

        Raises:
            ValueError: 체결 수량이 주문 수량을 초과할 경우.
        """
        quantity = info.data.get("quantity")
        if quantity and v > quantity:
            raise ValueError("체결 수량은 주문 수량을 초과할 수 없습니다")
        return v

    def is_fully_filled(self) -> bool:
        """주문이 완전히 체결되었는지 확인합니다.

        Returns:
            체결 수량이 주문 수량과 같으면 True.
        """
        return self.filled_quantity == self.quantity

    def is_terminal_state(self) -> bool:
        """주문이 종료 상태인지 확인합니다 (더 이상 변경 불가).

        Returns:
            상태가 FILLED, CANCELLED, REJECTED, FAILED 중 하나면 True.
        """
        return self.status in {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED,
        }

    def calculate_total_cost(self) -> Decimal:
        """주문의 총 비용/수익을 계산합니다.

        매수 주문: 총 지불 금액.
        매도 주문: 총 수령 금액.

        Returns:
            총 비용 (매수/매도 모두 양수).
            체결되지 않은 경우 0을 반환합니다.
        """
        if not self.filled_price or self.filled_quantity == 0:
            return Decimal("0")
        return self.filled_price * self.filled_quantity

    class Config:
        """Pydantic 설정."""

        frozen = False  # 주문 상태 업데이트를 위해 변경 가능
        use_enum_values = True
        json_encoders = {Decimal: str, datetime: lambda v: v.isoformat()}
