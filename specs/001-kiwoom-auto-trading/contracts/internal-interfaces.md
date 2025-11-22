# 내부 시스템 인터페이스 명세

**Feature Branch**: `001-kiwoom-auto-trading`
**Created**: 2025-11-22
**Status**: Draft
**Related**: [spec.md](../spec.md) | [data-model.md](../data-model.md) | [kiwoom-api.md](./kiwoom-api.md)

## 개요

본 문서는 자동매매 시스템의 내부 컴포넌트 간 인터페이스와 계약을 정의한다. 모든 핵심 인터페이스는 추상 클래스(Abstract Base Class)로 정의되며, 각 구현체는 이 계약을 준수해야 한다.

## 목차

1. [BaseStrategy - 전략 인터페이스](#basestrategy---전략-인터페이스)
2. [DataCollector - 데이터 수집 인터페이스](#datacollector---데이터-수집-인터페이스)
3. [OrderExecutor - 주문 실행 인터페이스](#orderexecutor---주문-실행-인터페이스)
4. [RiskManager - 위험 관리 인터페이스](#riskmanager---위험-관리-인터페이스)
5. [Notifier - 알림 인터페이스](#notifier---알림-인터페이스)
6. [HealthCheck - 헬스 체크 인터페이스](#healthcheck---헬스-체크-인터페이스)
7. [Repository - 저장소 인터페이스](#repository---저장소-인터페이스)

---

## 아키텍처 개요

```
┌─────────────────────────────────────────────────────────┐
│                   Application Layer                     │
│  (전략 실행, 주문 관리, 시스템 모니터링)                   │
└──────────────────┬──────────────────────────────────────┘
                   │
                   │ uses
                   ↓
┌─────────────────────────────────────────────────────────┐
│                  Interface Layer                        │
│  BaseStrategy | DataCollector | OrderExecutor           │
│  RiskManager | Notifier | HealthCheck                   │
└──────────────────┬──────────────────────────────────────┘
                   │
                   │ implements
                   ↓
┌─────────────────────────────────────────────────────────┐
│              Implementation Layer                       │
│  GoldenCrossStrategy | KiwoomDataCollector              │
│  KiwoomOrderExecutor | PositionRiskManager              │
│  DiscordNotifier | SystemHealthCheck                    │
└─────────────────────────────────────────────────────────┘
```

---

## BaseStrategy - 전략 인터페이스

### 목적

모든 매매 전략의 기반이 되는 추상 인터페이스. 전략은 매수/매도 시그널을 평가하고 주문을 생성하는 책임을 가진다.

### 인터페이스 정의

```python
from abc import ABC, abstractmethod
from typing import Optional, List
from decimal import Decimal
from pydantic import BaseModel

class BaseStrategy(ABC):
    """Abstract base class for all trading strategies.

    All concrete strategy implementations must inherit from this class
    and implement the required abstract methods.

    Attributes:
        config: Strategy configuration (StrategyConfig from data-model.md).
        name: Strategy unique name.
        enabled: Whether the strategy is currently active.
    """

    def __init__(self, config: StrategyConfig):
        """Initialize strategy with configuration.

        Args:
            config: Strategy configuration object.
        """
        self.config = config
        self.name = config.strategy_name
        self.enabled = config.enabled

    @abstractmethod
    async def evaluate_buy_signal(self, stock: Stock) -> bool:
        """Evaluate if stock meets buy conditions.

        This method is called for each watched stock during market hours.
        The strategy should analyze the stock data and return True if
        a buy signal is detected.

        Args:
            stock: Current stock data (Stock from data-model.md).

        Returns:
            True if buy signal detected, False otherwise.

        Raises:
            ValueError: If stock data is invalid or incomplete.
        """
        pass

    @abstractmethod
    async def evaluate_sell_signal(
        self,
        position: Position,
        stock: Stock
    ) -> bool:
        """Evaluate if position meets sell conditions.

        This method is called for each active position during market hours.
        The strategy should analyze the position and current stock data
        to determine if a sell signal is present.

        Args:
            position: Current position data (Position from data-model.md).
            stock: Current stock market data.

        Returns:
            True if sell signal detected, False otherwise.

        Raises:
            ValueError: If position or stock data is invalid.
        """
        pass

    @abstractmethod
    async def calculate_position_size(
        self,
        stock: Stock,
        available_capital: Decimal
    ) -> int:
        """Calculate optimal position size for a buy signal.

        Determines how many shares to buy based on available capital,
        risk management rules, and strategy parameters.

        Args:
            stock: Stock to buy.
            available_capital: Available capital for this trade.

        Returns:
            Number of shares to buy (must be > 0).

        Raises:
            ValueError: If available_capital is insufficient.
        """
        pass

    async def on_order_filled(self, order: Order) -> None:
        """Callback when an order is filled.

        Optional callback that strategies can override to react
        to order fills (e.g., adjust internal state, log trades).

        Args:
            order: Filled order (Order from data-model.md).
        """
        pass

    async def on_market_open(self) -> None:
        """Callback when market opens.

        Optional callback called at market open (09:00 KST).
        Strategies can use this to initialize daily state.
        """
        pass

    async def on_market_close(self) -> None:
        """Callback when market closes.

        Optional callback called at market close (15:30 KST).
        Strategies can use this to finalize daily state.
        """
        pass

    def is_enabled(self) -> bool:
        """Check if strategy is currently enabled.

        Returns:
            True if strategy is active.
        """
        return self.enabled

    def enable(self) -> None:
        """Enable the strategy."""
        self.enabled = True

    def disable(self) -> None:
        """Disable the strategy."""
        self.enabled = False
```

### 에러 처리 요구사항

1. **데이터 검증**: 입력 데이터가 유효하지 않으면 `ValueError` 발생
2. **비동기 처리**: 모든 시그널 평가 메서드는 `async` 함수여야 함
3. **예외 전파**: 내부 에러는 상위 레이어로 전파하여 중앙에서 처리

### 구현 예시

```python
class GoldenCrossStrategy(BaseStrategy):
    """Golden Cross trading strategy implementation.

    Buys when short-period SMA crosses above long-period SMA.
    Sells based on stop-loss or take-profit conditions.
    """

    def __init__(self, config: StrategyConfig):
        """Initialize golden cross strategy.

        Args:
            config: Strategy configuration.
        """
        super().__init__(config)

        # Extract strategy-specific parameters
        self.short_period = config.parameters.get("short_period", 5)
        self.long_period = config.parameters.get("long_period", 20)
        self.stop_loss_pct = Decimal(str(config.parameters.get("stop_loss_pct", 0.03)))
        self.take_profit_pct = Decimal(str(config.parameters.get("take_profit_pct", 0.05)))

    async def evaluate_buy_signal(self, stock: Stock) -> bool:
        """Evaluate buy signal based on golden cross.

        Args:
            stock: Current stock data.

        Returns:
            True if golden cross detected.
        """
        # Fetch historical data to calculate SMAs
        chart_data = await self._get_chart_data(stock.stock_code, self.long_period)

        if len(chart_data) < self.long_period:
            return False

        # Calculate SMAs
        sma_short = self._calculate_sma(chart_data, self.short_period)
        sma_long = self._calculate_sma(chart_data, self.long_period)

        # Check for golden cross (short crosses above long)
        prev_sma_short = self._calculate_sma(chart_data[:-1], self.short_period)
        prev_sma_long = self._calculate_sma(chart_data[:-1], self.long_period)

        return (prev_sma_short <= prev_sma_long and sma_short > sma_long)

    async def evaluate_sell_signal(
        self,
        position: Position,
        stock: Stock
    ) -> bool:
        """Evaluate sell signal based on stop-loss or take-profit.

        Args:
            position: Current position.
            stock: Current stock data.

        Returns:
            True if sell condition met.
        """
        return_rate = position.return_rate

        # Stop-loss condition
        if return_rate <= -self.stop_loss_pct:
            return True

        # Take-profit condition
        if return_rate >= self.take_profit_pct:
            return True

        return False

    async def calculate_position_size(
        self,
        stock: Stock,
        available_capital: Decimal
    ) -> int:
        """Calculate position size (fixed percentage of capital).

        Args:
            stock: Stock to buy.
            available_capital: Available capital.

        Returns:
            Number of shares to buy.
        """
        # Use 10% of available capital per position
        position_capital = available_capital * Decimal("0.1")
        quantity = int(position_capital / stock.current_price)

        if quantity < 1:
            raise ValueError("Insufficient capital for minimum position")

        return quantity
```

---

## DataCollector - 데이터 수집 인터페이스

### 목적

실시간 시세 데이터 및 과거 차트 데이터를 수집하고 캐싱하는 인터페이스.

### 인터페이스 정의

```python
from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime

class DataCollector(ABC):
    """Abstract interface for market data collection.

    Responsible for collecting real-time price data, historical chart data,
    and managing data caching.
    """

    @abstractmethod
    async def get_current_price(self, stock_code: str) -> Stock:
        """Get current price for a stock.

        Args:
            stock_code: 6-digit stock code.

        Returns:
            Current stock data.

        Raises:
            ValueError: If stock code is invalid.
            ConnectionError: If API connection fails.
        """
        pass

    @abstractmethod
    async def get_current_prices(self, stock_codes: List[str]) -> List[Stock]:
        """Get current prices for multiple stocks.

        Args:
            stock_codes: List of stock codes.

        Returns:
            List of current stock data.

        Raises:
            ValueError: If any stock code is invalid.
            ConnectionError: If API connection fails.
        """
        pass

    @abstractmethod
    async def get_chart_data(
        self,
        stock_code: str,
        interval: ChartInterval,
        count: int = 100
    ) -> List[ChartData]:
        """Get historical chart data.

        Args:
            stock_code: 6-digit stock code.
            interval: Chart interval (DAY, MIN_5, etc.).
            count: Number of candles to retrieve (max 500).

        Returns:
            List of chart data (OHLCV), sorted by timestamp ascending.

        Raises:
            ValueError: If parameters are invalid.
            ConnectionError: If API connection fails.
        """
        pass

    @abstractmethod
    async def subscribe_realtime(
        self,
        stock_code: str,
        callback: callable
    ) -> None:
        """Subscribe to real-time price updates.

        Registers a callback function to be called whenever
        new price data arrives for the specified stock.

        Args:
            stock_code: Stock code to subscribe.
            callback: Async function to call on updates.
                     Signature: async def callback(stock: Stock) -> None

        Raises:
            ValueError: If stock code is invalid.
        """
        pass

    @abstractmethod
    async def unsubscribe_realtime(self, stock_code: str) -> None:
        """Unsubscribe from real-time price updates.

        Args:
            stock_code: Stock code to unsubscribe.
        """
        pass

    @abstractmethod
    async def start(self) -> None:
        """Start data collection service.

        Initializes API connection and begins collecting data.

        Raises:
            ConnectionError: If API connection fails.
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop data collection service.

        Closes API connection and cleans up resources.
        """
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if data collector is connected to API.

        Returns:
            True if connected and operational.
        """
        pass
```

### 에러 처리 요구사항

1. **재시도 로직**: 네트워크 오류 시 최대 3회 재시도
2. **타임아웃**: 모든 API 호출에 30초 타임아웃 적용
3. **캐싱**: 동일 종목의 중복 요청은 캐시에서 반환 (5초 이내)

### 구현 예시

```python
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Callable

class KiwoomDataCollector(DataCollector):
    """Kiwoom API data collector implementation."""

    def __init__(self, api_client: KiwoomAPIClient):
        """Initialize data collector.

        Args:
            api_client: Kiwoom API client instance.
        """
        self.api_client = api_client
        self.cache: Dict[str, tuple[Stock, datetime]] = {}
        self.cache_ttl = timedelta(seconds=5)
        self.realtime_subscriptions: Dict[str, List[Callable]] = {}
        self._running = False

    async def get_current_price(self, stock_code: str) -> Stock:
        """Get current price with caching.

        Args:
            stock_code: Stock code.

        Returns:
            Current stock data.
        """
        # Check cache
        if stock_code in self.cache:
            cached_stock, cached_time = self.cache[stock_code]
            if datetime.now() - cached_time < self.cache_ttl:
                return cached_stock

        # Fetch from API
        stock_data = await self.api_client.get_current_price(stock_code)

        # Update cache
        stock = Stock(**stock_data)
        self.cache[stock_code] = (stock, datetime.now())

        return stock

    async def get_current_prices(self, stock_codes: List[str]) -> List[Stock]:
        """Get current prices for multiple stocks concurrently.

        Args:
            stock_codes: List of stock codes.

        Returns:
            List of stock data.
        """
        tasks = [self.get_current_price(code) for code in stock_codes]
        return await asyncio.gather(*tasks)

    async def subscribe_realtime(
        self,
        stock_code: str,
        callback: Callable
    ) -> None:
        """Subscribe to real-time updates.

        Args:
            stock_code: Stock code.
            callback: Callback function.
        """
        if stock_code not in self.realtime_subscriptions:
            self.realtime_subscriptions[stock_code] = []

        self.realtime_subscriptions[stock_code].append(callback)

    async def start(self) -> None:
        """Start data collection."""
        await self.api_client.connect()
        self._running = True

    def is_connected(self) -> bool:
        """Check connection status."""
        return self._running and self.api_client.is_connected()
```

---

## OrderExecutor - 주문 실행 인터페이스

### 목적

주문 생성, 제출, 상태 추적을 담당하는 인터페이스.

### 인터페이스 정의

```python
from abc import ABC, abstractmethod
from typing import Optional, List

class OrderExecutor(ABC):
    """Abstract interface for order execution.

    Responsible for creating, submitting, and tracking orders.
    """

    @abstractmethod
    async def place_buy_order(
        self,
        account_number: str,
        stock_code: str,
        quantity: int,
        price_type: PriceType,
        limit_price: Optional[Decimal] = None,
        strategy_name: Optional[str] = None
    ) -> Order:
        """Place a buy order.

        Args:
            account_number: Account number.
            stock_code: Stock code to buy.
            quantity: Number of shares.
            price_type: MARKET or LIMIT.
            limit_price: Price for LIMIT orders.
            strategy_name: Name of strategy placing order.

        Returns:
            Created order object with status PENDING.

        Raises:
            ValueError: If order validation fails.
        """
        pass

    @abstractmethod
    async def place_sell_order(
        self,
        account_number: str,
        stock_code: str,
        quantity: int,
        price_type: PriceType,
        limit_price: Optional[Decimal] = None,
        strategy_name: Optional[str] = None
    ) -> Order:
        """Place a sell order.

        Args:
            account_number: Account number.
            stock_code: Stock code to sell.
            quantity: Number of shares.
            price_type: MARKET or LIMIT.
            limit_price: Price for LIMIT orders.
            strategy_name: Name of strategy placing order.

        Returns:
            Created order object with status PENDING.

        Raises:
            ValueError: If order validation fails.
        """
        pass

    @abstractmethod
    async def submit_order(self, order: Order) -> Order:
        """Submit order to broker API.

        Changes order status from PENDING to SUBMITTED.

        Args:
            order: Order to submit.

        Returns:
            Updated order with SUBMITTED status and order_id from broker.

        Raises:
            ConnectionError: If API connection fails.
            ValueError: If order is rejected by broker.
        """
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> Order:
        """Cancel a pending order.

        Args:
            order_id: Order ID to cancel.

        Returns:
            Updated order with CANCELLED status.

        Raises:
            ValueError: If order cannot be cancelled (already filled, etc.).
        """
        pass

    @abstractmethod
    async def get_order_status(self, order_id: str) -> Order:
        """Get current order status.

        Args:
            order_id: Order ID to query.

        Returns:
            Current order state.

        Raises:
            ValueError: If order_id not found.
        """
        pass

    @abstractmethod
    async def get_pending_orders(
        self,
        account_number: str
    ) -> List[Order]:
        """Get all pending orders for an account.

        Returns orders with status PENDING, SUBMITTED, or PARTIALLY_FILLED.

        Args:
            account_number: Account number.

        Returns:
            List of pending orders.
        """
        pass

    @abstractmethod
    async def update_order_status(self, order: Order) -> Order:
        """Update order status from broker.

        Polls broker API to get latest order status and updates
        the order object.

        Args:
            order: Order to update.

        Returns:
            Updated order object.
        """
        pass
```

### 에러 처리 요구사항

1. **검증**: 주문 제출 전 예수금, 수량, 가격 검증 필수
2. **중복 방지**: 동일 종목 중복 주문 방지 로직 구현
3. **재시도**: API 호출 실패 시 최대 2회 재시도

### 구현 예시

```python
class KiwoomOrderExecutor(OrderExecutor):
    """Kiwoom API order executor implementation."""

    def __init__(
        self,
        api_client: KiwoomAPIClient,
        validator: OrderValidator,
        duplicate_checker: DuplicateOrderChecker
    ):
        """Initialize order executor.

        Args:
            api_client: Kiwoom API client.
            validator: Order validator.
            duplicate_checker: Duplicate order checker.
        """
        self.api_client = api_client
        self.validator = validator
        self.duplicate_checker = duplicate_checker

    async def place_buy_order(
        self,
        account_number: str,
        stock_code: str,
        quantity: int,
        price_type: PriceType,
        limit_price: Optional[Decimal] = None,
        strategy_name: Optional[str] = None
    ) -> Order:
        """Place a buy order with validation.

        Args:
            account_number: Account number.
            stock_code: Stock code.
            quantity: Order quantity.
            price_type: MARKET or LIMIT.
            limit_price: Limit price if applicable.
            strategy_name: Strategy name.

        Returns:
            Created order.

        Raises:
            ValueError: If validation fails.
        """
        # Create order object
        order = Order(
            account_number=account_number,
            stock_code=stock_code,
            order_type=OrderType.BUY,
            price_type=price_type,
            quantity=quantity,
            limit_price=limit_price,
            strategy_name=strategy_name,
            status=OrderStatus.PENDING
        )

        # Validate order
        account = await self._get_account(account_number)
        current_price = await self._get_current_price(stock_code)

        is_valid, error_msg = self.validator.validate_buy_order(
            account,
            order,
            current_price
        )

        if not is_valid:
            raise ValueError(f"Order validation failed: {error_msg}")

        # Check duplicate
        is_duplicate, existing_order_id = self.duplicate_checker.check_duplicate(
            stock_code,
            OrderType.BUY
        )

        if is_duplicate:
            raise ValueError(f"Duplicate order detected: {existing_order_id}")

        return order

    async def submit_order(self, order: Order) -> Order:
        """Submit order to Kiwoom API.

        Args:
            order: Order to submit.

        Returns:
            Updated order with broker order_id.
        """
        # Submit to API
        if order.order_type == OrderType.BUY:
            response = await self.api_client.place_buy_order(
                OrderRequest(
                    account_number=order.account_number,
                    stock_code=order.stock_code,
                    price_type=order.price_type.value,
                    price=str(order.limit_price) if order.limit_price else None,
                    quantity=order.quantity
                )
            )
        else:
            response = await self.api_client.place_sell_order(...)

        # Update order with broker response
        order.order_id = response["order_id"]
        order.status = OrderStatus.SUBMITTED
        order.submitted_at = datetime.now(tz=KST)

        return order
```

---

## RiskManager - 위험 관리 인터페이스

### 목적

계좌 위험 관리, 손실 한도 모니터링, 포지션 집중도 관리.

### 인터페이스 정의

```python
from abc import ABC, abstractmethod
from typing import Tuple, Optional

class RiskManager(ABC):
    """Abstract interface for risk management.

    Responsible for monitoring and enforcing risk limits.
    """

    @abstractmethod
    async def check_daily_loss_limit(
        self,
        account: Account
    ) -> Tuple[bool, Optional[str]]:
        """Check if daily loss limit has been exceeded.

        Args:
            account: Account to check.

        Returns:
            Tuple of (is_exceeded, warning_message).
            is_exceeded is True if limit exceeded.
            warning_message contains details if applicable.
        """
        pass

    @abstractmethod
    async def check_position_risk(
        self,
        position: Position,
        account: Account
    ) -> Tuple[bool, Optional[str]]:
        """Check if position exceeds risk limits.

        Checks position concentration (max % of portfolio),
        stop-loss levels, etc.

        Args:
            position: Position to check.
            account: Account information.

        Returns:
            Tuple of (is_risky, warning_message).
        """
        pass

    @abstractmethod
    async def should_stop_trading(
        self,
        account: Account
    ) -> Tuple[bool, Optional[str]]:
        """Determine if trading should be halted.

        Args:
            account: Account to evaluate.

        Returns:
            Tuple of (should_stop, reason).
            should_stop is True if trading must be halted.
        """
        pass

    @abstractmethod
    async def calculate_max_position_size(
        self,
        stock_code: str,
        account: Account,
        strategy_capital_allocation: Decimal
    ) -> int:
        """Calculate maximum allowed position size.

        Considers available capital, portfolio concentration limits,
        and strategy allocation.

        Args:
            stock_code: Stock to buy.
            account: Account information.
            strategy_capital_allocation: Capital allocated to strategy.

        Returns:
            Maximum number of shares allowed.
        """
        pass

    @abstractmethod
    async def validate_order_risk(
        self,
        order: Order,
        account: Account,
        positions: List[Position]
    ) -> Tuple[bool, Optional[str]]:
        """Validate order against risk rules before execution.

        Args:
            order: Order to validate.
            account: Account information.
            positions: Current positions.

        Returns:
            Tuple of (is_valid, rejection_reason).
        """
        pass
```

### 에러 처리 요구사항

1. **즉시 차단**: 위험 한도 초과 시 즉시 거래 중단
2. **경고 알림**: 80% 한도 도달 시 경고 알림 발송
3. **로깅**: 모든 위험 이벤트 로그 기록

### 구현 예시

```python
class PositionRiskManager(RiskManager):
    """Position-based risk manager implementation."""

    def __init__(
        self,
        max_daily_loss_rate: Decimal = Decimal("0.05"),
        max_position_concentration: Decimal = Decimal("0.30")
    ):
        """Initialize risk manager.

        Args:
            max_daily_loss_rate: Max daily loss as % of account (default 5%).
            max_position_concentration: Max position size as % of portfolio (default 30%).
        """
        self.max_daily_loss_rate = max_daily_loss_rate
        self.max_position_concentration = max_position_concentration

    async def check_daily_loss_limit(
        self,
        account: Account
    ) -> Tuple[bool, Optional[str]]:
        """Check daily loss limit.

        Args:
            account: Account to check.

        Returns:
            (is_exceeded, message) tuple.
        """
        daily_loss_limit = account.total_asset_value * self.max_daily_loss_rate

        # Check if limit exceeded
        if account.daily_pnl < -daily_loss_limit:
            return (
                True,
                f"Daily loss limit exceeded: {account.daily_pnl} < -{daily_loss_limit}"
            )

        # Check if approaching limit (80%)
        if account.daily_pnl < -(daily_loss_limit * Decimal("0.8")):
            return (
                False,
                f"Warning: Daily loss at 80% of limit: {account.daily_pnl}"
            )

        return (False, None)

    async def should_stop_trading(
        self,
        account: Account
    ) -> Tuple[bool, Optional[str]]:
        """Determine if trading should stop.

        Args:
            account: Account to evaluate.

        Returns:
            (should_stop, reason) tuple.
        """
        # Check daily loss limit
        is_exceeded, msg = await self.check_daily_loss_limit(account)

        if is_exceeded:
            return (True, f"HALT: {msg}")

        return (False, None)
```

---

## Notifier - 알림 인터페이스

### 목적

사용자에게 알림을 전송하는 인터페이스 (Discord, Email 등).

### 인터페이스 정의

```python
from abc import ABC, abstractmethod

class Notifier(ABC):
    """Abstract interface for sending notifications.

    Supports multiple channels (Discord, Email, etc.).
    """

    @abstractmethod
    async def send_order_notification(
        self,
        order: Order,
        stock_name: str
    ) -> None:
        """Send order filled notification.

        Args:
            order: Filled order.
            stock_name: Stock name for display.

        Raises:
            ConnectionError: If notification service unavailable.
        """
        pass

    @abstractmethod
    async def send_error_notification(
        self,
        error_message: str,
        severity: str = "ERROR"
    ) -> None:
        """Send error notification.

        Args:
            error_message: Error details.
            severity: ERROR, WARNING, or CRITICAL.
        """
        pass

    @abstractmethod
    async def send_daily_report(
        self,
        account: Account,
        orders: List[Order],
        positions: List[Position]
    ) -> None:
        """Send daily trading summary.

        Args:
            account: Account data.
            orders: Today's orders.
            positions: Current positions.
        """
        pass

    @abstractmethod
    async def send_risk_alert(
        self,
        alert_type: str,
        message: str
    ) -> None:
        """Send risk management alert.

        Args:
            alert_type: Type of alert (LOSS_LIMIT, POSITION_RISK, etc.).
            message: Alert details.
        """
        pass
```

### 구현 예시

```python
class DiscordNotifier(Notifier):
    """Discord webhook notifier implementation."""

    def __init__(self, webhook_url: str):
        """Initialize Discord notifier.

        Args:
            webhook_url: Discord webhook URL.
        """
        self.webhook_url = webhook_url

    async def send_order_notification(
        self,
        order: Order,
        stock_name: str
    ) -> None:
        """Send order notification to Discord.

        Args:
            order: Filled order.
            stock_name: Stock name.
        """
        order_type_kr = "매수" if order.order_type == OrderType.BUY else "매도"

        embed = {
            "title": f"{order_type_kr} 주문 체결",
            "description": f"{stock_name} ({order.stock_code})",
            "color": 0x00FF00 if order.order_type == OrderType.BUY else 0xFF0000,
            "fields": [
                {"name": "수량", "value": f"{order.filled_quantity}주", "inline": True},
                {"name": "체결가", "value": f"{order.filled_price:,}원", "inline": True},
                {"name": "총액", "value": f"{order.calculate_total_cost():,}원", "inline": False}
            ],
            "timestamp": order.filled_at.isoformat()
        }

        async with httpx.AsyncClient() as client:
            await client.post(
                self.webhook_url,
                json={"embeds": [embed]}
            )
```

---

## HealthCheck - 헬스 체크 인터페이스

### 목적

시스템 상태를 모니터링하고 이상 징후를 감지.

### 인터페이스 정의

```python
from abc import ABC, abstractmethod
from typing import Dict, Any

class HealthCheck(ABC):
    """Abstract interface for system health monitoring."""

    @abstractmethod
    async def check_api_connection(self) -> Tuple[bool, Optional[str]]:
        """Check if API connection is healthy.

        Returns:
            Tuple of (is_healthy, error_message).
        """
        pass

    @abstractmethod
    async def check_data_freshness(self) -> Tuple[bool, Optional[str]]:
        """Check if market data is being received.

        Returns:
            Tuple of (is_fresh, warning_message).
            is_fresh is False if no data received in last 3 minutes.
        """
        pass

    @abstractmethod
    async def check_system_resources(self) -> Tuple[bool, Optional[str]]:
        """Check system resources (memory, CPU).

        Returns:
            Tuple of (is_healthy, warning_message).
        """
        pass

    @abstractmethod
    async def run_health_check(self) -> Dict[str, Any]:
        """Run full health check.

        Returns:
            Dict with health status for each component.

        Example:
            {
                "status": "healthy",
                "api_connection": {"status": "ok"},
                "data_freshness": {"status": "ok", "last_update": "..."},
                "system_resources": {"status": "ok", "memory_usage": "45%"}
            }
        """
        pass
```

---

## Repository - 저장소 인터페이스

### 목적

데이터 영속성 계층 추상화.

### 인터페이스 정의

```python
from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime

class OrderRepository(ABC):
    """Abstract repository for Order persistence."""

    @abstractmethod
    async def save(self, order: Order) -> None:
        """Save or update an order.

        Args:
            order: Order to save.
        """
        pass

    @abstractmethod
    async def get_by_id(self, order_id: str) -> Optional[Order]:
        """Get order by ID.

        Args:
            order_id: Order ID.

        Returns:
            Order if found, None otherwise.
        """
        pass

    @abstractmethod
    async def get_pending_orders(
        self,
        account_number: str
    ) -> List[Order]:
        """Get all pending orders.

        Args:
            account_number: Account number.

        Returns:
            List of orders with non-terminal status.
        """
        pass

class PositionRepository(ABC):
    """Abstract repository for Position persistence."""

    @abstractmethod
    async def save(self, position: Position) -> None:
        """Save or update a position."""
        pass

    @abstractmethod
    async def get_by_stock(
        self,
        account_number: str,
        stock_code: str
    ) -> Optional[Position]:
        """Get position by stock code."""
        pass

    @abstractmethod
    async def get_all(self, account_number: str) -> List[Position]:
        """Get all positions for an account."""
        pass
```

---

## 요약

본 문서는 자동매매 시스템의 핵심 내부 인터페이스를 정의하였다:

1. **BaseStrategy**: 모든 매매 전략의 기반 인터페이스
2. **DataCollector**: 시세 데이터 수집 및 캐싱
3. **OrderExecutor**: 주문 생성 및 실행
4. **RiskManager**: 위험 관리 및 한도 모니터링
5. **Notifier**: 사용자 알림 전송
6. **HealthCheck**: 시스템 상태 모니터링
7. **Repository**: 데이터 영속성 추상화

모든 구현체는 이 인터페이스 계약을 준수해야 하며, 에러 처리 요구사항을 따라야 한다.

다음 문서: [events.md](./events.md)
