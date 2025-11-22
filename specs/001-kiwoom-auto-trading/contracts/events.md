# 이벤트 기반 통신 계약 명세

**Feature Branch**: `001-kiwoom-auto-trading`
**Created**: 2025-11-22
**Status**: Draft
**Related**: [spec.md](../spec.md) | [data-model.md](../data-model.md) | [internal-interfaces.md](./internal-interfaces.md)

## 개요

본 문서는 자동매매 시스템 내부의 이벤트 기반 통신 계약을 정의한다. 컴포넌트 간 느슨한 결합(Loose Coupling)을 위해 Pub/Sub 패턴을 사용하며, 모든 이벤트는 명확한 타입과 페이로드 구조를 가진다.

## 목차

1. [이벤트 아키텍처](#이벤트-아키텍처)
2. [이벤트 타입 정의](#이벤트-타입-정의)
3. [시장 데이터 이벤트](#시장-데이터-이벤트)
4. [주문 관련 이벤트](#주문-관련-이벤트)
5. [위험 관리 이벤트](#위험-관리-이벤트)
6. [시스템 이벤트](#시스템-이벤트)
7. [이벤트 플로우 다이어그램](#이벤트-플로우-다이어그램)
8. [이벤트 버스 구현](#이벤트-버스-구현)

---

## 이벤트 아키텍처

### Pub/Sub 패턴

시스템은 중앙 이벤트 버스를 통해 이벤트를 발행(Publish)하고 구독(Subscribe)한다.

```
┌─────────────┐        ┌─────────────────┐        ┌─────────────┐
│ Publisher   │──pub──>│   Event Bus     │──sub──>│ Subscriber  │
│ (Producer)  │        │  (Event Broker) │        │ (Consumer)  │
└─────────────┘        └─────────────────┘        └─────────────┘

예시:
DataCollector ──MarketDataReceived──> EventBus ──> Strategy (evaluate signal)
                                                ──> RiskManager (check limits)
```

### 이벤트 흐름 원칙

1. **비동기 처리**: 모든 이벤트 핸들러는 `async` 함수
2. **순서 보장 없음**: 이벤트 처리 순서는 보장되지 않음
3. **멱등성**: 이벤트 핸들러는 동일 이벤트를 여러 번 받아도 안전해야 함
4. **에러 격리**: 한 핸들러의 에러가 다른 핸들러에 영향을 주지 않음

---

## 이벤트 타입 정의

### 기본 이벤트 클래스

모든 이벤트는 다음 베이스 클래스를 상속한다:

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any, Dict
from uuid import uuid4
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

class BaseEvent(BaseModel):
    """Base class for all events.

    Attributes:
        event_id: Unique event identifier.
        event_type: Type of event (e.g., "MarketDataReceived").
        timestamp: When the event occurred (KST).
        source: Component that published the event.
        metadata: Additional metadata (optional).
    """
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str = Field(..., description="Event type identifier")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=KST))
    source: str = Field(..., description="Event publisher component")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        """Pydantic configuration."""
        frozen = True  # Events are immutable
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
```

---

## 시장 데이터 이벤트

### 1. MarketDataReceivedEvent

**설명**: 실시간 시세 데이터가 수신되었을 때 발행.

**발행자**: `DataCollector`

**구독자**: `Strategy`, `RiskManager`, `SystemHealthCheck`

**페이로드**:

```python
class MarketDataReceivedEvent(BaseEvent):
    """Event published when new market data is received.

    Attributes:
        stock: Current stock data.
    """
    event_type: str = Field(default="MarketDataReceived", const=True)
    stock: Stock

# 사용 예시
event = MarketDataReceivedEvent(
    source="KiwoomDataCollector",
    stock=Stock(
        stock_code="005930",
        stock_name="삼성전자",
        market=MarketType.KOSPI,
        current_price=Decimal("72000"),
        volume=15234567,
        updated_at=datetime.now(tz=KST)
    )
)
```

**이벤트 플로우**:

```
DataCollector ──> EventBus ──> Strategy.on_market_data(event)
                           ──> RiskManager.update_position_value(event)
                           ──> HealthCheck.record_data_received(event)
```

---

### 2. ChartDataLoadedEvent

**설명**: 과거 차트 데이터가 로드되었을 때 발행.

**발행자**: `DataCollector`

**구독자**: `Strategy` (기술적 분석용)

**페이로드**:

```python
class ChartDataLoadedEvent(BaseEvent):
    """Event published when chart data is loaded.

    Attributes:
        stock_code: Stock code.
        interval: Chart interval (DAY, MIN_5, etc.).
        chart_data: List of OHLCV data.
    """
    event_type: str = Field(default="ChartDataLoaded", const=True)
    stock_code: str
    interval: ChartInterval
    chart_data: List[ChartData]

# 사용 예시
event = ChartDataLoadedEvent(
    source="KiwoomDataCollector",
    stock_code="005930",
    interval=ChartInterval.DAY,
    chart_data=[
        ChartData(
            stock_code="005930",
            interval=ChartInterval.DAY,
            timestamp=datetime(2025, 11, 22, 15, 30, 0, tzinfo=KST),
            open_price=Decimal("71500"),
            high_price=Decimal("72500"),
            low_price=Decimal("71000"),
            close_price=Decimal("72000"),
            volume=15234567
        )
    ]
)
```

---

## 주문 관련 이벤트

### 3. OrderCreatedEvent

**설명**: 새로운 주문이 생성되었을 때 발행 (아직 제출 전).

**발행자**: `OrderExecutor`

**구독자**: `Notifier`, `RiskManager`, `OrderRepository`

**페이로드**:

```python
class OrderCreatedEvent(BaseEvent):
    """Event published when an order is created.

    Attributes:
        order: Created order with PENDING status.
    """
    event_type: str = Field(default="OrderCreated", const=True)
    order: Order

# 사용 예시
event = OrderCreatedEvent(
    source="KiwoomOrderExecutor",
    order=Order(
        order_id="temp-uuid",
        account_number="12345678",
        stock_code="005930",
        order_type=OrderType.BUY,
        price_type=PriceType.LIMIT,
        quantity=100,
        limit_price=Decimal("72000"),
        status=OrderStatus.PENDING
    )
)
```

---

### 4. OrderSubmittedEvent

**설명**: 주문이 브로커 API로 제출되었을 때 발행.

**발행자**: `OrderExecutor`

**구독자**: `Notifier`, `OrderRepository`, `Strategy`

**페이로드**:

```python
class OrderSubmittedEvent(BaseEvent):
    """Event published when an order is submitted to broker.

    Attributes:
        order: Order with SUBMITTED status and broker order_id.
    """
    event_type: str = Field(default="OrderSubmitted", const=True)
    order: Order

# 사용 예시
event = OrderSubmittedEvent(
    source="KiwoomOrderExecutor",
    order=Order(
        order_id="2025112212345678",  # Broker order ID
        account_number="12345678",
        stock_code="005930",
        order_type=OrderType.BUY,
        status=OrderStatus.SUBMITTED,
        submitted_at=datetime.now(tz=KST)
    )
)
```

---

### 5. OrderFilledEvent

**설명**: 주문이 완전히 체결되었을 때 발행.

**발행자**: `OrderExecutor`

**구독자**: `Notifier`, `PositionManager`, `Strategy`, `RiskManager`, `Account`

**페이로드**:

```python
class OrderFilledEvent(BaseEvent):
    """Event published when an order is fully filled.

    Attributes:
        order: Filled order with FILLED status.
        stock_name: Stock name for notifications.
    """
    event_type: str = Field(default="OrderFilled", const=True)
    order: Order
    stock_name: str

# 사용 예시
event = OrderFilledEvent(
    source="KiwoomOrderExecutor",
    order=Order(
        order_id="2025112212345678",
        account_number="12345678",
        stock_code="005930",
        order_type=OrderType.BUY,
        status=OrderStatus.FILLED,
        quantity=100,
        filled_quantity=100,
        filled_price=Decimal("72000"),
        filled_at=datetime.now(tz=KST)
    ),
    stock_name="삼성전자"
)
```

**이벤트 플로우**:

```
OrderExecutor ──> EventBus ──> Notifier.send_order_notification(event)
                           ──> PositionManager.update_position(event)
                           ──> Strategy.on_order_filled(event)
                           ──> Account.update_balance(event)
```

---

### 6. OrderPartiallyFilledEvent

**설명**: 주문이 부분 체결되었을 때 발행.

**발행자**: `OrderExecutor`

**구독자**: `Notifier`, `OrderRepository`

**페이로드**:

```python
class OrderPartiallyFilledEvent(BaseEvent):
    """Event published when an order is partially filled.

    Attributes:
        order: Order with PARTIALLY_FILLED status.
        filled_quantity_delta: Additional quantity filled since last update.
    """
    event_type: str = Field(default="OrderPartiallyFilled", const=True)
    order: Order
    filled_quantity_delta: int

# 사용 예시
event = OrderPartiallyFilledEvent(
    source="KiwoomOrderExecutor",
    order=Order(
        order_id="2025112212345678",
        quantity=100,
        filled_quantity=50,
        status=OrderStatus.PARTIALLY_FILLED
    ),
    filled_quantity_delta=50
)
```

---

### 7. OrderCancelledEvent

**설명**: 주문이 취소되었을 때 발행.

**발행자**: `OrderExecutor`

**구독자**: `Notifier`, `OrderRepository`, `Strategy`

**페이로드**:

```python
class OrderCancelledEvent(BaseEvent):
    """Event published when an order is cancelled.

    Attributes:
        order: Order with CANCELLED status.
        cancellation_reason: Reason for cancellation.
    """
    event_type: str = Field(default="OrderCancelled", const=True)
    order: Order
    cancellation_reason: str

# 사용 예시
event = OrderCancelledEvent(
    source="KiwoomOrderExecutor",
    order=Order(
        order_id="2025112212345678",
        status=OrderStatus.CANCELLED
    ),
    cancellation_reason="User requested cancellation"
)
```

---

### 8. OrderRejectedEvent

**설명**: 브로커가 주문을 거부했을 때 발행.

**발행자**: `OrderExecutor`

**구독자**: `Notifier`, `Strategy`, `RiskManager`

**페이로드**:

```python
class OrderRejectedEvent(BaseEvent):
    """Event published when broker rejects an order.

    Attributes:
        order: Order with REJECTED status.
        rejection_reason: Broker's rejection reason.
    """
    event_type: str = Field(default="OrderRejected", const=True)
    order: Order
    rejection_reason: str

# 사용 예시
event = OrderRejectedEvent(
    source="KiwoomOrderExecutor",
    order=Order(
        order_id="2025112212345678",
        status=OrderStatus.REJECTED,
        error_message="예수금 부족"
    ),
    rejection_reason="ORDR0001: 예수금 부족"
)
```

---

## 위험 관리 이벤트

### 9. DailyLossLimitExceededEvent

**설명**: 일일 손실 한도가 초과되었을 때 발행.

**발행자**: `RiskManager`

**구독자**: `TradingEngine` (매매 중단), `Notifier`

**페이로드**:

```python
class DailyLossLimitExceededEvent(BaseEvent):
    """Event published when daily loss limit is exceeded.

    Attributes:
        account: Account that exceeded limit.
        daily_pnl: Current daily P&L (negative).
        daily_loss_limit: Configured daily loss limit.
    """
    event_type: str = Field(default="DailyLossLimitExceeded", const=True)
    account: Account
    daily_pnl: Decimal
    daily_loss_limit: Decimal

# 사용 예시
event = DailyLossLimitExceededEvent(
    source="PositionRiskManager",
    account=account,
    daily_pnl=Decimal("-800000"),
    daily_loss_limit=Decimal("750000")
)
```

**이벤트 플로우**:

```
RiskManager ──> EventBus ──> TradingEngine.halt_all_strategies()
                         ──> Notifier.send_risk_alert("CRITICAL: Daily loss limit exceeded")
```

---

### 10. RiskWarningEvent

**설명**: 위험 경고 (80% 한도 도달 등).

**발행자**: `RiskManager`

**구독자**: `Notifier`

**페이로드**:

```python
class RiskWarningEvent(BaseEvent):
    """Event published for risk warnings.

    Attributes:
        warning_type: Type of warning (LOSS_APPROACHING, CONCENTRATION, etc.).
        message: Warning details.
        severity: WARNING or CRITICAL.
    """
    event_type: str = Field(default="RiskWarning", const=True)
    warning_type: str
    message: str
    severity: str = "WARNING"

# 사용 예시
event = RiskWarningEvent(
    source="PositionRiskManager",
    warning_type="LOSS_APPROACHING",
    message="Daily loss at 80% of limit: -600,000원 / -750,000원",
    severity="WARNING"
)
```

---

## 시스템 이벤트

### 11. SystemStartedEvent

**설명**: 시스템이 시작되었을 때 발행.

**발행자**: `TradingEngine`

**구독자**: 모든 컴포넌트

**페이로드**:

```python
class SystemStartedEvent(BaseEvent):
    """Event published when system starts.

    Attributes:
        system_mode: Initial system mode (STARTING).
    """
    event_type: str = Field(default="SystemStarted", const=True)
    system_mode: SystemMode

# 사용 예시
event = SystemStartedEvent(
    source="TradingEngine",
    system_mode=SystemMode.STARTING
)
```

---

### 12. SystemShutdownEvent

**설명**: 시스템이 종료될 때 발행.

**발행자**: `TradingEngine`

**구독자**: 모든 컴포넌트 (정리 작업 수행)

**페이로드**:

```python
class SystemShutdownEvent(BaseEvent):
    """Event published when system is shutting down.

    Attributes:
        reason: Shutdown reason (user request, error, etc.).
    """
    event_type: str = Field(default="SystemShutdown", const=True)
    reason: str

# 사용 예시
event = SystemShutdownEvent(
    source="TradingEngine",
    reason="User requested shutdown"
)
```

---

### 13. MarketPhaseChangedEvent

**설명**: 시장 상태가 변경되었을 때 발행 (장 시작, 마감 등).

**발행자**: `MarketHoursMonitor`

**구독자**: `TradingEngine`, `Strategy`, `DataCollector`

**페이로드**:

```python
class MarketPhaseChangedEvent(BaseEvent):
    """Event published when market phase changes.

    Attributes:
        previous_phase: Previous market phase.
        current_phase: New market phase.
    """
    event_type: str = Field(default="MarketPhaseChanged", const=True)
    previous_phase: MarketPhase
    current_phase: MarketPhase

# 사용 예시
event = MarketPhaseChangedEvent(
    source="MarketHoursMonitor",
    previous_phase=MarketPhase.PRE_MARKET,
    current_phase=MarketPhase.OPENING
)
```

**이벤트 플로우**:

```
MarketHoursMonitor ──> EventBus ──> TradingEngine.on_market_open()
                                ──> Strategy.on_market_open()
                                ──> DataCollector.start_realtime_collection()
```

---

### 14. ErrorOccurredEvent

**설명**: 시스템 에러가 발생했을 때 발행.

**발행자**: 모든 컴포넌트

**구독자**: `Notifier`, `HealthCheck`, `SystemLogger`

**페이로드**:

```python
class ErrorOccurredEvent(BaseEvent):
    """Event published when an error occurs.

    Attributes:
        error_type: Type of error (API_ERROR, VALIDATION_ERROR, etc.).
        error_message: Error details.
        component: Component where error occurred.
        recoverable: Whether error is recoverable.
    """
    event_type: str = Field(default="ErrorOccurred", const=True)
    error_type: str
    error_message: str
    component: str
    recoverable: bool = True

# 사용 예시
event = ErrorOccurredEvent(
    source="KiwoomDataCollector",
    error_type="API_ERROR",
    error_message="Rate limit exceeded: RATE0001",
    component="DataCollector",
    recoverable=True
)
```

---

### 15. HealthCheckFailedEvent

**설명**: 헬스 체크 실패 시 발행.

**발행자**: `HealthCheck`

**구독자**: `Notifier`, `TradingEngine`

**페이로드**:

```python
class HealthCheckFailedEvent(BaseEvent):
    """Event published when health check fails.

    Attributes:
        check_type: Type of check (API_CONNECTION, DATA_FRESHNESS, etc.).
        failure_reason: Reason for failure.
    """
    event_type: str = Field(default="HealthCheckFailed", const=True)
    check_type: str
    failure_reason: str

# 사용 예시
event = HealthCheckFailedEvent(
    source="SystemHealthCheck",
    check_type="DATA_FRESHNESS",
    failure_reason="No market data received in last 5 minutes"
)
```

---

## 이벤트 플로우 다이어그램

### 매수 주문 실행 플로우

```
1. MarketDataReceived
   DataCollector ──> Strategy

2. Strategy 매수 조건 충족
   Strategy ──> OrderCreated
            ──> RiskManager (validate)
            ──> OrderExecutor

3. OrderSubmitted
   OrderExecutor ──> Notifier (알림)
                 ──> OrderRepository (저장)

4. OrderFilled
   OrderExecutor ──> PositionManager (포지션 업데이트)
                 ──> Account (잔고 업데이트)
                 ──> Notifier (체결 알림)
                 ──> Strategy (callback)
```

### 위험 한도 초과 플로우

```
1. MarketDataReceived
   DataCollector ──> RiskManager

2. RiskManager detects loss limit exceeded
   RiskManager ──> DailyLossLimitExceeded
               ──> TradingEngine (halt)
               ──> Notifier (긴급 알림)

3. TradingEngine halts all strategies
   TradingEngine ──> Strategy.disable() for all
```

### 시스템 시작/종료 플로우

```
System Startup:
TradingEngine ──> SystemStarted
              ──> DataCollector.start()
              ──> OrderExecutor.initialize()
              ──> Strategy.load_config()

Market Open:
MarketHoursMonitor ──> MarketPhaseChanged (OPENING)
                   ──> Strategy.on_market_open()
                   ──> DataCollector.subscribe_realtime()

Market Close:
MarketHoursMonitor ──> MarketPhaseChanged (CLOSED)
                   ──> Strategy.on_market_close()
                   ──> Notifier.send_daily_report()
```

---

## 이벤트 버스 구현

### EventBus 인터페이스

```python
from typing import Callable, List, Dict, Type
from collections import defaultdict
import asyncio
import logging

logger = logging.getLogger(__name__)

class EventBus:
    """Central event bus for pub/sub messaging.

    All components publish and subscribe to events through this bus.
    """

    def __init__(self):
        """Initialize event bus."""
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[BaseEvent], None]
    ) -> None:
        """Subscribe to an event type.

        Args:
            event_type: Type of event to subscribe to.
            handler: Async callback function to handle events.
                     Signature: async def handler(event: BaseEvent) -> None
        """
        self._subscribers[event_type].append(handler)
        logger.info(f"Subscribed to {event_type}: {handler.__name__}")

    def unsubscribe(
        self,
        event_type: str,
        handler: Callable
    ) -> None:
        """Unsubscribe from an event type.

        Args:
            event_type: Event type.
            handler: Handler to remove.
        """
        if event_type in self._subscribers:
            self._subscribers[event_type].remove(handler)
            logger.info(f"Unsubscribed from {event_type}: {handler.__name__}")

    async def publish(self, event: BaseEvent) -> None:
        """Publish an event to all subscribers.

        Calls all registered handlers for the event type.
        Handlers are called concurrently and errors are isolated.

        Args:
            event: Event to publish.
        """
        event_type = event.event_type
        logger.info(f"Publishing event: {event_type} (id={event.event_id})")

        if event_type not in self._subscribers:
            logger.warning(f"No subscribers for event type: {event_type}")
            return

        # Call all handlers concurrently
        tasks = []
        for handler in self._subscribers[event_type]:
            tasks.append(self._call_handler_safe(handler, event))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _call_handler_safe(
        self,
        handler: Callable,
        event: BaseEvent
    ) -> None:
        """Call handler with error isolation.

        Args:
            handler: Event handler function.
            event: Event to pass to handler.
        """
        try:
            await handler(event)
        except Exception as e:
            logger.error(
                f"Error in event handler {handler.__name__} for event {event.event_type}",
                exc_info=True
            )
            # Publish error event (avoid infinite loop by not publishing ErrorOccurredEvent here)
            # You can log or record the error separately
```

### 사용 예시

```python
class TradingEngine:
    """Main trading engine that coordinates all components."""

    def __init__(self, event_bus: EventBus):
        """Initialize trading engine.

        Args:
            event_bus: Central event bus.
        """
        self.event_bus = event_bus
        self._setup_event_handlers()

    def _setup_event_handlers(self) -> None:
        """Register event handlers."""
        # Subscribe to market data
        self.event_bus.subscribe(
            "MarketDataReceived",
            self.on_market_data_received
        )

        # Subscribe to order filled
        self.event_bus.subscribe(
            "OrderFilled",
            self.on_order_filled
        )

        # Subscribe to risk alerts
        self.event_bus.subscribe(
            "DailyLossLimitExceeded",
            self.on_daily_loss_limit_exceeded
        )

    async def on_market_data_received(self, event: MarketDataReceivedEvent) -> None:
        """Handle market data event.

        Args:
            event: Market data event.
        """
        logger.info(f"Received market data for {event.stock.stock_code}")

        # Evaluate all strategies
        for strategy in self.active_strategies:
            if strategy.is_enabled():
                # Check buy signal
                if await strategy.evaluate_buy_signal(event.stock):
                    await self._create_buy_order(strategy, event.stock)

    async def on_order_filled(self, event: OrderFilledEvent) -> None:
        """Handle order filled event.

        Args:
            event: Order filled event.
        """
        logger.info(f"Order filled: {event.order.order_id}")

        # Update position
        await self.position_manager.update_position(event.order)

        # Update account balance
        await self.account_manager.update_balance(event.order)

    async def on_daily_loss_limit_exceeded(
        self,
        event: DailyLossLimitExceededEvent
    ) -> None:
        """Handle daily loss limit exceeded.

        Args:
            event: Loss limit event.
        """
        logger.critical("Daily loss limit exceeded! Halting all trading.")

        # Disable all strategies
        for strategy in self.active_strategies:
            strategy.disable()

        # Publish system halt event
        await self.event_bus.publish(
            SystemShutdownEvent(
                source="TradingEngine",
                reason="Daily loss limit exceeded"
            )
        )
```

---

## 이벤트 타입 요약 테이블

| 이벤트 타입 | 발행자 | 주요 구독자 | 설명 |
|-----------|--------|-----------|------|
| `MarketDataReceived` | DataCollector | Strategy, RiskManager | 실시간 시세 수신 |
| `ChartDataLoaded` | DataCollector | Strategy | 차트 데이터 로드 완료 |
| `OrderCreated` | OrderExecutor | Notifier, RiskManager | 주문 생성 |
| `OrderSubmitted` | OrderExecutor | Notifier, Repository | 주문 제출 |
| `OrderFilled` | OrderExecutor | Notifier, PositionManager, Account | 주문 체결 |
| `OrderPartiallyFilled` | OrderExecutor | Notifier, Repository | 부분 체결 |
| `OrderCancelled` | OrderExecutor | Notifier, Strategy | 주문 취소 |
| `OrderRejected` | OrderExecutor | Notifier, Strategy | 주문 거부 |
| `DailyLossLimitExceeded` | RiskManager | TradingEngine, Notifier | 일일 손실 한도 초과 |
| `RiskWarning` | RiskManager | Notifier | 위험 경고 |
| `SystemStarted` | TradingEngine | 모든 컴포넌트 | 시스템 시작 |
| `SystemShutdown` | TradingEngine | 모든 컴포넌트 | 시스템 종료 |
| `MarketPhaseChanged` | MarketHoursMonitor | TradingEngine, Strategy | 시장 상태 변경 |
| `ErrorOccurred` | 모든 컴포넌트 | Notifier, HealthCheck | 에러 발생 |
| `HealthCheckFailed` | HealthCheck | Notifier, TradingEngine | 헬스 체크 실패 |

---

## 베스트 프랙티스

### 1. 이벤트 핸들러 작성 규칙

```python
async def on_event_handler(event: BaseEvent) -> None:
    """Event handler best practices.

    1. Type hint the event parameter correctly
    2. Keep handlers short and focused
    3. Don't block the event loop
    4. Log all important actions
    5. Handle errors gracefully
    """
    try:
        # Type cast to specific event
        if not isinstance(event, ExpectedEventType):
            logger.warning(f"Unexpected event type: {type(event)}")
            return

        # Process event
        logger.info(f"Processing {event.event_type}")

        # Perform action (keep it fast)
        await do_something(event)

    except Exception as e:
        logger.error(f"Error handling {event.event_type}", exc_info=True)
        # Don't re-raise - error isolation
```

### 2. 이벤트 발행 패턴

```python
class Component:
    """Component that publishes events."""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

    async def do_action(self) -> None:
        """Perform action and publish event."""
        # Do work
        result = await perform_task()

        # Create event
        event = SomethingHappenedEvent(
            source=self.__class__.__name__,
            result=result
        )

        # Publish event
        await self.event_bus.publish(event)

        logger.info(f"Published {event.event_type}")
```

### 3. 테스트 지원

```python
class MockEventBus(EventBus):
    """Mock event bus for testing."""

    def __init__(self):
        super().__init__()
        self.published_events: List[BaseEvent] = []

    async def publish(self, event: BaseEvent) -> None:
        """Capture published events for testing."""
        self.published_events.append(event)
        await super().publish(event)

    def get_events_by_type(self, event_type: str) -> List[BaseEvent]:
        """Get all published events of a specific type."""
        return [e for e in self.published_events if e.event_type == event_type]

    def clear(self) -> None:
        """Clear published events."""
        self.published_events.clear()

# 테스트 예시
async def test_order_filled_event():
    """Test that OrderFilledEvent is published when order is filled."""
    event_bus = MockEventBus()
    order_executor = KiwoomOrderExecutor(event_bus=event_bus)

    # Execute order
    order = await order_executor.submit_order(test_order)

    # Verify event published
    events = event_bus.get_events_by_type("OrderFilled")
    assert len(events) == 1
    assert events[0].order.order_id == order.order_id
```

---

## 요약

본 문서는 자동매매 시스템의 이벤트 기반 통신 계약을 정의하였다:

1. **15개 이벤트 타입**: 시장 데이터, 주문, 위험 관리, 시스템 이벤트
2. **Pub/Sub 패턴**: 중앙 EventBus를 통한 느슨한 결합
3. **비동기 처리**: 모든 핸들러는 async 함수
4. **에러 격리**: 핸들러 에러가 다른 핸들러에 영향 없음
5. **멱등성**: 동일 이벤트 중복 처리 안전

다음 문서: [configuration-schema.md](./configuration-schema.md)
