"""WebSocket 실시간 데이터 모델 정의.

키움증권 WebSocket API에서 수신하는 실시간 데이터 타입:
- 0B: 주식체결 (TradeData)
- 0D: 주식호가잔량 (OrderBookData)
- 00: 주문체결 알림 (OrderExecutionData)
- 04: 잔고 변동 (BalanceUpdateData)
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

KST = ZoneInfo("Asia/Seoul")


class MarketPhase(str, Enum):
    """장 운영 구분."""

    PRE_MARKET = "1"  # 장전 시간외
    REGULAR = "2"  # 장중
    POST_MARKET = "3"  # 장후 시간외


class OrderStatus(str, Enum):
    """주문 상태 (00 타입)."""

    RECEIVED = "접수"
    EXECUTED = "체결"
    CONFIRMED = "확인"
    CANCELLED = "취소"
    REJECTED = "거부"


class BalanceAction(str, Enum):
    """잔고 변동 구분 (04 타입)."""

    INSERT = "I"  # 삽입 (신규 매수)
    DELETE = "D"  # 삭제 (전량 매도)


class TradeData(BaseModel):
    """주식체결 데이터 (0B 타입).

    실시간 체결 정보를 담습니다.

    Attributes:
        stock_code: 종목코드 (6자리).
        current_price: 현재가 (절대값).
        price_change: 전일대비 변동가.
        change_rate: 등락률 (%).
        volume: 단일 체결량 (양수=매수체결, 음수=매도체결).
        volume_sign: 체결 방향 ('+': 매수, '-': 매도).
        cumulative_volume: 누적거래량.
        cumulative_amount: 누적거래대금 (백만원).
        trade_strength: 체결강도.
        best_ask: 최우선 매도호가.
        best_bid: 최우선 매수호가.
        open_price: 시가.
        high_price: 고가.
        low_price: 저가.
        market_phase: 장 구분.
        timestamp: 체결 시간.
    """

    stock_code: str = Field(..., pattern=r"^\d{6}$", description="종목코드")
    current_price: Decimal = Field(..., description="현재가 (절대값)")
    price_change: Decimal = Field(default=Decimal("0"), description="전일대비")
    change_rate: Decimal = Field(default=Decimal("0"), description="등락률 (%)")
    volume: int = Field(default=0, description="단일 체결량")
    volume_sign: str = Field(default="+", description="체결 방향")
    cumulative_volume: int = Field(default=0, ge=0, description="누적거래량")
    cumulative_amount: Decimal = Field(default=Decimal("0"), description="누적거래대금")
    trade_strength: Decimal = Field(default=Decimal("0"), description="체결강도")
    best_ask: Decimal = Field(default=Decimal("0"), description="최우선 매도호가")
    best_bid: Decimal = Field(default=Decimal("0"), description="최우선 매수호가")
    open_price: Decimal = Field(default=Decimal("0"), description="시가")
    high_price: Decimal = Field(default=Decimal("0"), description="고가")
    low_price: Decimal = Field(default=Decimal("0"), description="저가")
    market_phase: str = Field(default="2", description="장 구분")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(KST), description="체결 시간"
    )

    def is_buy_trade(self) -> bool:
        """매수 체결 여부."""
        return self.volume_sign == "+"

    class Config:
        """Pydantic 설정."""

        frozen = False
        json_encoders = {Decimal: str, datetime: lambda v: v.isoformat()}


class OrderBookData(BaseModel):
    """주식호가잔량 데이터 (0D 타입).

    10단계 호가 정보를 담습니다.

    Attributes:
        stock_code: 종목코드.
        ask_prices: 매도호가 (1~10단계).
        ask_quantities: 매도호가 수량 (1~10단계).
        bid_prices: 매수호가 (1~10단계).
        bid_quantities: 매수호가 수량 (1~10단계).
        total_ask_quantity: 총 매도 잔량.
        total_bid_quantity: 총 매수 잔량.
        expected_price: 예상체결가.
        expected_volume: 예상체결수량.
        timestamp: 호가 시간.
    """

    stock_code: str = Field(..., pattern=r"^\d{6}$", description="종목코드")
    ask_prices: List[Decimal] = Field(
        default_factory=list, max_length=10, description="매도호가 (1~10단계)"
    )
    ask_quantities: List[int] = Field(
        default_factory=list, max_length=10, description="매도호가 수량"
    )
    bid_prices: List[Decimal] = Field(
        default_factory=list, max_length=10, description="매수호가 (1~10단계)"
    )
    bid_quantities: List[int] = Field(
        default_factory=list, max_length=10, description="매수호가 수량"
    )
    total_ask_quantity: int = Field(default=0, ge=0, description="총 매도 잔량")
    total_bid_quantity: int = Field(default=0, ge=0, description="총 매수 잔량")
    expected_price: Decimal = Field(default=Decimal("0"), description="예상체결가")
    expected_volume: int = Field(default=0, ge=0, description="예상체결수량")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(KST), description="호가 시간"
    )

    def get_imbalance_ratio(self) -> Decimal:
        """호가 불균형 비율 계산.

        Returns:
            (총매수잔량 - 총매도잔량) / (총매수잔량 + 총매도잔량)
        """
        total = self.total_bid_quantity + self.total_ask_quantity
        if total == 0:
            return Decimal("0")
        imbalance = self.total_bid_quantity - self.total_ask_quantity
        return Decimal(str(imbalance)) / Decimal(str(total))

    class Config:
        """Pydantic 설정."""

        frozen = False
        json_encoders = {Decimal: str, datetime: lambda v: v.isoformat()}


class OrderExecutionData(BaseModel):
    """주문체결 알림 데이터 (00 타입).

    내 계좌의 주문 접수/체결/정정/취소 알림입니다.
    종목코드 등록 없이 토큰 기반으로 자동 수신됩니다.

    Attributes:
        account_number: 계좌번호.
        order_id: 주문번호.
        original_order_id: 원주문번호 (정정/취소 시).
        stock_code: 종목코드.
        stock_name: 종목명.
        order_status: 주문상태 (접수/체결/확인/취소/거부).
        order_type: 주문구분 (매수/매도/정정/취소).
        trade_type: 매매구분 (보통/시장가 등).
        side: 매도수구분 (1: 매도, 2: 매수).
        quantity: 주문수량.
        price: 주문가격.
        unfilled_quantity: 미체결수량.
        filled_amount: 체결누계금액.
        filled_price: 체결가.
        filled_quantity: 체결량.
        unit_filled_price: 단위체결가.
        unit_filled_quantity: 단위체결량.
        reject_reason: 거부사유.
        current_price: 현재가.
        timestamp: 주문/체결시간.
    """

    account_number: str = Field(..., description="계좌번호")
    order_id: str = Field(..., description="주문번호")
    original_order_id: Optional[str] = Field(None, description="원주문번호")
    stock_code: str = Field(..., description="종목코드")
    stock_name: str = Field(default="", description="종목명")
    order_status: str = Field(..., description="주문상태")
    order_type: str = Field(default="", description="주문구분")
    trade_type: str = Field(default="", description="매매구분")
    side: str = Field(default="", description="매도수구분 (1:매도, 2:매수)")
    quantity: int = Field(default=0, ge=0, description="주문수량")
    price: Decimal = Field(default=Decimal("0"), description="주문가격")
    unfilled_quantity: int = Field(default=0, ge=0, description="미체결수량")
    filled_amount: Decimal = Field(default=Decimal("0"), description="체결누계금액")
    filled_price: Decimal = Field(default=Decimal("0"), description="체결가")
    filled_quantity: int = Field(default=0, ge=0, description="체결량")
    unit_filled_price: Decimal = Field(default=Decimal("0"), description="단위체결가")
    unit_filled_quantity: int = Field(default=0, ge=0, description="단위체결량")
    reject_reason: str = Field(default="", description="거부사유")
    current_price: Decimal = Field(default=Decimal("0"), description="현재가")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(KST), description="주문/체결시간"
    )

    def is_filled(self) -> bool:
        """체결 완료 여부."""
        return self.order_status == OrderStatus.EXECUTED.value

    def is_rejected(self) -> bool:
        """거부 여부."""
        return self.order_status == OrderStatus.REJECTED.value

    def is_buy_order(self) -> bool:
        """매수 주문 여부."""
        return self.side == "2"

    class Config:
        """Pydantic 설정."""

        frozen = False
        json_encoders = {Decimal: str, datetime: lambda v: v.isoformat()}


class BalanceUpdateData(BaseModel):
    """잔고 변동 데이터 (04 타입).

    계좌의 잔고 변동 알림입니다.
    종목코드 등록 없이 토큰 기반으로 자동 수신됩니다.

    Attributes:
        account_number: 계좌번호.
        stock_code: 종목코드.
        stock_name: 종목명.
        action: 삽입/삭제 구분 (I: 신규, D: 삭제).
        side: 매도수구분.
        holding_quantity: 보유수량.
        average_price: 매입단가.
        total_purchase_amount: 총매입가.
        orderable_quantity: 주문가능수량.
        current_price: 현재가.
        best_ask: 최우선 매도호가.
        best_bid: 최우선 매수호가.
        realized_pnl: 당일실현손익.
        realized_pnl_rate: 당일실현손익률.
        timestamp: 체결시간.
    """

    account_number: str = Field(..., description="계좌번호")
    stock_code: str = Field(..., description="종목코드")
    stock_name: str = Field(default="", description="종목명")
    action: str = Field(default="I", description="삽입/삭제 구분")
    side: str = Field(default="", description="매도수구분")
    holding_quantity: int = Field(default=0, ge=0, description="보유수량")
    average_price: Decimal = Field(default=Decimal("0"), description="매입단가")
    total_purchase_amount: Decimal = Field(default=Decimal("0"), description="총매입가")
    orderable_quantity: int = Field(default=0, ge=0, description="주문가능수량")
    current_price: Decimal = Field(default=Decimal("0"), description="현재가")
    best_ask: Decimal = Field(default=Decimal("0"), description="최우선 매도호가")
    best_bid: Decimal = Field(default=Decimal("0"), description="최우선 매수호가")
    realized_pnl: Decimal = Field(default=Decimal("0"), description="당일실현손익")
    realized_pnl_rate: Decimal = Field(default=Decimal("0"), description="당일실현손익률")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(KST), description="체결시간"
    )

    def is_new_position(self) -> bool:
        """신규 포지션 여부."""
        return self.action == BalanceAction.INSERT.value

    def is_position_closed(self) -> bool:
        """포지션 종료 여부."""
        return self.action == BalanceAction.DELETE.value

    class Config:
        """Pydantic 설정."""

        frozen = False
        json_encoders = {Decimal: str, datetime: lambda v: v.isoformat()}
