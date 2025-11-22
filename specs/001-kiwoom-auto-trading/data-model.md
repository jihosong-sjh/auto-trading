# 데이터 모델 명세 (Data Model Specification)

**Feature Branch**: `001-kiwoom-auto-trading`
**Created**: 2025-11-22
**Status**: Draft
**Related**: [spec.md](./spec.md) | [research.md](./research.md) | [plan.md](./plan.md)

## 목차 (Table of Contents)

1. [개요](#개요)
2. [아키텍처 원칙](#아키텍처-원칙)
3. [Enum 정의](#enum-정의)
4. [핵심 엔티티](#핵심-엔티티)
5. [엔티티 관계도](#엔티티-관계도)
6. [저장소 구현 전략](#저장소-구현-전략)
7. [유효성 검증 및 비즈니스 로직](#유효성-검증-및-비즈니스-로직)

---

## 개요

본 문서는 키움증권 REST API 기반 자동매매 시스템의 모든 핵심 엔티티와 데이터 모델을 정의한다. 각 엔티티는 Pydantic 모델을 사용하여 타입 안전성과 런타임 검증을 보장하며, Constitution 원칙에 따라 금융 데이터의 정확성과 안정성을 최우선으로 한다.

### 설계 목표

- **타입 안전성**: 모든 필드에 타입 힌트 적용 및 Pydantic 검증
- **금융 데이터 정확성**: Decimal 타입 사용으로 부동소수점 오차 방지
- **시간대 명확성**: KST 타임존 명시적 처리
- **확장성**: 새로운 전략 및 기능 추가 용이
- **추적성**: 모든 주문 및 거래 내역 완전한 감사 추적

---

## 아키텍처 원칙

### 1. Pydantic 기반 모델링

모든 엔티티는 `pydantic.BaseModel`을 상속하여 정의한다.

```python
from pydantic import BaseModel, Field, field_validator
from decimal import Decimal
from datetime import datetime
from typing import Optional

class ExampleModel(BaseModel):
    """Example model demonstrating Pydantic patterns.

    Attributes:
        field_name: Description of the field.
    """
    field_name: str = Field(..., description="Field description")

    class Config:
        """Pydantic configuration."""
        frozen = True  # Immutable for thread safety
        use_enum_values = True
        json_encoders = {
            Decimal: str,
            datetime: lambda v: v.isoformat()
        }
```

### 2. 금융 데이터 타입 규칙

| 데이터 타입 | Python 타입 | 예시 | 비고 |
|------------|------------|------|------|
| 가격 (Price) | `Decimal` | `Decimal("50000.00")` | 부동소수점 오차 방지 |
| 수량 (Quantity) | `int` | `100` | 주식은 정수 단위 |
| 비율 (Rate) | `Decimal` | `Decimal("0.03")` | 3% = 0.03 |
| 금액 (Amount) | `Decimal` | `Decimal("5000000.00")` | 가격 × 수량 |
| 시간 (Timestamp) | `datetime` | `datetime.now(tz=KST)` | 타임존 명시 필수 |
| 코드 (Code) | `str` | `"005930"` | 6자리 문자열 |

### 3. 타임존 처리

```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# KST timezone (Korea Standard Time)
KST = ZoneInfo("Asia/Seoul")

def get_kst_now() -> datetime:
    """Get current KST time with timezone awareness.

    Returns:
        Current datetime in KST timezone.
    """
    return datetime.now(tz=KST)
```

### 4. Google Style Docstring

모든 클래스와 메서드는 Google Style Docstring을 사용한다.

```python
def calculate_profit_loss(
    quantity: int,
    buy_price: Decimal,
    sell_price: Decimal
) -> Decimal:
    """Calculate realized profit/loss for a trade.

    Args:
        quantity: Number of shares traded.
        buy_price: Average purchase price per share.
        sell_price: Selling price per share.

    Returns:
        Realized profit/loss amount (positive for profit, negative for loss).

    Example:
        >>> calculate_profit_loss(100, Decimal("50000"), Decimal("55000"))
        Decimal('500000.00')
    """
    return (sell_price - buy_price) * quantity
```

---

## Enum 정의

### OrderType (주문 유형)

```python
from enum import Enum

class OrderType(str, Enum):
    """Order type enumeration.

    Attributes:
        BUY: Buy order (매수).
        SELL: Sell order (매도).
    """
    BUY = "BUY"
    SELL = "SELL"
```

**사용 예시**:
```python
order = Order(order_type=OrderType.BUY, ...)
```

---

### OrderStatus (주문 상태)

```python
class OrderStatus(str, Enum):
    """Order status enumeration.

    Attributes:
        PENDING: Order created but not yet sent to API.
        SUBMITTED: Order submitted to broker API.
        PARTIALLY_FILLED: Order partially executed.
        FILLED: Order fully executed.
        CANCELLED: Order cancelled by user or system.
        REJECTED: Order rejected by broker.
        FAILED: Order failed due to system error.
    """
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
```

**상태 전이 규칙**:
```
PENDING → SUBMITTED → PARTIALLY_FILLED → FILLED
                   ↘ CANCELLED
                   ↘ REJECTED
                   ↘ FAILED
```

---

### PriceType (가격 유형)

```python
class PriceType(str, Enum):
    """Price type for orders.

    Attributes:
        MARKET: Market order (시장가 주문).
        LIMIT: Limit order (지정가 주문).
    """
    MARKET = "MARKET"
    LIMIT = "LIMIT"
```

**사용 예시**:
```python
# 시장가 매수
order = Order(price_type=PriceType.MARKET, ...)

# 지정가 매도 (특정 가격 이상에서만 매도)
order = Order(price_type=PriceType.LIMIT, limit_price=Decimal("55000"), ...)
```

---

### ChartInterval (차트 주기)

```python
class ChartInterval(str, Enum):
    """Chart data interval.

    Attributes:
        TICK: Tick data (체결 데이터).
        MIN_1: 1-minute candle (1분봉).
        MIN_5: 5-minute candle (5분봉).
        MIN_30: 30-minute candle (30분봉).
        HOUR_1: 1-hour candle (1시간봉).
        DAY: Daily candle (일봉).
        WEEK: Weekly candle (주봉).
        MONTH: Monthly candle (월봉).
    """
    TICK = "TICK"
    MIN_1 = "MIN_1"
    MIN_5 = "MIN_5"
    MIN_30 = "MIN_30"
    HOUR_1 = "HOUR_1"
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
```

---

### SystemMode (시스템 운영 모드)

```python
class SystemMode(str, Enum):
    """System operation mode.

    Attributes:
        STARTING: System is starting up.
        RUNNING: System is running normally.
        PAUSED: System is paused by user.
        ERROR: System encountered an error.
        SHUTDOWN: System is shutting down.
        BACKTEST: System is running in backtest mode.
    """
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    SHUTDOWN = "SHUTDOWN"
    BACKTEST = "BACKTEST"
```

---

### NotificationType (알림 유형)

```python
class NotificationType(str, Enum):
    """Notification type enumeration.

    Attributes:
        ORDER_FILLED: Order execution notification.
        ERROR: Error alert.
        DAILY_REPORT: Daily trading summary.
        SYSTEM_STATUS: System status change.
        RISK_ALERT: Risk management alert (e.g., daily loss limit).
    """
    ORDER_FILLED = "ORDER_FILLED"
    ERROR = "ERROR"
    DAILY_REPORT = "DAILY_REPORT"
    SYSTEM_STATUS = "SYSTEM_STATUS"
    RISK_ALERT = "RISK_ALERT"
```

---

### MarketPhase (장 운영 시간대)

```python
class MarketPhase(str, Enum):
    """Market trading phase.

    Attributes:
        PRE_MARKET: Before market open (09:00 이전).
        OPENING: Market opening (09:00-09:05).
        REGULAR: Regular trading hours (09:05-15:20).
        CLOSING_SOON: Near market close (15:20-15:30).
        CLOSED: Market closed (15:30 이후).
        AFTER_HOURS: After-hours trading (시간외 거래).
    """
    PRE_MARKET = "PRE_MARKET"
    OPENING = "OPENING"
    REGULAR = "REGULAR"
    CLOSING_SOON = "CLOSING_SOON"
    CLOSED = "CLOSED"
    AFTER_HOURS = "AFTER_HOURS"
```

---

## 핵심 엔티티

### 1. Account (계좌)

#### 목적

사용자의 증권 계좌 정보 및 예수금 관리.

#### 필드 정의

| 필드명 | 타입 | 필수 | 설명 | 유효성 규칙 |
|-------|------|-----|------|-----------|
| `account_number` | `str` | Yes | 계좌번호 (8자리) | 정규식: `^\d{8}$` |
| `name` | `str` | Yes | 계좌명 | 길이: 1-50자 |
| `cash_balance` | `Decimal` | Yes | 예수금 (현금 잔고) | >= 0 |
| `total_asset_value` | `Decimal` | Yes | 총 평가 금액 (현금 + 주식 평가액) | >= cash_balance |
| `total_pnl` | `Decimal` | Yes | 총 손익 (실현 + 미실현) | 제한 없음 |
| `daily_pnl` | `Decimal` | Yes | 당일 손익 | 제한 없음 |
| `daily_loss_limit` | `Decimal` | Yes | 일일 손실 한도 (예: 계좌의 5%) | > 0 |
| `updated_at` | `datetime` | Yes | 마지막 업데이트 시간 (KST) | 타임존 명시 |

#### 관계

- **1:N with Position**: 한 계좌는 여러 포지션을 보유할 수 있다.
- **1:N with Order**: 한 계좌에서 여러 주문이 발생한다.

#### 구현 예시

```python
from pydantic import BaseModel, Field, field_validator
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo
import re

KST = ZoneInfo("Asia/Seoul")

class Account(BaseModel):
    """User's trading account information.

    Attributes:
        account_number: 8-digit account number.
        name: Account display name.
        cash_balance: Available cash balance.
        total_asset_value: Total asset value (cash + stock positions).
        total_pnl: Total profit/loss (realized + unrealized).
        daily_pnl: Today's profit/loss.
        daily_loss_limit: Maximum allowed daily loss.
        updated_at: Last update timestamp in KST.
    """
    account_number: str = Field(..., pattern=r"^\d{8}$", description="8-digit account number")
    name: str = Field(..., min_length=1, max_length=50, description="Account name")
    cash_balance: Decimal = Field(..., ge=0, description="Cash balance in KRW")
    total_asset_value: Decimal = Field(..., description="Total asset value")
    total_pnl: Decimal = Field(default=Decimal("0"), description="Total P&L")
    daily_pnl: Decimal = Field(default=Decimal("0"), description="Daily P&L")
    daily_loss_limit: Decimal = Field(..., gt=0, description="Daily loss limit")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=KST))

    @field_validator("total_asset_value")
    @classmethod
    def validate_total_asset_value(cls, v: Decimal, info) -> Decimal:
        """Validate total asset value is at least cash balance.

        Args:
            v: Total asset value to validate.
            info: Validation info containing other field values.

        Returns:
            Validated total asset value.

        Raises:
            ValueError: If total asset value < cash balance.
        """
        cash_balance = info.data.get("cash_balance")
        if cash_balance and v < cash_balance:
            raise ValueError("Total asset value cannot be less than cash balance")
        return v

    def is_daily_loss_limit_exceeded(self) -> bool:
        """Check if daily loss limit has been exceeded.

        Returns:
            True if daily P&L exceeds loss limit (negative direction).
        """
        return self.daily_pnl < -self.daily_loss_limit

    class Config:
        """Pydantic configuration."""
        frozen = False  # Mutable for balance updates
        json_encoders = {
            Decimal: str,
            datetime: lambda v: v.isoformat()
        }
```

#### 실제 데이터 예시

```python
account = Account(
    account_number="12345678",
    name="김철수 위탁계좌",
    cash_balance=Decimal("10000000.00"),  # 1천만원
    total_asset_value=Decimal("15000000.00"),  # 1천5백만원 (현금 1천만 + 주식 5백만)
    total_pnl=Decimal("500000.00"),  # 총 50만원 수익
    daily_pnl=Decimal("-120000.00"),  # 당일 12만원 손실
    daily_loss_limit=Decimal("750000.00"),  # 일일 손실 한도 75만원 (계좌의 5%)
    updated_at=datetime(2025, 11, 22, 15, 30, 0, tzinfo=KST)
)

# 일일 손실 한도 확인
if account.is_daily_loss_limit_exceeded():
    print("일일 손실 한도 초과! 자동 매매 중단")
```

---

### 2. Stock (종목)

#### 목적

거래 대상 주식의 기본 정보 및 현재 시세 관리.

#### 필드 정의

| 필드명 | 타입 | 필수 | 설명 | 유효성 규칙 |
|-------|------|-----|------|-----------|
| `stock_code` | `str` | Yes | 종목코드 (6자리) | 정규식: `^\d{6}$` |
| `stock_name` | `str` | Yes | 종목명 | 길이: 1-50자 |
| `market` | `str` | Yes | 시장 구분 (KOSPI/KOSDAQ) | Enum: KOSPI, KOSDAQ |
| `current_price` | `Decimal` | Yes | 현재가 | > 0 |
| `open_price` | `Decimal` | No | 시가 | > 0 |
| `high_price` | `Decimal` | No | 고가 | >= open_price |
| `low_price` | `Decimal` | No | 저가 | <= open_price |
| `volume` | `int` | Yes | 거래량 | >= 0 |
| `updated_at` | `datetime` | Yes | 마지막 업데이트 시간 (KST) | 타임존 명시 |

#### 관계

- **1:N with Order**: 한 종목에 대해 여러 주문이 발생할 수 있다.
- **1:1 with Position**: 보유 중인 종목은 Position으로 관리된다.
- **1:N with ChartData**: 한 종목은 여러 차트 데이터를 가진다.

#### 구현 예시

```python
class MarketType(str, Enum):
    """Stock market type."""
    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"

class Stock(BaseModel):
    """Stock information and current market data.

    Attributes:
        stock_code: 6-digit stock code.
        stock_name: Stock name (Korean).
        market: Market type (KOSPI/KOSDAQ).
        current_price: Current trading price.
        open_price: Opening price of the day.
        high_price: Highest price of the day.
        low_price: Lowest price of the day.
        volume: Trading volume.
        updated_at: Last price update timestamp in KST.
    """
    stock_code: str = Field(..., pattern=r"^\d{6}$", description="6-digit stock code")
    stock_name: str = Field(..., min_length=1, max_length=50, description="Stock name")
    market: MarketType = Field(..., description="Market type")
    current_price: Decimal = Field(..., gt=0, description="Current price")
    open_price: Optional[Decimal] = Field(None, gt=0, description="Opening price")
    high_price: Optional[Decimal] = Field(None, description="Highest price")
    low_price: Optional[Decimal] = Field(None, description="Lowest price")
    volume: int = Field(default=0, ge=0, description="Trading volume")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=KST))

    @field_validator("high_price")
    @classmethod
    def validate_high_price(cls, v: Optional[Decimal], info) -> Optional[Decimal]:
        """Validate high price is at least open price.

        Args:
            v: High price to validate.
            info: Validation info containing other field values.

        Returns:
            Validated high price.

        Raises:
            ValueError: If high price < open price.
        """
        if v is not None:
            open_price = info.data.get("open_price")
            if open_price and v < open_price:
                raise ValueError("High price cannot be less than open price")
        return v

    @field_validator("low_price")
    @classmethod
    def validate_low_price(cls, v: Optional[Decimal], info) -> Optional[Decimal]:
        """Validate low price is at most open price.

        Args:
            v: Low price to validate.
            info: Validation info containing other field values.

        Returns:
            Validated low price.

        Raises:
            ValueError: If low price > open price.
        """
        if v is not None:
            open_price = info.data.get("open_price")
            if open_price and v > open_price:
                raise ValueError("Low price cannot be greater than open price")
        return v

    def get_price_change_rate(self) -> Decimal:
        """Calculate price change rate from open to current.

        Returns:
            Price change rate (0.05 = 5% increase, -0.03 = 3% decrease).
            Returns 0 if open_price is not available.
        """
        if not self.open_price or self.open_price == 0:
            return Decimal("0")
        return (self.current_price - self.open_price) / self.open_price

    class Config:
        """Pydantic configuration."""
        frozen = False
        use_enum_values = True
        json_encoders = {
            Decimal: str,
            datetime: lambda v: v.isoformat()
        }
```

#### 실제 데이터 예시

```python
samsung = Stock(
    stock_code="005930",
    stock_name="삼성전자",
    market=MarketType.KOSPI,
    current_price=Decimal("72000.00"),
    open_price=Decimal("71500.00"),
    high_price=Decimal("72500.00"),
    low_price=Decimal("71000.00"),
    volume=15234567,
    updated_at=datetime(2025, 11, 22, 14, 30, 15, tzinfo=KST)
)

# 등락률 계산
change_rate = samsung.get_price_change_rate()
print(f"등락률: {change_rate * 100:.2f}%")  # 등락률: 0.70%
```

---

### 3. Order (주문)

#### 목적

매수/매도 주문의 생성, 실행, 체결 상태를 추적한다.

#### 필드 정의

| 필드명 | 타입 | 필수 | 설명 | 유효성 규칙 |
|-------|------|-----|------|-----------|
| `order_id` | `str` | Yes | 주문 고유 ID (UUID) | UUID 형식 |
| `account_number` | `str` | Yes | 계좌번호 | 정규식: `^\d{8}$` |
| `stock_code` | `str` | Yes | 종목코드 | 정규식: `^\d{6}$` |
| `order_type` | `OrderType` | Yes | 주문 유형 (BUY/SELL) | Enum |
| `price_type` | `PriceType` | Yes | 가격 유형 (MARKET/LIMIT) | Enum |
| `quantity` | `int` | Yes | 주문 수량 | > 0 |
| `limit_price` | `Decimal` | No | 지정가 (LIMIT 주문 시 필수) | > 0 |
| `status` | `OrderStatus` | Yes | 주문 상태 | Enum |
| `filled_quantity` | `int` | Yes | 체결 수량 | 0 <= filled_quantity <= quantity |
| `filled_price` | `Decimal` | No | 평균 체결가 | > 0 (체결 시) |
| `strategy_name` | `str` | No | 생성한 전략명 | 길이: 1-100자 |
| `created_at` | `datetime` | Yes | 주문 생성 시간 (KST) | 타임존 명시 |
| `submitted_at` | `datetime` | No | API 제출 시간 (KST) | >= created_at |
| `filled_at` | `datetime` | No | 체결 완료 시간 (KST) | >= submitted_at |
| `error_message` | `str` | No | 오류 메시지 (실패 시) | 길이: 0-500자 |

#### 상태 전이 (State Transitions)

```
PENDING (생성)
    ↓ submit_order()
SUBMITTED (제출)
    ↓ partial_fill() / fill()
PARTIALLY_FILLED (부분 체결) → FILLED (완전 체결)
    ↓ cancel() / reject() / fail()
CANCELLED / REJECTED / FAILED (종료 상태)
```

**상태 전이 규칙**:
- `PENDING` → `SUBMITTED`: 주문이 API로 전송됨
- `SUBMITTED` → `PARTIALLY_FILLED`: 일부 수량 체결
- `PARTIALLY_FILLED` → `FILLED`: 전체 수량 체결
- 모든 상태에서 `CANCELLED`, `REJECTED`, `FAILED`로 전이 가능

#### 관계

- **N:1 with Account**: 여러 주문은 하나의 계좌에 속한다.
- **N:1 with Stock**: 여러 주문은 하나의 종목을 대상으로 한다.
- **N:1 with Strategy**: 여러 주문은 하나의 전략에서 생성된다.

#### 구현 예시

```python
from uuid import uuid4, UUID

class Order(BaseModel):
    """Order for buying or selling stocks.

    Attributes:
        order_id: Unique order identifier (UUID).
        account_number: Account number placing the order.
        stock_code: Target stock code.
        order_type: Buy or sell.
        price_type: Market or limit order.
        quantity: Number of shares to order.
        limit_price: Limit price (required for LIMIT orders).
        status: Current order status.
        filled_quantity: Number of shares filled.
        filled_price: Average filled price.
        strategy_name: Name of strategy that created this order.
        created_at: Order creation timestamp.
        submitted_at: API submission timestamp.
        filled_at: Order filled timestamp.
        error_message: Error message if order failed.
    """
    order_id: str = Field(default_factory=lambda: str(uuid4()), description="Unique order ID")
    account_number: str = Field(..., pattern=r"^\d{8}$")
    stock_code: str = Field(..., pattern=r"^\d{6}$")
    order_type: OrderType
    price_type: PriceType
    quantity: int = Field(..., gt=0, description="Order quantity")
    limit_price: Optional[Decimal] = Field(None, gt=0, description="Limit price for LIMIT orders")
    status: OrderStatus = Field(default=OrderStatus.PENDING)
    filled_quantity: int = Field(default=0, ge=0, description="Filled quantity")
    filled_price: Optional[Decimal] = Field(None, gt=0, description="Average filled price")
    strategy_name: Optional[str] = Field(None, min_length=1, max_length=100)
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=KST))
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    error_message: Optional[str] = Field(None, max_length=500)

    @field_validator("limit_price")
    @classmethod
    def validate_limit_price(cls, v: Optional[Decimal], info) -> Optional[Decimal]:
        """Validate limit price is provided for LIMIT orders.

        Args:
            v: Limit price to validate.
            info: Validation info containing other field values.

        Returns:
            Validated limit price.

        Raises:
            ValueError: If LIMIT order has no limit_price.
        """
        price_type = info.data.get("price_type")
        if price_type == PriceType.LIMIT and v is None:
            raise ValueError("LIMIT orders must have a limit_price")
        return v

    @field_validator("filled_quantity")
    @classmethod
    def validate_filled_quantity(cls, v: int, info) -> int:
        """Validate filled quantity does not exceed order quantity.

        Args:
            v: Filled quantity to validate.
            info: Validation info containing other field values.

        Returns:
            Validated filled quantity.

        Raises:
            ValueError: If filled_quantity > quantity.
        """
        quantity = info.data.get("quantity")
        if quantity and v > quantity:
            raise ValueError("Filled quantity cannot exceed order quantity")
        return v

    def is_fully_filled(self) -> bool:
        """Check if order is fully filled.

        Returns:
            True if filled_quantity equals order quantity.
        """
        return self.filled_quantity == self.quantity

    def is_terminal_state(self) -> bool:
        """Check if order is in a terminal state (no further changes).

        Returns:
            True if status is FILLED, CANCELLED, REJECTED, or FAILED.
        """
        return self.status in {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED
        }

    def calculate_total_cost(self) -> Decimal:
        """Calculate total cost/proceeds of the order.

        For BUY orders: total amount to pay.
        For SELL orders: total amount to receive.

        Returns:
            Total cost (positive for BUY, positive for SELL).
            Returns 0 if not filled.
        """
        if not self.filled_price or self.filled_quantity == 0:
            return Decimal("0")
        return self.filled_price * self.filled_quantity

    class Config:
        """Pydantic configuration."""
        frozen = False
        use_enum_values = True
        json_encoders = {
            Decimal: str,
            datetime: lambda v: v.isoformat()
        }
```

#### 실제 데이터 예시

```python
# 지정가 매수 주문
buy_order = Order(
    account_number="12345678",
    stock_code="005930",
    order_type=OrderType.BUY,
    price_type=PriceType.LIMIT,
    quantity=100,
    limit_price=Decimal("71500.00"),
    strategy_name="Golden Cross Strategy",
    created_at=datetime(2025, 11, 22, 10, 15, 30, tzinfo=KST)
)

# 주문 제출
buy_order.status = OrderStatus.SUBMITTED
buy_order.submitted_at = datetime.now(tz=KST)

# 부분 체결
buy_order.status = OrderStatus.PARTIALLY_FILLED
buy_order.filled_quantity = 50
buy_order.filled_price = Decimal("71500.00")

# 완전 체결
buy_order.status = OrderStatus.FILLED
buy_order.filled_quantity = 100
buy_order.filled_at = datetime.now(tz=KST)

print(f"총 매수 금액: {buy_order.calculate_total_cost():,}원")  # 총 매수 금액: 7,150,000원
```

---

### 4. Position (포지션)

#### 목적

현재 보유 중인 종목의 수량, 평균 매수가, 평가 손익을 관리한다.

#### 필드 정의

| 필드명 | 타입 | 필수 | 설명 | 유효성 규칙 |
|-------|------|-----|------|-----------|
| `account_number` | `str` | Yes | 계좌번호 | 정규식: `^\d{8}$` |
| `stock_code` | `str` | Yes | 종목코드 | 정규식: `^\d{6}$` |
| `quantity` | `int` | Yes | 보유 수량 | > 0 |
| `average_buy_price` | `Decimal` | Yes | 평균 매수가 | > 0 |
| `current_price` | `Decimal` | Yes | 현재가 | > 0 |
| `strategy_name` | `str` | No | 포지션을 생성한 전략명 | 길이: 1-100자 |
| `opened_at` | `datetime` | Yes | 포지션 최초 생성 시간 (KST) | 타임존 명시 |
| `updated_at` | `datetime` | Yes | 마지막 업데이트 시간 (KST) | >= opened_at |

#### 계산 필드 (Computed Fields)

이 필드들은 저장되지 않고 런타임에 계산된다.

| 필드명 | 계산 식 | 설명 |
|-------|--------|------|
| `evaluation_amount` | `quantity * current_price` | 평가 금액 |
| `unrealized_pnl` | `(current_price - average_buy_price) * quantity` | 미실현 손익 |
| `return_rate` | `(current_price - average_buy_price) / average_buy_price` | 수익률 |

#### 관계

- **N:1 with Account**: 여러 포지션은 하나의 계좌에 속한다.
- **N:1 with Stock**: 각 포지션은 하나의 종목을 보유한다.
- **N:1 with Strategy**: 각 포지션은 하나의 전략에 의해 생성된다.

#### 구현 예시

```python
from pydantic import computed_field

class Position(BaseModel):
    """Current stock position held in the account.

    Attributes:
        account_number: Account number holding this position.
        stock_code: Stock code of the position.
        quantity: Number of shares held.
        average_buy_price: Average purchase price per share.
        current_price: Current market price per share.
        strategy_name: Name of strategy that opened this position.
        opened_at: Position opening timestamp.
        updated_at: Last update timestamp.
    """
    account_number: str = Field(..., pattern=r"^\d{8}$")
    stock_code: str = Field(..., pattern=r"^\d{6}$")
    quantity: int = Field(..., gt=0, description="Position quantity")
    average_buy_price: Decimal = Field(..., gt=0, description="Average buy price")
    current_price: Decimal = Field(..., gt=0, description="Current price")
    strategy_name: Optional[str] = Field(None, min_length=1, max_length=100)
    opened_at: datetime = Field(default_factory=lambda: datetime.now(tz=KST))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=KST))

    @computed_field
    @property
    def evaluation_amount(self) -> Decimal:
        """Calculate current evaluation amount.

        Returns:
            Total position value at current price.
        """
        return self.current_price * self.quantity

    @computed_field
    @property
    def unrealized_pnl(self) -> Decimal:
        """Calculate unrealized profit/loss.

        Returns:
            Unrealized P&L (positive for profit, negative for loss).
        """
        return (self.current_price - self.average_buy_price) * self.quantity

    @computed_field
    @property
    def return_rate(self) -> Decimal:
        """Calculate return rate.

        Returns:
            Return rate (0.05 = 5% profit, -0.03 = 3% loss).
        """
        return (self.current_price - self.average_buy_price) / self.average_buy_price

    def update_price(self, new_price: Decimal) -> None:
        """Update current price and timestamp.

        Args:
            new_price: New current price.
        """
        self.current_price = new_price
        self.updated_at = datetime.now(tz=KST)

    def add_quantity(self, additional_quantity: int, buy_price: Decimal) -> None:
        """Add quantity to position and recalculate average buy price.

        Args:
            additional_quantity: Number of shares to add.
            buy_price: Purchase price of additional shares.
        """
        total_cost = (self.average_buy_price * self.quantity) + (buy_price * additional_quantity)
        self.quantity += additional_quantity
        self.average_buy_price = total_cost / self.quantity
        self.updated_at = datetime.now(tz=KST)

    def reduce_quantity(self, reduce_quantity: int) -> None:
        """Reduce position quantity (for partial sell).

        Args:
            reduce_quantity: Number of shares to reduce.

        Raises:
            ValueError: If reduce_quantity exceeds current quantity.
        """
        if reduce_quantity > self.quantity:
            raise ValueError("Cannot reduce more than current quantity")
        self.quantity -= reduce_quantity
        self.updated_at = datetime.now(tz=KST)

    class Config:
        """Pydantic configuration."""
        frozen = False
        json_encoders = {
            Decimal: str,
            datetime: lambda v: v.isoformat()
        }
```

#### 실제 데이터 예시

```python
position = Position(
    account_number="12345678",
    stock_code="005930",
    quantity=150,
    average_buy_price=Decimal("70000.00"),
    current_price=Decimal("72000.00"),
    strategy_name="Golden Cross Strategy",
    opened_at=datetime(2025, 11, 20, 10, 30, 0, tzinfo=KST),
    updated_at=datetime(2025, 11, 22, 14, 30, 0, tzinfo=KST)
)

print(f"평가 금액: {position.evaluation_amount:,}원")  # 평가 금액: 10,800,000원
print(f"미실현 손익: {position.unrealized_pnl:,}원")  # 미실현 손익: 300,000원
print(f"수익률: {position.return_rate * 100:.2f}%")  # 수익률: 2.86%

# 추가 매수 (100주 @ 71,000원)
position.add_quantity(100, Decimal("71000.00"))
print(f"평균 매수가: {position.average_buy_price:,}원")  # 평균 매수가: 70,400원
print(f"보유 수량: {position.quantity}주")  # 보유 수량: 250주
```

---

### 5. Strategy (전략)

#### 목적

매수/매도 조건을 정의하는 논리 단위. 각 전략은 독립적으로 종목을 감시하고 주문을 생성한다.

#### 필드 정의

| 필드명 | 타입 | 필수 | 설명 | 유효성 규칙 |
|-------|------|-----|------|-----------|
| `strategy_name` | `str` | Yes | 전략 고유 이름 | 길이: 1-100자, 중복 불가 |
| `enabled` | `bool` | Yes | 전략 활성화 여부 | True/False |
| `capital_allocation` | `Decimal` | Yes | 할당 자금 | > 0 |
| `max_positions` | `int` | Yes | 최대 동시 보유 종목 수 | > 0 |
| `watched_stocks` | `List[str]` | Yes | 감시 대상 종목 코드 리스트 | 각 코드 정규식: `^\d{6}$` |
| `parameters` | `Dict[str, Any]` | Yes | 전략별 파라미터 (YAML에서 로드) | 비어있을 수 있음 |
| `created_at` | `datetime` | Yes | 전략 생성 시간 (KST) | 타임존 명시 |

#### 추상 메서드 (Abstract Methods)

모든 전략은 다음 메서드를 구현해야 한다:

```python
from abc import ABC, abstractmethod
from typing import Optional

class BaseStrategy(ABC):
    """Abstract base class for all trading strategies.

    All strategies must implement evaluate_buy_signal and evaluate_sell_signal.
    """

    @abstractmethod
    async def evaluate_buy_signal(self, stock: Stock) -> bool:
        """Evaluate if stock meets buy conditions.

        Args:
            stock: Stock to evaluate.

        Returns:
            True if buy signal detected, False otherwise.
        """
        pass

    @abstractmethod
    async def evaluate_sell_signal(self, position: Position, stock: Stock) -> bool:
        """Evaluate if position meets sell conditions.

        Args:
            position: Current position to evaluate.
            stock: Stock market data.

        Returns:
            True if sell signal detected, False otherwise.
        """
        pass
```

#### 관계

- **1:N with Order**: 한 전략은 여러 주문을 생성한다.
- **1:N with Position**: 한 전략은 여러 포지션을 보유한다.

#### 구현 예시

```python
from typing import Dict, List, Any

class StrategyConfig(BaseModel):
    """Strategy configuration model.

    Attributes:
        strategy_name: Unique strategy identifier.
        enabled: Whether strategy is active.
        capital_allocation: Allocated capital for this strategy.
        max_positions: Maximum concurrent positions.
        watched_stocks: List of stock codes to monitor.
        parameters: Strategy-specific parameters.
        created_at: Strategy creation timestamp.
    """
    strategy_name: str = Field(..., min_length=1, max_length=100, description="Strategy name")
    enabled: bool = Field(default=True, description="Strategy enabled status")
    capital_allocation: Decimal = Field(..., gt=0, description="Allocated capital")
    max_positions: int = Field(..., gt=0, description="Max concurrent positions")
    watched_stocks: List[str] = Field(..., description="Stock codes to monitor")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Strategy parameters")
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=KST))

    @field_validator("watched_stocks")
    @classmethod
    def validate_stock_codes(cls, v: List[str]) -> List[str]:
        """Validate all stock codes are 6 digits.

        Args:
            v: List of stock codes to validate.

        Returns:
            Validated stock code list.

        Raises:
            ValueError: If any stock code is invalid.
        """
        stock_code_pattern = re.compile(r"^\d{6}$")
        for code in v:
            if not stock_code_pattern.match(code):
                raise ValueError(f"Invalid stock code: {code}")
        return v

    class Config:
        """Pydantic configuration."""
        frozen = False
        json_encoders = {
            Decimal: str,
            datetime: lambda v: v.isoformat()
        }


# 구체적 전략 구현 예시
class GoldenCrossStrategy(BaseStrategy):
    """Golden Cross strategy implementation.

    Buys when short-period SMA crosses above long-period SMA.
    Sells when stop-loss or take-profit conditions are met.
    """

    def __init__(self, config: StrategyConfig):
        """Initialize golden cross strategy.

        Args:
            config: Strategy configuration.
        """
        self.config = config
        self.short_period = config.parameters.get("short_period", 5)
        self.long_period = config.parameters.get("long_period", 20)
        self.stop_loss_pct = Decimal(str(config.parameters.get("stop_loss_pct", 0.03)))
        self.take_profit_pct = Decimal(str(config.parameters.get("take_profit_pct", 0.05)))

    async def evaluate_buy_signal(self, stock: Stock) -> bool:
        """Evaluate buy signal based on golden cross.

        Args:
            stock: Stock to evaluate.

        Returns:
            True if golden cross detected, False otherwise.
        """
        # 실제 구현에서는 과거 데이터로 SMA 계산
        # 여기서는 간소화된 예시
        # sma_short = calculate_sma(stock, self.short_period)
        # sma_long = calculate_sma(stock, self.long_period)
        # return sma_short > sma_long and prev_sma_short <= prev_sma_long
        return False  # Placeholder

    async def evaluate_sell_signal(self, position: Position, stock: Stock) -> bool:
        """Evaluate sell signal based on stop-loss or take-profit.

        Args:
            position: Current position.
            stock: Stock market data.

        Returns:
            True if sell condition met, False otherwise.
        """
        return_rate = position.return_rate

        # 손절 조건
        if return_rate <= -self.stop_loss_pct:
            return True

        # 익절 조건
        if return_rate >= self.take_profit_pct:
            return True

        return False
```

#### 실제 데이터 예시 (YAML 설정)

```yaml
# config/strategies.yaml
strategies:
  - strategy_name: "Golden Cross Strategy"
    enabled: true
    capital_allocation: 5000000  # 5백만원
    max_positions: 10
    watched_stocks:
      - "005930"  # 삼성전자
      - "000660"  # SK하이닉스
      - "035720"  # 카카오
    parameters:
      short_period: 5
      long_period: 20
      min_volume: 1000000
      stop_loss_pct: 0.03
      take_profit_pct: 0.05
```

```python
# Python에서 로드
import yaml
from pathlib import Path

def load_strategies(config_path: Path) -> List[StrategyConfig]:
    """Load strategies from YAML config file.

    Args:
        config_path: Path to YAML config file.

    Returns:
        List of validated StrategyConfig instances.
    """
    with open(config_path) as f:
        config_data = yaml.safe_load(f)

    strategies = []
    for strategy_dict in config_data["strategies"]:
        strategy = StrategyConfig(**strategy_dict)
        strategies.append(strategy)

    return strategies
```

---

### 6. Notification (알림)

#### 목적

사용자에게 전달되는 메시지 (주문 체결, 오류, 일일 리포트 등).

#### 필드 정의

| 필드명 | 타입 | 필수 | 설명 | 유효성 규칙 |
|-------|------|-----|------|-----------|
| `notification_id` | `str` | Yes | 알림 고유 ID (UUID) | UUID 형식 |
| `notification_type` | `NotificationType` | Yes | 알림 유형 | Enum |
| `title` | `str` | Yes | 알림 제목 | 길이: 1-100자 |
| `message` | `str` | Yes | 알림 내용 | 길이: 1-1000자 |
| `metadata` | `Dict[str, Any]` | No | 추가 메타데이터 (주문 ID, 종목 코드 등) | JSON 직렬화 가능 |
| `sent` | `bool` | Yes | 전송 완료 여부 | True/False |
| `created_at` | `datetime` | Yes | 알림 생성 시간 (KST) | 타임존 명시 |
| `sent_at` | `datetime` | No | 전송 완료 시간 (KST) | >= created_at |

#### 관계

- **독립적**: 알림은 다른 엔티티와 직접적인 관계가 없지만, `metadata`에 연관 정보를 포함한다.

#### 구현 예시

```python
class Notification(BaseModel):
    """Notification message to be sent to user.

    Attributes:
        notification_id: Unique notification identifier.
        notification_type: Type of notification.
        title: Notification title.
        message: Notification content.
        metadata: Additional metadata (order_id, stock_code, etc.).
        sent: Whether notification has been sent.
        created_at: Notification creation timestamp.
        sent_at: Notification sent timestamp.
    """
    notification_id: str = Field(default_factory=lambda: str(uuid4()))
    notification_type: NotificationType
    title: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1, max_length=1000)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    sent: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=KST))
    sent_at: Optional[datetime] = None

    def mark_as_sent(self) -> None:
        """Mark notification as sent and record timestamp."""
        self.sent = True
        self.sent_at = datetime.now(tz=KST)

    class Config:
        """Pydantic configuration."""
        frozen = False
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
```

#### 실제 데이터 예시

```python
# 주문 체결 알림
order_filled_notification = Notification(
    notification_type=NotificationType.ORDER_FILLED,
    title="매수 주문 체결",
    message="삼성전자 100주가 71,500원에 매수 체결되었습니다.",
    metadata={
        "order_id": "123e4567-e89b-12d3-a456-426614174000",
        "stock_code": "005930",
        "stock_name": "삼성전자",
        "order_type": "BUY",
        "quantity": 100,
        "price": "71500.00"
    },
    created_at=datetime(2025, 11, 22, 10, 30, 45, tzinfo=KST)
)

# 리스크 경고 알림
risk_alert_notification = Notification(
    notification_type=NotificationType.RISK_ALERT,
    title="일일 손실 한도 접근 경고",
    message="당일 손실이 한도의 80%에 도달했습니다. 현재 손실: -600,000원 / 한도: -750,000원",
    metadata={
        "current_daily_pnl": "-600000.00",
        "daily_loss_limit": "750000.00",
        "usage_percentage": 0.8
    },
    created_at=datetime.now(tz=KST)
)
```

---

### 7. SystemStatus (시스템 상태)

#### 목적

시스템의 현재 운영 상태 및 헬스 체크 정보 관리.

#### 필드 정의

| 필드명 | 타입 | 필수 | 설명 | 유효성 규칙 |
|-------|------|-----|------|-----------|
| `system_mode` | `SystemMode` | Yes | 시스템 운영 모드 | Enum |
| `market_phase` | `MarketPhase` | Yes | 현재 시장 상태 | Enum |
| `api_connected` | `bool` | Yes | API 연결 상태 | True/False |
| `last_data_received_at` | `datetime` | No | 마지막 데이터 수신 시간 (KST) | 타임존 명시 |
| `active_strategies` | `List[str]` | Yes | 활성 전략 목록 | 전략 이름 리스트 |
| `error_count` | `int` | Yes | 오류 발생 횟수 (누적) | >= 0 |
| `last_error_message` | `str` | No | 마지막 오류 메시지 | 길이: 0-500자 |
| `uptime_seconds` | `int` | Yes | 시스템 가동 시간 (초) | >= 0 |
| `updated_at` | `datetime` | Yes | 마지막 업데이트 시간 (KST) | 타임존 명시 |

#### 구현 예시

```python
class SystemStatus(BaseModel):
    """System operation status and health information.

    Attributes:
        system_mode: Current system operation mode.
        market_phase: Current market trading phase.
        api_connected: Whether API connection is active.
        last_data_received_at: Last data reception timestamp.
        active_strategies: List of currently active strategy names.
        error_count: Cumulative error count.
        last_error_message: Last error message.
        uptime_seconds: System uptime in seconds.
        updated_at: Last status update timestamp.
    """
    system_mode: SystemMode = Field(default=SystemMode.STARTING)
    market_phase: MarketPhase = Field(default=MarketPhase.PRE_MARKET)
    api_connected: bool = Field(default=False)
    last_data_received_at: Optional[datetime] = None
    active_strategies: List[str] = Field(default_factory=list)
    error_count: int = Field(default=0, ge=0)
    last_error_message: Optional[str] = Field(None, max_length=500)
    uptime_seconds: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=KST))

    def is_healthy(self) -> bool:
        """Check if system is in healthy state.

        Returns:
            True if API connected, mode is RUNNING, and recent data received.
        """
        if not self.api_connected:
            return False

        if self.system_mode != SystemMode.RUNNING:
            return False

        # Check if data received in last 5 minutes
        if self.last_data_received_at:
            time_since_data = datetime.now(tz=KST) - self.last_data_received_at
            if time_since_data.total_seconds() > 300:  # 5 minutes
                return False

        return True

    def record_error(self, error_message: str) -> None:
        """Record an error occurrence.

        Args:
            error_message: Error message to record.
        """
        self.error_count += 1
        self.last_error_message = error_message[:500]  # Truncate if too long
        self.updated_at = datetime.now(tz=KST)

    def update_data_received(self) -> None:
        """Update last data received timestamp."""
        self.last_data_received_at = datetime.now(tz=KST)
        self.updated_at = datetime.now(tz=KST)

    class Config:
        """Pydantic configuration."""
        frozen = False
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
```

#### 실제 데이터 예시

```python
system_status = SystemStatus(
    system_mode=SystemMode.RUNNING,
    market_phase=MarketPhase.REGULAR,
    api_connected=True,
    last_data_received_at=datetime(2025, 11, 22, 14, 30, 0, tzinfo=KST),
    active_strategies=["Golden Cross Strategy", "Scalping Strategy"],
    error_count=3,
    last_error_message="API rate limit warning: 14/15 requests used",
    uptime_seconds=18000,  # 5시간
    updated_at=datetime(2025, 11, 22, 14, 30, 15, tzinfo=KST)
)

if system_status.is_healthy():
    print("시스템 정상 작동 중")
else:
    print(f"시스템 비정상: {system_status.last_error_message}")
```

---

### 8. ChartData (차트 데이터)

#### 목적

일봉/분봉 과거 가격 데이터 저장 및 기술적 분석 지원.

#### 필드 정의

| 필드명 | 타입 | 필수 | 설명 | 유효성 규칙 |
|-------|------|-----|------|-----------|
| `stock_code` | `str` | Yes | 종목코드 | 정규식: `^\d{6}$` |
| `interval` | `ChartInterval` | Yes | 차트 주기 (일봉, 분봉 등) | Enum |
| `timestamp` | `datetime` | Yes | 데이터 시점 (KST) | 타임존 명시 |
| `open_price` | `Decimal` | Yes | 시가 | > 0 |
| `high_price` | `Decimal` | Yes | 고가 | >= open_price |
| `low_price` | `Decimal` | Yes | 저가 | <= open_price |
| `close_price` | `Decimal` | Yes | 종가 | > 0 |
| `volume` | `int` | Yes | 거래량 | >= 0 |

#### 관계

- **N:1 with Stock**: 여러 차트 데이터는 하나의 종목에 속한다.

#### 구현 예시

```python
class ChartData(BaseModel):
    """Historical price chart data (OHLCV).

    Attributes:
        stock_code: Stock code.
        interval: Chart interval (daily, minute, etc.).
        timestamp: Data timestamp in KST.
        open_price: Opening price.
        high_price: Highest price.
        low_price: Lowest price.
        close_price: Closing price.
        volume: Trading volume.
    """
    stock_code: str = Field(..., pattern=r"^\d{6}$")
    interval: ChartInterval
    timestamp: datetime
    open_price: Decimal = Field(..., gt=0)
    high_price: Decimal = Field(..., gt=0)
    low_price: Decimal = Field(..., gt=0)
    close_price: Decimal = Field(..., gt=0)
    volume: int = Field(..., ge=0)

    @field_validator("high_price")
    @classmethod
    def validate_high_price(cls, v: Decimal, info) -> Decimal:
        """Validate high >= open, low, close.

        Args:
            v: High price to validate.
            info: Validation info containing other field values.

        Returns:
            Validated high price.

        Raises:
            ValueError: If high < open, low, or close.
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
        """Validate low <= open, high, close.

        Args:
            v: Low price to validate.
            info: Validation info containing other field values.

        Returns:
            Validated low price.

        Raises:
            ValueError: If low > open, high, or close.
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
        """Pydantic configuration."""
        frozen = True  # Immutable (historical data)
        use_enum_values = True
        json_encoders = {
            Decimal: str,
            datetime: lambda v: v.isoformat()
        }
```

#### 실제 데이터 예시

```python
# 일봉 데이터
daily_chart = ChartData(
    stock_code="005930",
    interval=ChartInterval.DAY,
    timestamp=datetime(2025, 11, 22, 15, 30, 0, tzinfo=KST),
    open_price=Decimal("71500.00"),
    high_price=Decimal("72500.00"),
    low_price=Decimal("71000.00"),
    close_price=Decimal("72000.00"),
    volume=15234567
)

# 5분봉 데이터
minute_5_chart = ChartData(
    stock_code="005930",
    interval=ChartInterval.MIN_5,
    timestamp=datetime(2025, 11, 22, 14, 30, 0, tzinfo=KST),
    open_price=Decimal("71800.00"),
    high_price=Decimal("72000.00"),
    low_price=Decimal("71750.00"),
    close_price=Decimal("71950.00"),
    volume=123456
)
```

---

## 엔티티 관계도

### ER Diagram (Text Format)

```
┌─────────────────┐
│    Account      │
│  (계좌)         │
├─────────────────┤
│ account_number  │◄────┐
│ name            │     │
│ cash_balance    │     │
│ total_asset_val │     │
│ total_pnl       │     │
│ daily_pnl       │     │
│ daily_loss_lmt  │     │
└─────────────────┘     │
                        │ 1
                        │
                        │ N
                 ┌──────┴──────┐
                 │             │
        ┌────────▼─────┐  ┌────▼──────────┐
        │   Position   │  │     Order     │
        │  (포지션)     │  │   (주문)      │
        ├──────────────┤  ├───────────────┤
        │ stock_code   │  │ order_id      │
        │ quantity     │  │ stock_code    │◄──┐
        │ avg_buy_price│  │ order_type    │   │
        │ current_price│  │ price_type    │   │
        │ strategy_name│◄┐│ quantity      │   │
        └──────┬───────┘ ││ status        │   │
               │         ││ filled_qty    │   │
               │ N       ││ strategy_name │◄┐ │
               │         │└───────────────┘ │ │
               │ 1       │                  │ │
        ┌──────▼─────┐  │                  │ │
        │   Stock    │  │                  │ │
        │  (종목)    │  │                  │ │
        ├────────────┤  │                  │ │
        │ stock_code │◄─┘                  │ │ N
        │ stock_name │                     │ │
        │ market     │                     │ │
        │ current_pr │                     │ │
        │ volume     │                     │ │ 1
        └────┬───────┘                     │ │
             │                             │ │
             │ 1                    ┌──────▼─┴────┐
             │                      │   Strategy  │
             │ N                    │   (전략)    │
        ┌────▼──────┐               ├─────────────┤
        │ ChartData │               │ strategy_nm │
        │ (차트)    │               │ enabled     │
        ├───────────┤               │ capital_all │
        │ stock_code│               │ max_pos     │
        │ interval  │               │ watched_stk │
        │ timestamp │               │ parameters  │
        │ open      │               └─────────────┘
        │ high      │
        │ low       │               ┌──────────────┐
        │ close     │               │ Notification │
        │ volume    │               │  (알림)      │
        └───────────┘               ├──────────────┤
                                    │ notif_id     │
┌──────────────┐                   │ notif_type   │
│ SystemStatus │                   │ title        │
│ (시스템상태)  │                   │ message      │
├──────────────┤                   │ metadata     │
│ system_mode  │                   │ sent         │
│ market_phase │                   └──────────────┘
│ api_connected│
│ active_strat │
│ error_count  │
└──────────────┘
```

### 관계 요약

| 관계 | Cardinality | 설명 |
|-----|-------------|------|
| Account ↔ Position | 1:N | 한 계좌는 여러 포지션을 보유 |
| Account ↔ Order | 1:N | 한 계좌에서 여러 주문 발생 |
| Stock ↔ Position | 1:N | 한 종목은 여러 계좌에서 보유 가능 |
| Stock ↔ Order | 1:N | 한 종목에 대해 여러 주문 발생 |
| Stock ↔ ChartData | 1:N | 한 종목은 여러 차트 데이터 보유 |
| Strategy ↔ Order | 1:N | 한 전략은 여러 주문 생성 |
| Strategy ↔ Position | 1:N | 한 전략은 여러 포지션 보유 |

---

## 저장소 구현 전략

### 1. 영속성 계층 (Persistence Layer)

#### SQLite 데이터베이스

**목적**: 주문 내역, 포지션 히스토리, 차트 데이터의 장기 보관.

**테이블 스키마**:

```sql
-- 주문 내역 테이블
CREATE TABLE orders (
    order_id TEXT PRIMARY KEY,
    account_number TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    order_type TEXT NOT NULL,
    price_type TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    limit_price TEXT,
    status TEXT NOT NULL,
    filled_quantity INTEGER DEFAULT 0,
    filled_price TEXT,
    strategy_name TEXT,
    created_at TEXT NOT NULL,
    submitted_at TEXT,
    filled_at TEXT,
    error_message TEXT
);

CREATE INDEX idx_orders_account ON orders(account_number);
CREATE INDEX idx_orders_stock ON orders(stock_code);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_created_at ON orders(created_at);

-- 포지션 히스토리 테이블 (종료된 포지션 기록)
CREATE TABLE position_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_number TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    average_buy_price TEXT NOT NULL,
    sell_price TEXT NOT NULL,
    realized_pnl TEXT NOT NULL,
    return_rate TEXT NOT NULL,
    strategy_name TEXT,
    opened_at TEXT NOT NULL,
    closed_at TEXT NOT NULL
);

CREATE INDEX idx_position_history_account ON position_history(account_number);
CREATE INDEX idx_position_history_closed_at ON position_history(closed_at);

-- 차트 데이터 테이블
CREATE TABLE chart_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    interval TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open_price TEXT NOT NULL,
    high_price TEXT NOT NULL,
    low_price TEXT NOT NULL,
    close_price TEXT NOT NULL,
    volume INTEGER NOT NULL,
    UNIQUE(stock_code, interval, timestamp)
);

CREATE INDEX idx_chart_data_stock_interval ON chart_data(stock_code, interval);
CREATE INDEX idx_chart_data_timestamp ON chart_data(timestamp);

-- 알림 로그 테이블
CREATE TABLE notifications (
    notification_id TEXT PRIMARY KEY,
    notification_type TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata TEXT,  -- JSON
    sent BOOLEAN NOT NULL,
    created_at TEXT NOT NULL,
    sent_at TEXT
);

CREATE INDEX idx_notifications_type ON notifications(notification_type);
CREATE INDEX idx_notifications_created_at ON notifications(created_at);
```

#### 인메모리 저장소

**목적**: 실시간 데이터의 빠른 읽기/쓰기.

**저장 데이터**:
- 현재 계좌 상태 (Account)
- 활성 포지션 (Position)
- 최신 주식 시세 (Stock)
- 시스템 상태 (SystemStatus)
- 진행 중인 주문 (Order with status != FILLED/CANCELLED/REJECTED/FAILED)

**구현 방식**:
```python
from typing import Dict, List

class InMemoryStore:
    """In-memory data store for real-time data.

    Attributes:
        account: Current account state.
        positions: Active positions indexed by stock_code.
        stocks: Current stock prices indexed by stock_code.
        pending_orders: Orders not in terminal state.
        system_status: Current system status.
    """

    def __init__(self):
        self.account: Optional[Account] = None
        self.positions: Dict[str, Position] = {}
        self.stocks: Dict[str, Stock] = {}
        self.pending_orders: Dict[str, Order] = {}
        self.system_status: SystemStatus = SystemStatus()

    def get_position(self, stock_code: str) -> Optional[Position]:
        """Get position by stock code.

        Args:
            stock_code: Stock code to lookup.

        Returns:
            Position if exists, None otherwise.
        """
        return self.positions.get(stock_code)

    def update_position(self, position: Position) -> None:
        """Update or insert position.

        Args:
            position: Position to update.
        """
        self.positions[position.stock_code] = position

    def remove_position(self, stock_code: str) -> None:
        """Remove position (when fully sold).

        Args:
            stock_code: Stock code to remove.
        """
        self.positions.pop(stock_code, None)
```

### 2. 데이터 동기화 전략

#### 쓰기 패턴 (Write Pattern)

1. **주문 생성 시**:
   - 인메모리에 `pending_orders`에 추가
   - SQLite `orders` 테이블에 INSERT

2. **주문 체결 시**:
   - 인메모리 `pending_orders` 업데이트
   - SQLite `orders` 테이블 UPDATE
   - 포지션 업데이트 (인메모리 `positions` 및 SQLite `position_history`)

3. **포지션 청산 시**:
   - 인메모리 `positions`에서 제거
   - SQLite `position_history`에 INSERT

4. **차트 데이터 수집 시**:
   - 인메모리에는 최근 N개만 보관 (예: 최근 100개 캔들)
   - SQLite `chart_data`에 모든 데이터 저장

#### 읽기 패턴 (Read Pattern)

1. **실시간 조회** (계좌, 포지션, 주문): 인메모리에서 읽기
2. **과거 조회** (히스토리, 차트): SQLite에서 읽기
3. **시스템 재시작 시**: SQLite에서 데이터 로드하여 인메모리 초기화

### 3. 저장소 인터페이스 (Repository Pattern)

```python
from abc import ABC, abstractmethod
from typing import List, Optional

class OrderRepository(ABC):
    """Abstract repository for Order persistence."""

    @abstractmethod
    async def save(self, order: Order) -> None:
        """Save or update an order."""
        pass

    @abstractmethod
    async def get_by_id(self, order_id: str) -> Optional[Order]:
        """Get order by ID."""
        pass

    @abstractmethod
    async def get_pending_orders(self, account_number: str) -> List[Order]:
        """Get all pending orders for an account."""
        pass

    @abstractmethod
    async def get_orders_by_stock(
        self,
        stock_code: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Order]:
        """Get orders for a stock within date range."""
        pass


class SQLiteOrderRepository(OrderRepository):
    """SQLite implementation of OrderRepository."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def save(self, order: Order) -> None:
        """Save order to SQLite database."""
        # Implementation using aiosqlite
        pass

    async def get_by_id(self, order_id: str) -> Optional[Order]:
        """Get order by ID from database."""
        # Implementation
        pass
```

---

## 유효성 검증 및 비즈니스 로직

### 1. Pydantic 검증 (Field-level Validation)

모든 엔티티는 Pydantic의 `Field` 제약 조건과 `@field_validator`를 사용하여 필드 수준 검증을 수행한다.

**예시**: 주문 수량은 반드시 양수
```python
quantity: int = Field(..., gt=0, description="Order quantity must be positive")
```

### 2. 비즈니스 로직 검증 (Business Logic Validation)

#### 주문 실행 전 검증 (Pre-Order Validation)

```python
from decimal import Decimal
from typing import Optional

class OrderValidator:
    """Validates orders before execution."""

    @staticmethod
    def validate_buy_order(
        account: Account,
        order: Order,
        current_price: Decimal
    ) -> tuple[bool, Optional[str]]:
        """Validate buy order before submission.

        Args:
            account: User account.
            order: Order to validate.
            current_price: Current stock price.

        Returns:
            Tuple of (is_valid, error_message).
        """
        # 예수금 확인
        estimated_cost = current_price * order.quantity
        if account.cash_balance < estimated_cost:
            return False, f"Insufficient balance: {account.cash_balance} < {estimated_cost}"

        # 수량 확인 (최소 1주)
        if order.quantity < 1:
            return False, "Order quantity must be at least 1"

        # 일일 손실 한도 확인
        if account.is_daily_loss_limit_exceeded():
            return False, "Daily loss limit exceeded, trading suspended"

        return True, None

    @staticmethod
    def validate_sell_order(
        position: Optional[Position],
        order: Order
    ) -> tuple[bool, Optional[str]]:
        """Validate sell order before submission.

        Args:
            position: Current position (if exists).
            order: Order to validate.

        Returns:
            Tuple of (is_valid, error_message).
        """
        # 포지션 존재 확인
        if not position:
            return False, f"No position found for stock {order.stock_code}"

        # 매도 가능 수량 확인
        if order.quantity > position.quantity:
            return False, f"Insufficient quantity: {position.quantity} < {order.quantity}"

        return True, None
```

#### 중복 주문 방지 (Duplicate Order Prevention)

```python
class DuplicateOrderChecker:
    """Prevents duplicate orders for the same stock."""

    def __init__(self, in_memory_store: InMemoryStore):
        self.store = in_memory_store

    def check_duplicate(self, stock_code: str, order_type: OrderType) -> tuple[bool, Optional[str]]:
        """Check if there's already a pending order for this stock.

        Args:
            stock_code: Stock code to check.
            order_type: Order type (BUY/SELL).

        Returns:
            Tuple of (is_duplicate, existing_order_id).
        """
        for order_id, order in self.store.pending_orders.items():
            if order.stock_code == stock_code and order.order_type == order_type:
                if not order.is_terminal_state():
                    return True, order_id

        return False, None
```

#### 위험 관리 검증 (Risk Management Validation)

```python
class RiskManager:
    """Manages trading risk limits."""

    def __init__(self, daily_loss_limit: Decimal):
        self.daily_loss_limit = daily_loss_limit

    def check_daily_loss_limit(self, account: Account) -> tuple[bool, Optional[str]]:
        """Check if daily loss limit has been exceeded.

        Args:
            account: User account.

        Returns:
            Tuple of (is_exceeded, warning_message).
        """
        if account.daily_pnl < -self.daily_loss_limit:
            return True, f"Daily loss limit exceeded: {account.daily_pnl} < -{self.daily_loss_limit}"

        # 80% 경고
        if account.daily_pnl < -(self.daily_loss_limit * Decimal("0.8")):
            warning = f"Daily loss approaching limit (80%): {account.daily_pnl}"
            return False, warning

        return False, None

    def check_position_concentration(
        self,
        positions: List[Position],
        total_asset_value: Decimal,
        max_concentration: Decimal = Decimal("0.3")
    ) -> tuple[bool, Optional[str]]:
        """Check if any single position exceeds concentration limit.

        Args:
            positions: List of all positions.
            total_asset_value: Total portfolio value.
            max_concentration: Maximum allowed concentration (default 30%).

        Returns:
            Tuple of (is_exceeded, warning_message).
        """
        for position in positions:
            concentration = position.evaluation_amount / total_asset_value
            if concentration > max_concentration:
                return True, f"Position {position.stock_code} exceeds {max_concentration*100}% limit: {concentration*100:.2f}%"

        return False, None
```

### 3. 시간대 검증 (Market Hours Validation)

```python
from datetime import time

class MarketHoursChecker:
    """Checks market operating hours and phases."""

    @staticmethod
    def get_market_phase(current_time: datetime) -> MarketPhase:
        """Determine current market phase based on KST time.

        Args:
            current_time: Current datetime in KST.

        Returns:
            Current market phase.
        """
        current_time_only = current_time.time()

        if current_time_only < time(9, 0):
            return MarketPhase.PRE_MARKET
        elif time(9, 0) <= current_time_only < time(9, 5):
            return MarketPhase.OPENING
        elif time(9, 5) <= current_time_only < time(15, 20):
            return MarketPhase.REGULAR
        elif time(15, 20) <= current_time_only < time(15, 30):
            return MarketPhase.CLOSING_SOON
        else:
            return MarketPhase.CLOSED

    @staticmethod
    def can_place_buy_order(current_time: datetime) -> tuple[bool, Optional[str]]:
        """Check if buy orders are allowed at current time.

        Args:
            current_time: Current datetime in KST.

        Returns:
            Tuple of (is_allowed, reason_if_not).
        """
        phase = MarketHoursChecker.get_market_phase(current_time)

        # 장 마감 10분 전부터 신규 매수 차단
        if phase == MarketPhase.CLOSING_SOON:
            return False, "Buy orders blocked 10 minutes before market close"

        # 장 마감 후 차단
        if phase == MarketPhase.CLOSED:
            return False, "Market is closed"

        return True, None
```

---

## 사용 예시 (Complete Workflow)

### 전략 실행 → 주문 생성 → 체결 → 포지션 업데이트

```python
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

async def trading_workflow_example():
    """Complete trading workflow example."""

    # 1. 계좌 초기화
    account = Account(
        account_number="12345678",
        name="김철수 위탁계좌",
        cash_balance=Decimal("10000000.00"),
        total_asset_value=Decimal("10000000.00"),
        daily_loss_limit=Decimal("500000.00")
    )

    # 2. 종목 데이터 수신
    samsung = Stock(
        stock_code="005930",
        stock_name="삼성전자",
        market=MarketType.KOSPI,
        current_price=Decimal("72000.00"),
        open_price=Decimal("71500.00"),
        volume=15234567
    )

    # 3. 전략 평가 (골든크로스 전략 예시)
    strategy_config = StrategyConfig(
        strategy_name="Golden Cross Strategy",
        enabled=True,
        capital_allocation=Decimal("5000000.00"),
        max_positions=10,
        watched_stocks=["005930"],
        parameters={
            "short_period": 5,
            "long_period": 20,
            "stop_loss_pct": 0.03,
            "take_profit_pct": 0.05
        }
    )

    strategy = GoldenCrossStrategy(strategy_config)

    # 매수 시그널 평가
    buy_signal = await strategy.evaluate_buy_signal(samsung)

    if buy_signal:
        # 4. 주문 생성
        buy_order = Order(
            account_number=account.account_number,
            stock_code=samsung.stock_code,
            order_type=OrderType.BUY,
            price_type=PriceType.LIMIT,
            quantity=100,
            limit_price=Decimal("72000.00"),
            strategy_name=strategy_config.strategy_name
        )

        # 5. 주문 전 검증
        validator = OrderValidator()
        is_valid, error_msg = validator.validate_buy_order(account, buy_order, samsung.current_price)

        if not is_valid:
            print(f"주문 검증 실패: {error_msg}")
            return

        # 6. 중복 주문 확인
        in_memory_store = InMemoryStore()
        dup_checker = DuplicateOrderChecker(in_memory_store)
        is_duplicate, existing_order_id = dup_checker.check_duplicate(
            samsung.stock_code,
            OrderType.BUY
        )

        if is_duplicate:
            print(f"중복 주문 차단: {existing_order_id}")
            return

        # 7. 시장 시간 확인
        market_checker = MarketHoursChecker()
        can_buy, reason = market_checker.can_place_buy_order(datetime.now(tz=KST))

        if not can_buy:
            print(f"주문 불가: {reason}")
            return

        # 8. 주문 제출
        buy_order.status = OrderStatus.SUBMITTED
        buy_order.submitted_at = datetime.now(tz=KST)

        # 저장소에 저장
        order_repo = SQLiteOrderRepository("data/orders.db")
        await order_repo.save(buy_order)

        # 인메모리에 추가
        in_memory_store.pending_orders[buy_order.order_id] = buy_order

        print(f"주문 제출: {buy_order.order_id}")

        # 9. 주문 체결 (API 응답 시뮬레이션)
        buy_order.status = OrderStatus.FILLED
        buy_order.filled_quantity = 100
        buy_order.filled_price = Decimal("72000.00")
        buy_order.filled_at = datetime.now(tz=KST)

        await order_repo.save(buy_order)
        in_memory_store.pending_orders.pop(buy_order.order_id)

        print(f"주문 체결: {buy_order.calculate_total_cost():,}원")

        # 10. 포지션 생성
        position = Position(
            account_number=account.account_number,
            stock_code=samsung.stock_code,
            quantity=buy_order.filled_quantity,
            average_buy_price=buy_order.filled_price,
            current_price=samsung.current_price,
            strategy_name=strategy_config.strategy_name
        )

        in_memory_store.update_position(position)

        print(f"포지션 생성: {position.quantity}주 @ {position.average_buy_price:,}원")

        # 11. 계좌 업데이트
        account.cash_balance -= buy_order.calculate_total_cost()
        account.total_asset_value = account.cash_balance + position.evaluation_amount

        print(f"계좌 잔고: {account.cash_balance:,}원")

        # 12. 알림 전송
        notification = Notification(
            notification_type=NotificationType.ORDER_FILLED,
            title="매수 주문 체결",
            message=f"{samsung.stock_name} {buy_order.filled_quantity}주가 {buy_order.filled_price:,}원에 매수 체결되었습니다.",
            metadata={
                "order_id": buy_order.order_id,
                "stock_code": samsung.stock_code,
                "stock_name": samsung.stock_name,
                "order_type": "BUY",
                "quantity": buy_order.filled_quantity,
                "price": str(buy_order.filled_price)
            }
        )

        # 알림 전송 (Discord, Email)
        # await notifier.send_order_notification(...)
        notification.mark_as_sent()

        print(f"알림 전송: {notification.title}")

# 실행
# asyncio.run(trading_workflow_example())
```

---

## 요약

본 데이터 모델 명세는 키움증권 자동매매 시스템의 모든 핵심 엔티티를 Pydantic 기반으로 정의하였으며, 다음 원칙을 준수한다:

1. **타입 안전성**: 모든 필드에 타입 힌트 및 Pydantic 검증 적용
2. **금융 데이터 정확성**: Decimal 타입 사용으로 부동소수점 오차 방지
3. **시간대 명확성**: KST 타임존 명시적 처리
4. **확장성**: 전략 추가 및 새로운 기능 확장 용이
5. **추적성**: 모든 주문 및 거래 내역의 완전한 감사 추적

이 문서를 기반으로 Phase 2 (Task Generation)에서 구현 작업을 구체화할 수 있다.

---

**다음 단계**: [tasks.md](./tasks.md) 생성 (`/speckit.tasks` 명령)
