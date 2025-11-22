# Research Report: Kiwoom Securities Auto-Trading System

**Date**: 2025-11-22
**Branch**: `001-kiwoom-auto-trading`
**Related**: [plan.md](./plan.md) | [spec.md](./spec.md)

## Research Objectives

This research addresses the "NEEDS CLARIFICATION" items identified in plan.md:

1. Kiwoom Securities REST API Rate Limits and Constraints
2. Real-time Data Receiving Method (WebSocket vs REST Polling)
3. Strategy Definition Best Practices (Python vs YAML/DSL)
4. Notification Libraries for Python (Discord, Email)
5. Python Async Trading System Architecture

---

## 1. Kiwoom Securities REST API Rate Limits and Constraints

### Decision

**Adopt conservative rate limiting approach**: Implement client-side throttling at **15 requests/second** with token bucket algorithm using `asyncio.Semaphore`.

### Rationale

1. **Limited Official Documentation**: Kiwoom Securities REST API (launched March 2025) does not publicly document specific rate limits. The official site (https://openapi.kiwoom.com/) requires registration to access detailed documentation.

2. **Industry Comparison**: Korea Investment Securities (a comparable platform) has documented limits:
   - Individual accounts: 10 requests/second
   - Corporate accounts: 20 requests/second
   - Uses sliding window rate limiting

3. **Conservative Approach**: Without official documentation, setting a 15 req/sec limit provides safety margin while allowing adequate data collection for 50+ concurrent stocks.

### Implementation Strategy

```python
import asyncio
from collections import deque
from time import time

class TokenBucketRateLimiter:
    """Token bucket rate limiter for API throttling"""

    def __init__(self, rate: int = 15, period: float = 1.0):
        self.rate = rate
        self.period = period
        self.semaphore = asyncio.BoundedSemaphore(rate)
        self._tokens = deque()

    async def acquire(self):
        """Acquire permission to make API call"""
        async with self.semaphore:
            now = time()
            # Remove expired tokens
            while self._tokens and self._tokens[0] < now - self.period:
                self._tokens.popleft()

            # Wait if at rate limit
            if len(self._tokens) >= self.rate:
                sleep_time = self.period - (now - self._tokens[0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

            self._tokens.append(time())
```

### Best Practices for Handling API Limits

1. **Exponential Backoff**: Implement retry logic with exponential backoff (1s, 2s, 4s) on 429 errors
2. **Request Prioritization**: Prioritize order execution over data collection when approaching limits
3. **Monitoring**: Log rate limit hits and adjust client-side throttling dynamically
4. **Batch Operations**: Group related requests where API supports it
5. **Caching**: Cache static data (stock info, daily OHLCV) to reduce redundant API calls

### Alternatives Considered

| Approach | Pros | Cons | Rejected Reason |
|----------|------|------|-----------------|
| No rate limiting | Simplest implementation | Risk of API blocking, service disruption | Too risky for production trading |
| Simple semaphore (concurrent limit) | Easy to implement | Doesn't prevent burst requests | Doesn't model actual rate limits |
| **Token bucket (chosen)** | Models real-world limits, smooth traffic | More complex | Best balance for production |
| Third-party library (aiometer) | Battle-tested | External dependency | Token bucket is simple enough to implement |

### Known Constraints

- **API Registration Required**: Access to full API documentation requires account registration at openapi.kiwoom.com
- **AI Assistant Limit**: Kiwoom's AI Coding Assistant has a 30 conversations/day limit (unrelated to API calls)
- **Server Load Warning**: Kiwoom warns that "abnormal data queries may result in connections being arbitrarily blocked"
- **Algorithm Account Registration**: Heavy API usage may trigger registration as an algorithmic trading account with Korea Exchange

### Action Items

- [ ] Register for Kiwoom REST API and review official rate limit documentation
- [ ] Implement initial 15 req/sec throttling with monitoring
- [ ] Adjust limits based on actual API responses and error rates during testing
- [ ] Contact Kiwoom support for official rate limit specifications

---

## 2. Real-time Data Receiving Method

### Decision

**Use REST API polling with adaptive intervals**:
- **Default**: 1-second intervals for active trading hours
- **Pre-market/After-hours**: 5-second intervals
- **Prepare for WebSocket migration** when/if Kiwoom adds support

### Rationale

1. **No Native WebSocket Support**: Search results and community projects (GitHub) show no evidence of Kiwoom REST API supporting WebSocket as of 2025. The traditional Kiwoom OpenAPI+ (OCX-based) has real-time capabilities, but the REST API appears limited to polling.

2. **REST Polling Viability**: For 50 stocks at 1-second intervals = 50 requests/second, which exceeds our 15 req/sec budget. Solution: **Stagger requests** across the 1-second window.

3. **Industry Standard**: Other trading platforms show:
   - **WebSocket**: Preferred for <100ms latency (Alpaca, Polygon.io, EODHD)
   - **REST Polling**: Acceptable for 1-5 second update intervals for retail algo trading

4. **Kiwoom OpenAPI+ Alternative**: Traditional OpenAPI+ (PyQt5/OCX) offers real-time data but:
   - Windows-only (limits server deployment options)
   - More complex integration (requires event loop compatibility with asyncio)
   - Steeper learning curve

### Implementation Strategy

```python
import asyncio
from typing import List

class StaggeredPricePoller:
    """Polls multiple stocks with staggered timing to distribute API load"""

    def __init__(self, stocks: List[str], interval: float = 1.0, rate_limiter=None):
        self.stocks = stocks
        self.interval = interval
        self.rate_limiter = rate_limiter
        self.tasks = []

    async def poll_stock(self, stock_code: str, delay: float):
        """Poll single stock with initial delay for staggering"""
        await asyncio.sleep(delay)

        while True:
            try:
                if self.rate_limiter:
                    await self.rate_limiter.acquire()

                # Fetch price data from API
                data = await self.fetch_price(stock_code)
                await self.process_data(stock_code, data)

            except Exception as e:
                logger.error(f"Error polling {stock_code}: {e}")

            await asyncio.sleep(self.interval)

    async def start(self):
        """Start polling all stocks with staggered delays"""
        stagger_delay = self.interval / len(self.stocks)

        for idx, stock in enumerate(self.stocks):
            delay = idx * stagger_delay
            task = asyncio.create_task(self.poll_stock(stock, delay))
            self.tasks.append(task)
```

### Adaptive Polling Intervals

| Market Phase | Interval | Rationale |
|--------------|----------|-----------|
| Pre-market (08:00-09:00) | 5 seconds | Lower volatility, conserve API quota |
| Active trading (09:00-15:20) | 1 second | Critical decision window |
| Near-close (15:20-15:30) | 1 second | High volatility, position management |
| After-hours (15:30+) | 5 seconds | Monitoring only, no new positions |

### WebSocket Migration Plan

If Kiwoom adds WebSocket support in future:

1. **Abstraction Layer**: Design `DataStream` interface that both REST poller and WebSocket client can implement
2. **Feature Detection**: Check API capabilities at startup
3. **Fallback Logic**: Use WebSocket if available, fall back to REST polling
4. **Zero Downtime**: Hot-swap data source without restarting strategy engine

### Best Practices

1. **Connection Pooling**: Reuse `aiohttp.ClientSession` across requests
2. **Timeout Handling**: Set aggressive timeouts (3-5 seconds) to detect stale connections
3. **Data Validation**: Verify timestamps on received data to detect delayed/stale quotes
4. **Heartbeat Monitoring**: If no data received for 3 minutes during market hours, trigger reconnection
5. **Graceful Degradation**: If data for specific stock fails repeatedly, remove from active monitoring and alert user

### Alternatives Considered

| Approach | Pros | Cons | Decision |
|----------|------|------|----------|
| **REST Polling (chosen)** | Works with current API, predictable load | Higher latency (1s), more API calls | Best option given current constraints |
| WebSocket (if available) | Low latency (<100ms), efficient | Not currently supported by Kiwoom REST API | Monitor for future availability |
| Kiwoom OpenAPI+ (OCX) | Real-time data, official support | Windows-only, complex integration | Not suitable for Linux server deployment |
| Hybrid (OpenAPI+ data + REST orders) | Best of both worlds | Architectural complexity, two API integrations | Overly complex for initial version |

### Action Items

- [ ] Confirm WebSocket support status by reviewing official Kiwoom REST API documentation
- [ ] Implement staggered REST polling as primary data collection method
- [ ] Monitor average data lag (API request time + processing)
- [ ] Design `DataStream` abstraction for future WebSocket migration
- [ ] Test polling performance with 50 stocks under rate limit constraints

---

## 3. Strategy Definition Best Practices

### Decision

**Hybrid Approach**:
- **Core strategy logic in Python** (entry/exit conditions, calculations)
- **Configuration in YAML** (stock lists, parameters, risk limits, capital allocation)

### Rationale

1. **Industry Trends (2025)**: Python-based trading systems increasingly adopt YAML for configuration while keeping strategy logic in code:
   - **Wolfinch**: Strategy modules in Python, portfolio config in YAML
   - **Trading Strategy API**: Python strategies with parameter configurations
   - **Hummingbot**: Configuration module supports both code and declarative configs

2. **Flexibility vs Safety Trade-off**:
   - **Pure Python**: Maximum flexibility, but harder for non-programmers to customize
   - **Pure YAML/DSL**: Easy parameter tweaking, but limits complex logic (multi-condition strategies, dynamic risk management)
   - **Hybrid**: Best of both worlds

3. **Real-World Example (2025 Bot Boilerplate)**:
   ```yaml
   # config.yaml - What users modify frequently
   trading:
     symbols: [NVDA, TSLA, SMCI, PLTR]
     position_size: 1000
     stop_loss_multiplier: 0.99
     take_profit_multiplier: 1.03

   strategies:
     - name: golden-cross
       module: strategies.golden_cross
       params:
         short_period: 5
         long_period: 20
         volume_threshold: 1000000
   ```

   ```python
   # strategies/golden_cross.py - What developers write
   from strategies.base import BaseStrategy

   class GoldenCrossStrategy(BaseStrategy):
       def __init__(self, short_period: int, long_period: int, volume_threshold: int):
           self.short_period = short_period
           self.long_period = long_period
           self.volume_threshold = volume_threshold

       async def evaluate_buy_signal(self, stock: Stock) -> bool:
           """Core logic remains in Python for type safety and debugging"""
           sma_short = stock.get_sma(self.short_period)
           sma_long = stock.get_sma(self.long_period)

           return (
               sma_short > sma_long and
               stock.prev_sma_short <= stock.prev_sma_long and
               stock.volume > self.volume_threshold
           )
   ```

### What Goes in YAML vs Python

| Aspect | YAML Config | Python Code | Rationale |
|--------|-------------|-------------|-----------|
| Stock symbols | Yes | No | Changes frequently, no code needed |
| Position sizing | Yes | No | Risk management parameters |
| Stop loss % | Yes | No | User-specific risk tolerance |
| Entry/exit logic | No | Yes | Complex conditions need code |
| Technical indicators | No | Yes | Calculations require libraries (pandas, ta-lib) |
| Multi-condition rules | No | Yes | Type safety, debugging, unit tests |
| Capital allocation | Yes | No | Per-strategy budget limits |
| Trading hours | Yes | No | Market-specific configurations |

### Implementation Architecture

```python
# models/strategy.py
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Dict, Any

class StrategyConfig(BaseModel):
    """Pydantic model for YAML validation"""
    name: str
    module: str
    enabled: bool = True
    capital_allocation: Decimal
    max_positions: int
    params: Dict[str, Any]

class BaseStrategy(ABC):
    """Abstract base class all strategies must inherit"""

    def __init__(self, config: StrategyConfig):
        self.config = config
        self.params = config.params

    @abstractmethod
    async def evaluate_buy_signal(self, stock: Stock) -> bool:
        """Subclasses implement specific logic"""
        pass

    @abstractmethod
    async def evaluate_sell_signal(self, position: Position) -> bool:
        """Subclasses implement specific logic"""
        pass
```

```yaml
# config/strategies.yaml
strategies:
  - name: "Golden Cross Strategy"
    module: "strategies.golden_cross.GoldenCrossStrategy"
    enabled: true
    capital_allocation: 5000000  # 5 million KRW
    max_positions: 10
    stocks:
      - "005930"  # Samsung
      - "000660"  # SK Hynix
    params:
      short_period: 5
      long_period: 20
      min_volume: 1000000
      stop_loss_pct: 0.03
      take_profit_pct: 0.05

  - name: "Scalping Strategy"
    module: "strategies.scalping.ScalpingStrategy"
    enabled: false  # Easily enable/disable
    capital_allocation: 3000000
    max_positions: 5
    stocks:
      - "035720"  # Kakao
    params:
      tick_threshold: 5
      hold_time_seconds: 300
```

### Strategy Loading System

```python
# services/strategy_engine.py
import importlib
import yaml
from pathlib import Path

class StrategyEngine:
    """Loads and executes strategies based on YAML config"""

    async def load_strategies(self, config_path: Path) -> List[BaseStrategy]:
        """Dynamically load strategy modules from config"""
        with open(config_path) as f:
            config_data = yaml.safe_load(f)

        strategies = []
        for strategy_config in config_data['strategies']:
            # Validate with Pydantic
            config = StrategyConfig(**strategy_config)

            if not config.enabled:
                continue

            # Dynamic import
            module_path, class_name = config.module.rsplit('.', 1)
            module = importlib.import_module(module_path)
            strategy_class = getattr(module, class_name)

            # Instantiate with config
            strategy = strategy_class(config)
            strategies.append(strategy)

        return strategies
```

### Benefits of This Approach

1. **Type Safety**: Python code with type hints catches errors at development time
2. **Easy Customization**: Non-programmers can modify stock lists, parameters via YAML
3. **Version Control**: YAML configs are git-friendly, easy to diff and review
4. **Testing**: Python strategies are unit-testable with mocks
5. **Hot Reload**: Can reload YAML configs without restarting (Python code requires restart)
6. **Documentation**: Docstrings in Python explain strategy logic, YAML comments explain parameters

### Alternatives Considered

| Approach | Pros | Cons | Decision |
|----------|------|------|----------|
| Pure Python | Max flexibility, type safety | Hard for non-devs to customize | Too rigid |
| Pure YAML/DSL | Very user-friendly | Limited to simple strategies, no complex logic | Too limiting |
| **Hybrid (chosen)** | Balance of power and usability | Requires discipline in what goes where | Best for production |
| GUI Strategy Builder | No coding needed | Complex to build, limited expressiveness | Out of scope for initial version |
| Python with decorators | Clean syntax | Still requires Python knowledge | Subset of hybrid approach |

### Best Practices

1. **Fail Fast**: Validate YAML configs at startup with Pydantic schemas
2. **Immutable Configs**: Treat configs as immutable during runtime, reload to change
3. **Config Versioning**: Include `version: "1.0"` in YAML for migration support
4. **Sensible Defaults**: Provide default values in strategy classes for optional params
5. **Config Documentation**: Auto-generate docs from Pydantic models showing available params

### Action Items

- [ ] Define `BaseStrategy` abstract class with required methods
- [ ] Create `StrategyConfig` Pydantic model for YAML validation
- [ ] Implement dynamic strategy loading from YAML
- [ ] Write example strategy (Golden Cross) demonstrating the pattern
- [ ] Document YAML schema and parameter meanings
- [ ] Add unit tests for strategy loading and validation

---

## 4. Notification Libraries for Python

### Decision - Discord

**Use `discord-webhook`** (PyPI: discord-webhook, latest: March 5, 2025)

### Rationale - Discord

1. **Most Recently Updated**: Released March 5, 2025, supports Python 3.10-3.13
2. **Async Native**: Full asyncio support with `AsyncDiscordWebhook` class
3. **Battle-Tested**: Production-stable, widely used in trading bots
4. **Minimal Dependencies**: Lightweight, doesn't require full discord.py library

### Implementation - Discord

```python
# services/notifier.py
import asyncio
from discord_webhook import AsyncDiscordWebhook
from typing import Optional

class DiscordNotifier:
    """Async Discord webhook notifier for trading events"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send_order_notification(
        self,
        stock_code: str,
        action: str,
        quantity: int,
        price: Decimal
    ):
        """Send order execution notification"""
        webhook = AsyncDiscordWebhook(
            url=self.webhook_url,
            content=f"**주문 체결 알림**\n종목: {stock_code}\n{action}: {quantity}주 @ {price:,}원"
        )
        await webhook.execute()

    async def send_error_alert(self, error_type: str, message: str):
        """Send critical error alert"""
        webhook = AsyncDiscordWebhook(
            url=self.webhook_url,
            content=f":warning: **긴급 알림**\n{error_type}\n{message}"
        )
        await webhook.execute()

    async def send_daily_report(self, report: dict):
        """Send end-of-day trading summary"""
        content = f"""
**일일 트레이딩 리포트**
총 매매: {report['total_trades']}건
실현 손익: {report['realized_pnl']:,}원
승률: {report['win_rate']:.1f}%
보유 종목: {report['open_positions']}개
        """
        webhook = AsyncDiscordWebhook(url=self.webhook_url, content=content.strip())
        await webhook.execute()
```

### Decision - Email

**Use `aiosmtplib`** (PyPI: aiosmtplib, latest: October 19, 2025)

### Rationale - Email

1. **Official asyncio Support**: Pure async SMTP implementation, no blocking calls
2. **Recently Updated**: October 19, 2025 release, requires Python 3.10+
3. **Production Stable**: Development Status 5 - Production/Stable
4. **Standard Library Compatible**: Works with `email.message.EmailMessage`
5. **TLS/SSL Support**: Automatic STARTTLS upgrade when server supports it

### Implementation - Email

```python
# services/notifier.py
import aiosmtplib
from email.message import EmailMessage
from typing import Optional

class EmailNotifier:
    """Async email notifier using aiosmtplib"""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_addr: str,
        to_addr: str
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.to_addr = to_addr

    async def send_notification(self, subject: str, body: str):
        """Send email notification"""
        message = EmailMessage()
        message["From"] = self.from_addr
        message["To"] = self.to_addr
        message["Subject"] = subject
        message.set_content(body)

        await aiosmtplib.send(
            message,
            hostname=self.smtp_host,
            port=self.smtp_port,
            username=self.username,
            password=self.password,
            use_tls=True
        )

    async def send_order_notification(
        self,
        stock_code: str,
        action: str,
        quantity: int,
        price: Decimal
    ):
        """Send order execution email"""
        subject = f"[자동매매] {action} 체결: {stock_code}"
        body = f"""
주문이 체결되었습니다.

종목: {stock_code}
주문 유형: {action}
체결 수량: {quantity}주
체결 가격: {price:,}원
총액: {quantity * price:,}원
        """
        await self.send_notification(subject, body.strip())
```

### Unified Notification Manager

```python
# services/notifier.py
from typing import List, Optional
from enum import Enum

class NotificationChannel(Enum):
    DISCORD = "discord"
    EMAIL = "email"

class NotificationManager:
    """Manages multiple notification channels"""

    def __init__(
        self,
        discord_webhook: Optional[str] = None,
        email_config: Optional[dict] = None,
        enabled_channels: List[NotificationChannel] = None
    ):
        self.notifiers = {}

        if discord_webhook and NotificationChannel.DISCORD in (enabled_channels or []):
            self.notifiers['discord'] = DiscordNotifier(discord_webhook)

        if email_config and NotificationChannel.EMAIL in (enabled_channels or []):
            self.notifiers['email'] = EmailNotifier(**email_config)

    async def send_to_all(self, method_name: str, *args, **kwargs):
        """Send notification to all enabled channels"""
        tasks = []
        for notifier in self.notifiers.values():
            method = getattr(notifier, method_name, None)
            if method:
                tasks.append(method(*args, **kwargs))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def send_order_notification(self, stock_code: str, action: str, quantity: int, price: Decimal):
        """Send order notification to all channels"""
        await self.send_to_all('send_order_notification', stock_code, action, quantity, price)

    async def send_error_alert(self, error_type: str, message: str):
        """Send error alert to all channels"""
        await self.send_to_all('send_error_alert', error_type, message)
```

### Configuration Example

```yaml
# config.yaml
notifications:
  enabled_channels:
    - discord
    - email

  discord:
    webhook_url: "https://discord.com/api/webhooks/..."

  email:
    smtp_host: "smtp.gmail.com"
    smtp_port: 587
    username: "your-email@gmail.com"
    password: "${EMAIL_PASSWORD}"  # From environment variable
    from_addr: "trading-bot@example.com"
    to_addr: "your-email@gmail.com"
```

### Alternatives Considered

| Library | Channel | Status | Async Support | Decision |
|---------|---------|--------|---------------|----------|
| **discord-webhook** | Discord | Latest: Mar 2025 | Yes (AsyncDiscordWebhook) | Chosen |
| discordwebhook.py | Discord | Active | Yes | Good, but less popular |
| dhooks | Discord | Active | Yes (Webhook.Async) | Older, less maintained |
| discord.py webhooks | Discord | v2.0+ stable | Yes | Overkill (need full bot library) |
| **aiosmtplib** | Email | Latest: Oct 2025 | Yes (native) | Chosen |
| smtplib | Email | Standard library | No (blocking) | Not async-compatible |
| yagmail | Email | Popular | No | Not async-compatible |

### Best Practices

1. **Rate Limiting**: Discord has webhook rate limits (30 requests/min), implement client-side throttling
2. **Retry Logic**: Both services can fail; implement exponential backoff
3. **Fallback**: If Discord fails, try Email (and vice versa)
4. **Sensitive Data**: Never log full email credentials or webhook URLs
5. **Environment Variables**: Store credentials in env vars, not config files
6. **Error Handling**: Don't let notification failures crash the trading system

### Action Items

- [ ] Install `discord-webhook` and `aiosmtplib` dependencies
- [ ] Implement `NotificationManager` with both channels
- [ ] Add rate limiting for Discord webhooks (30/min)
- [ ] Test notification delivery and measure latency
- [ ] Implement retry logic with exponential backoff
- [ ] Add notification preferences to config.yaml

---

## 5. Python Async Trading System Architecture

### Decision

**Event-driven architecture with asyncio event loop**:
- Single event loop running all async tasks
- Separate coroutines for data collection, strategy evaluation, order execution
- Use `asyncio.Queue` for inter-component communication
- Implement `asyncio.Semaphore` for concurrency control

### Rationale

1. **Industry Adoption (2025)**: Python asyncio has matured for trading applications:
   - **AAT (AsyncAlgoTrading)**: Production framework for event-driven algo trading
   - **FastAPI**: Processes 3,000+ requests/second with asyncio
   - **Alpaca Example**: Demonstrates concurrent multi-stock trading with asyncio

2. **Performance Characteristics**:
   - Python asyncio now matches Node.js/Go for I/O-bound operations (2025 benchmarks)
   - Event loop enables asynchronous I/O without blocking on network/disk operations
   - Critical for trading: Can process new data while waiting for API responses

3. **Concurrent Trading Requirements**:
   - Monitor 50+ stocks simultaneously
   - Process real-time price updates without blocking
   - Execute orders while continuing data collection
   - Run health checks in background

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Main Event Loop                          │
│  (Single asyncio.run() entry point)                        │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
┌───────▼───────┐    ┌───────▼───────┐    ┌───────▼───────┐
│ Data          │    │ Strategy      │    │ System        │
│ Collection    │    │ Evaluation    │    │ Management    │
│ Tasks         │    │ Tasks         │    │ Tasks         │
└───────┬───────┘    └───────┬───────┘    └───────┬───────┘
        │                     │                     │
        │  asyncio.Queue      │  asyncio.Queue      │
        └─────────►┌─────────▼──────────┐◄─────────┘
                   │  Order Execution   │
                   │  (Centralized)     │
                   └────────────────────┘
```

### Core Components

#### 1. Main Application Loop

```python
# cli/main.py
import asyncio
from services.data_collector import DataCollector
from services.strategy_engine import StrategyEngine
from services.order_executor import OrderExecutor
from services.health_check import HealthCheck

class TradingSystem:
    """Main trading system orchestrator"""

    def __init__(self, config):
        self.config = config
        self.market_data_queue = asyncio.Queue(maxsize=1000)
        self.order_queue = asyncio.Queue(maxsize=100)
        self.shutdown_event = asyncio.Event()

        # Components
        self.data_collector = DataCollector(config, self.market_data_queue)
        self.strategy_engine = StrategyEngine(config, self.market_data_queue, self.order_queue)
        self.order_executor = OrderExecutor(config, self.order_queue)
        self.health_check = HealthCheck(config, self.shutdown_event)

    async def start(self):
        """Start all system components"""
        tasks = [
            asyncio.create_task(self.data_collector.run(), name="data_collector"),
            asyncio.create_task(self.strategy_engine.run(), name="strategy_engine"),
            asyncio.create_task(self.order_executor.run(), name="order_executor"),
            asyncio.create_task(self.health_check.run(), name="health_check"),
        ]

        try:
            await self.shutdown_event.wait()
        finally:
            # Graceful shutdown
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

def main():
    config = load_config()
    system = TradingSystem(config)
    asyncio.run(system.start())
```

#### 2. Data Collection (Producer)

```python
# services/data_collector.py
import asyncio
from typing import List

class DataCollector:
    """Collects market data and publishes to queue"""

    def __init__(self, config, market_data_queue: asyncio.Queue):
        self.config = config
        self.queue = market_data_queue
        self.stocks = config.watched_stocks
        self.rate_limiter = TokenBucketRateLimiter(rate=15)

    async def run(self):
        """Main data collection loop"""
        # Stagger stock polling to distribute load
        tasks = []
        stagger_delay = 1.0 / len(self.stocks)

        for idx, stock_code in enumerate(self.stocks):
            delay = idx * stagger_delay
            task = asyncio.create_task(
                self.poll_stock(stock_code, delay),
                name=f"poll_{stock_code}"
            )
            tasks.append(task)

        await asyncio.gather(*tasks)

    async def poll_stock(self, stock_code: str, initial_delay: float):
        """Poll single stock at regular intervals"""
        await asyncio.sleep(initial_delay)

        while True:
            try:
                await self.rate_limiter.acquire()

                # Fetch price data
                data = await self.api_client.get_price(stock_code)

                # Publish to queue (non-blocking)
                try:
                    self.queue.put_nowait({
                        'stock_code': stock_code,
                        'price': data['price'],
                        'volume': data['volume'],
                        'timestamp': data['timestamp']
                    })
                except asyncio.QueueFull:
                    logger.warning(f"Market data queue full, dropping {stock_code} update")

            except Exception as e:
                logger.error(f"Error polling {stock_code}: {e}")

            await asyncio.sleep(self.config.poll_interval)
```

#### 3. Strategy Engine (Consumer/Producer)

```python
# services/strategy_engine.py
import asyncio
from typing import List

class StrategyEngine:
    """Evaluates strategies and generates orders"""

    def __init__(self, config, market_data_queue: asyncio.Queue, order_queue: asyncio.Queue):
        self.config = config
        self.market_data_queue = market_data_queue
        self.order_queue = order_queue
        self.strategies = []
        self.positions = {}

    async def run(self):
        """Main strategy evaluation loop"""
        # Load strategies
        self.strategies = await self.load_strategies()

        while True:
            # Get market data (blocking until available)
            market_data = await self.market_data_queue.get()

            try:
                # Evaluate all strategies for this stock
                await self.evaluate_strategies(market_data)
            except Exception as e:
                logger.error(f"Error evaluating strategies: {e}")
            finally:
                self.market_data_queue.task_done()

    async def evaluate_strategies(self, market_data: dict):
        """Evaluate all strategies concurrently"""
        stock_code = market_data['stock_code']

        # Run all strategies in parallel
        tasks = [
            strategy.evaluate(market_data, self.positions.get(stock_code))
            for strategy in self.strategies
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Generate orders from strategy signals
        for strategy, result in zip(self.strategies, results):
            if isinstance(result, Exception):
                logger.error(f"Strategy {strategy.name} failed: {result}")
                continue

            if result and result.action:  # Buy or Sell signal
                await self.order_queue.put({
                    'strategy': strategy.name,
                    'stock_code': stock_code,
                    'action': result.action,
                    'quantity': result.quantity,
                    'price': market_data['price']
                })
```

#### 4. Order Executor (Consumer)

```python
# services/order_executor.py
import asyncio
from decimal import Decimal

class OrderExecutor:
    """Executes orders with safety checks"""

    def __init__(self, config, order_queue: asyncio.Queue):
        self.config = config
        self.order_queue = order_queue
        self.pending_orders = {}  # Track pending orders to prevent duplicates
        self.order_semaphore = asyncio.Semaphore(5)  # Max 5 concurrent orders

    async def run(self):
        """Main order execution loop"""
        while True:
            order_request = await self.order_queue.get()

            try:
                # Execute in background (don't block queue processing)
                asyncio.create_task(self.execute_order(order_request))
            except Exception as e:
                logger.error(f"Error creating order task: {e}")
            finally:
                self.order_queue.task_done()

    async def execute_order(self, order_request: dict):
        """Execute single order with safety checks"""
        async with self.order_semaphore:
            stock_code = order_request['stock_code']

            # Check for duplicate orders
            if stock_code in self.pending_orders:
                logger.warning(f"Duplicate order prevented for {stock_code}")
                return

            try:
                self.pending_orders[stock_code] = True

                # Pre-flight checks
                if order_request['action'] == 'BUY':
                    balance = await self.api_client.get_balance()
                    cost = order_request['quantity'] * order_request['price']

                    if balance < cost:
                        logger.error(f"Insufficient balance for {stock_code}")
                        await self.notify_insufficient_balance(order_request)
                        return

                # Execute order via API
                result = await self.api_client.place_order(
                    stock_code=stock_code,
                    action=order_request['action'],
                    quantity=order_request['quantity'],
                    price=order_request['price']
                )

                # Log and notify
                logger.info(f"Order executed: {result}")
                await self.notifier.send_order_notification(order_request)

            except Exception as e:
                logger.error(f"Order execution failed: {e}")
                await self.notifier.send_error_alert("Order Failed", str(e))
            finally:
                del self.pending_orders[stock_code]
```

### Concurrency Control Patterns

#### 1. Semaphore for Rate Limiting

```python
# Limit concurrent API calls
api_semaphore = asyncio.Semaphore(15)

async def api_call():
    async with api_semaphore:
        # Only 15 concurrent API calls allowed
        response = await client.get(url)
        return response
```

#### 2. Queue for Inter-Task Communication

```python
# Producer
await queue.put(data)

# Consumer
data = await queue.get()
try:
    process(data)
finally:
    queue.task_done()
```

#### 3. Event for Coordination

```python
# Shutdown coordination
shutdown_event = asyncio.Event()

# In task
async def worker():
    while not shutdown_event.is_set():
        await do_work()

# Trigger shutdown
shutdown_event.set()
```

### Common Pitfalls and Solutions

| Pitfall | Impact | Solution |
|---------|--------|----------|
| **Blocking I/O in async code** | Stalls event loop, freezes system | Use async libraries (aiohttp, not requests) |
| **Unhandled exceptions in tasks** | Silent failures, no error visibility | Wrap tasks with try/except, log errors |
| **Race conditions on shared state** | Inconsistent position tracking | Use asyncio.Lock for critical sections |
| **Queue overflow** | Memory leaks, data loss | Set maxsize, handle QueueFull exceptions |
| **Forgetting task_done()** | queue.join() hangs forever | Always call in finally block |
| **Python GIL limiting CPU** | Slow calculations block event loop | Offload heavy calculations to ProcessPoolExecutor |
| **Garbage collector pauses** | Latency spikes in HFT scenarios | Tune GC settings, avoid creating many short-lived objects |

### Error Handling Best Practices

```python
# BAD: Exception kills the task
async def bad_poller():
    while True:
        data = await fetch_data()  # If this raises, loop stops forever
        process(data)

# GOOD: Exception is logged, task continues
async def good_poller():
    while True:
        try:
            data = await fetch_data()
            process(data)
        except Exception as e:
            logger.error(f"Polling error: {e}", exc_info=True)
            await asyncio.sleep(5)  # Back off before retry
```

### Background Task Management

```python
# Track all background tasks
class TaskManager:
    def __init__(self):
        self.tasks: List[asyncio.Task] = []

    def create_task(self, coro, name: str):
        task = asyncio.create_task(coro, name=name)
        self.tasks.append(task)

        # Auto-remove on completion
        task.add_done_callback(self.tasks.remove)

        return task

    async def shutdown(self):
        for task in self.tasks:
            task.cancel()

        await asyncio.gather(*self.tasks, return_exceptions=True)
```

### Performance Monitoring

```python
# Monitor event loop lag
import time

class EventLoopMonitor:
    async def monitor(self):
        while True:
            start = time.perf_counter()
            await asyncio.sleep(0)  # Yield to event loop
            lag = time.perf_counter() - start

            if lag > 0.1:  # 100ms lag is concerning
                logger.warning(f"Event loop lag: {lag*1000:.2f}ms")

            await asyncio.sleep(1)
```

### Alternatives Considered

| Approach | Pros | Cons | Decision |
|----------|------|------|----------|
| **Asyncio (chosen)** | Native Python, mature ecosystem, good performance | Learning curve, GIL limits CPU-bound tasks | Best for I/O-bound trading |
| Threading | Simple for beginners | GIL limits parallelism, harder to debug | Not suitable for async I/O |
| Multiprocessing | True parallelism | High overhead, complex state sharing | Overkill for this use case |
| Twisted | Mature framework | Older API style, declining popularity | Asyncio is more modern |
| Trio | Clean API, structured concurrency | Smaller ecosystem | Too new, fewer libraries |

### Action Items

- [ ] Design event loop architecture with clear component boundaries
- [ ] Implement `asyncio.Queue` communication between data collector, strategy engine, and order executor
- [ ] Add `asyncio.Semaphore` for API rate limiting and concurrent order limits
- [ ] Implement error handling with task-level try/except and logging
- [ ] Add event loop lag monitoring for performance debugging
- [ ] Write integration test simulating full data collection → strategy → order flow
- [ ] Document shutdown procedure and graceful task cancellation

---

## Summary and Recommendations

### Key Decisions Made

| Topic | Decision | Confidence | Next Steps |
|-------|----------|------------|------------|
| API Rate Limits | 15 req/sec with token bucket | Medium | Verify with official docs after registration |
| Real-time Data | REST polling (1s intervals) | High | Monitor for WebSocket availability |
| Strategy Definition | Hybrid (Python logic + YAML config) | High | Implement and document pattern |
| Discord Notifications | discord-webhook library | High | Implement with rate limiting |
| Email Notifications | aiosmtplib library | High | Test with real SMTP server |
| Async Architecture | Event loop with asyncio.Queue | High | Build and test full pipeline |

### Critical Path Items (Phase 0 → Phase 1)

1. **Register for Kiwoom REST API** and confirm official rate limits
2. **Test real API calls** to understand actual response times and data formats
3. **Implement rate limiter** as foundational component
4. **Design data models** (Order, Position, Stock) based on actual API responses
5. **Build PoC** of data collector → strategy engine → order executor pipeline

### Risk Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Kiwoom API rate limits stricter than assumed | Medium | High | Conservative throttling, monitoring, alerts |
| No WebSocket support causes data lag | High | Medium | Optimize polling, consider OpenAPI+ hybrid |
| YAML config too limiting for complex strategies | Low | Medium | Keep hybrid approach, extend Python when needed |
| Event loop blocking under load | Low | High | Profile performance, offload CPU tasks |

### Open Questions for Official Documentation Review

1. What is the exact rate limit for Kiwoom REST API (requests per second)?
2. Are there separate limits for different endpoint types (data vs orders)?
3. Is WebSocket supported for real-time data streaming?
4. What are the official response time SLAs for API calls?
5. Are there any time-of-day restrictions on API availability?
6. What error codes indicate rate limiting vs other failures?

---

## References

### Kiwoom Securities
- Official REST API: https://openapi.kiwoom.com/
- AI Coding Assistant announcement (May 2025): MetaJournal, Financial Post Korea

### Industry Comparisons
- Korea Investment Securities API: https://apiportal.koreainvestment.com/
- Rate limit reference: https://hky035.github.io/web/kis-api-throttling/

### Python Libraries
- discord-webhook: https://pypi.org/project/discord-webhook/ (Mar 5, 2025)
- aiosmtplib: https://pypi.org/project/aiosmtplib/ (Oct 19, 2025)
- aiohttp: Standard async HTTP client
- pydantic: Data validation framework

### Trading System Architecture
- AAT (AsyncAlgoTrading): https://github.com/AsyncAlgoTrading/aat
- Alpaca Scalping Example: https://alpaca.markets/learn/concurrent-scalping-algo-async-python
- Python HFT Techniques: https://www.pyquantnews.com/free-python-resources/python-in-high-frequency-trading-low-latency-techniques

### Best Practices Resources
- Asyncio Event Loops: https://docs.python.org/3/library/asyncio-eventloop.html
- Race Conditions in Python (2025): https://medium.com/pythoneers/avoiding-race-conditions-in-python-in-2025-best-practices-for-async-and-threads-4e006579a622
- API Rate Limiting Patterns: https://zuplo.com/learning-center/10-best-practices-for-api-rate-limiting-in-2025

---

**Next Phase**: Proceed to Phase 1 (Data Model Design) with these research findings incorporated into technical decisions.
