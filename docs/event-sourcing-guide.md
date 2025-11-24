# Event Sourcing Implementation Guide

**Date**: 2025-11-24
**Status**: Phase 4 Complete

## Overview

This guide explains how to use the Event Sourcing system for tracking all trading events with immutable storage and event replay capabilities for debugging.

## Architecture

### Components

1. **EventStore**: Immutable append-only event storage using SQLite
2. **EventBus**: Pub/Sub event bus for loose coupling between components
3. **EventReplay**: Debug and analysis tool for replaying historical events
4. **Event Models**: Strongly-typed event definitions (Order events, Position events)

### Event Flow

```
Component A (Publisher)
    |
    | publishes event
    v
EventBus
    |
    +---> EventStore (persists immutable event)
    |
    +---> Component B (Subscriber 1)
    |
    +---> Component C (Subscriber 2)
    |
    +---> Component D (Subscriber N)
```

## Quick Start

### 1. Initialize Event Sourcing Infrastructure

```python
from pathlib import Path
from src.events import EventStore, EventBus, get_event_store, get_event_bus

# Initialize EventStore
event_store = await get_event_store(Path("data/events.db"))
await event_store.connect()
await event_store.init_schema()

# Initialize EventBus with EventStore integration
event_bus = get_event_bus(event_store=event_store)
```

### 2. Publishing Events

```python
from src.events import OrderCreatedEvent, OrderFilledEvent
from src.models import Order, OrderType, OrderStatus, PriceType
from decimal import Decimal

# Create an order
order = Order(
    order_id="2025112412345678",
    account_number="12345678",
    stock_code="005930",
    order_type=OrderType.BUY,
    price_type=PriceType.LIMIT,
    quantity=100,
    limit_price=Decimal("72000"),
    status=OrderStatus.PENDING
)

# Publish OrderCreatedEvent
event = OrderCreatedEvent(
    source="OrderExecutor",
    order=order
)
await event_bus.publish(event)
```

### 3. Subscribing to Events

```python
async def handle_order_created(event: OrderCreatedEvent):
    """Handle order creation."""
    print(f"Order created: {event.order.order_id}")
    # Send notification, log, etc.

async def handle_order_filled(event: OrderFilledEvent):
    """Handle order fill."""
    print(f"Order filled: {event.order.order_id} - {event.stock_name}")
    # Update position, send notification, etc.

# Subscribe to specific event types
event_bus.subscribe("OrderCreated", handle_order_created)
event_bus.subscribe("OrderFilled", handle_order_filled)

# Or subscribe to ALL events (for logging/monitoring)
async def log_all_events(event):
    logger.info(f"Event: {event.event_type} from {event.source}")

event_bus.subscribe_all(log_all_events)
```

## Integration with Existing Components

### OrderExecutor Integration

**Before (without Event Sourcing):**

```python
class OrderExecutor:
    async def submit_order(self, order: Order) -> Order:
        # Submit to broker API
        order.status = OrderStatus.SUBMITTED

        # Update database directly
        await self.repository.update(order)

        return order
```

**After (with Event Sourcing):**

```python
class OrderExecutor:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

    async def create_order(self, order: Order) -> Order:
        # Create order
        order.status = OrderStatus.PENDING

        # Publish event (automatically persisted and distributed)
        event = OrderCreatedEvent(
            source="OrderExecutor",
            order=order
        )
        await self.event_bus.publish(event)

        return order

    async def submit_order(self, order: Order) -> Order:
        # Submit to broker API
        order.status = OrderStatus.SUBMITTED

        # Publish event
        event = OrderSubmittedEvent(
            source="OrderExecutor",
            order=order
        )
        await self.event_bus.publish(event)

        return order

    async def on_order_filled(self, order: Order, stock_name: str):
        """Called by broker callback when order fills."""
        order.status = OrderStatus.FILLED

        # Publish event
        event = OrderFilledEvent(
            source="OrderExecutor",
            order=order,
            stock_name=stock_name
        )
        await self.event_bus.publish(event)
```

### PositionManager Integration

```python
class PositionManager:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

        # Subscribe to order events
        self.event_bus.subscribe("OrderFilled", self.on_order_filled)

    async def on_order_filled(self, event: OrderFilledEvent):
        """Update position when order fills."""
        order = event.order

        if order.order_type == OrderType.BUY:
            # Open or increase position
            position = await self._update_position(order)

            # Publish position event
            pos_event = PositionOpenedEvent(
                source="PositionManager",
                position=position
            )
            await self.event_bus.publish(pos_event)

        elif order.order_type == OrderType.SELL:
            # Close or decrease position
            position, realized_pnl = await self._close_position(order)

            # Publish position closed event
            pos_event = PositionClosedEvent(
                source="PositionManager",
                position=position,
                realized_pnl=realized_pnl,
                return_rate=position.return_rate
            )
            await self.event_bus.publish(pos_event)
```

### NotificationManager Integration

```python
class NotificationManager:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

        # Subscribe to events we want to notify about
        self.event_bus.subscribe("OrderFilled", self.on_order_filled)
        self.event_bus.subscribe("OrderRejected", self.on_order_rejected)
        self.event_bus.subscribe("PositionClosed", self.on_position_closed)

    async def on_order_filled(self, event: OrderFilledEvent):
        """Send notification when order fills."""
        await self.send_notification(
            title=f"Order Filled: {event.stock_name}",
            message=f"Order {event.order.order_id} filled at {event.order.filled_price}"
        )

    async def on_order_rejected(self, event: OrderRejectedEvent):
        """Send alert when order rejected."""
        await self.send_notification(
            title="Order Rejected",
            message=f"Order {event.order.order_id}: {event.rejection_reason}"
        )
```

## Event Replay for Debugging

### Analyze Order Lifecycle

```python
from src.events import EventReplay

# Create replay instance
replay = EventReplay(event_store=event_store)

# Analyze what happened to a specific order
analysis = await replay.analyze_order_lifecycle("2025112412345678")

print(f"Order created at: {analysis['created_at']}")
print(f"Order submitted at: {analysis['submitted_at']}")
print(f"Order filled at: {analysis['filled_at']}")
print(f"Time to fill: {analysis['time_to_fill']} seconds")
print(f"Event sequence: {analysis['event_types']}")
```

Output:
```
Order created at: 2025-11-24 09:15:23
Order submitted at: 2025-11-24 09:15:24
Order filled at: 2025-11-24 09:15:27
Time to fill: 4.0 seconds
Event sequence: ['OrderCreated', 'OrderSubmitted', 'OrderFilled']
```

### Analyze Position P&L

```python
# Analyze position history
analysis = await replay.analyze_position_pnl("005930")

print(f"Position opened at: {analysis['opened_at']}")
print(f"Position closed at: {analysis['closed_at']}")
print(f"Total realized P&L: {analysis['total_pnl']}")
print(f"Return rate: {analysis['return_rate']}%")
print(f"Number of increases: {analysis['increases']}")
print(f"Number of decreases: {analysis['decreases']}")
print(f"Price updates: {analysis['price_updates']}")
```

### Daily Trading Summary

```python
from datetime import datetime

# Get summary for today
today = datetime.now().date()
summary = await replay.get_daily_summary(today)

print(f"Total events today: {summary['total_events']}")
print(f"Orders created: {summary['orders_created']}")
print(f"Orders filled: {summary['orders_filled']}")
print(f"Orders rejected: {summary['orders_rejected']}")
print(f"Positions opened: {summary['positions_opened']}")
print(f"Positions closed: {summary['positions_closed']}")
```

### Export Events for Analysis

```python
from datetime import datetime, timedelta

# Export yesterday's events to JSON
yesterday = datetime.now() - timedelta(days=1)
today = datetime.now()

await replay.export_events_to_json(
    from_time=yesterday,
    to_time=today,
    output_file="trading_events_2025-11-23.json"
)
```

## Complete Integration Example

```python
import asyncio
from pathlib import Path
from src.events import EventStore, EventBus, EventReplay, get_event_store, get_event_bus

async def main():
    # 1. Initialize infrastructure
    event_store = await get_event_store(Path("data/events.db"))
    await event_store.connect()
    await event_store.init_schema()

    event_bus = get_event_bus(event_store=event_store)

    # 2. Initialize components with EventBus
    order_executor = OrderExecutor(event_bus=event_bus)
    position_manager = PositionManager(event_bus=event_bus)
    notification_manager = NotificationManager(event_bus=event_bus)
    risk_manager = RiskManager(event_bus=event_bus)

    # 3. Run trading system
    # Events are automatically published, persisted, and distributed
    order = await order_executor.create_order(...)
    await order_executor.submit_order(order)

    # 4. Debug/analyze later using EventReplay
    replay = EventReplay(event_store=event_store)
    analysis = await replay.analyze_order_lifecycle(order.order_id)

    # 5. Cleanup
    await event_store.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
```

## Benefits

### 1. Complete Audit Trail
Every state change is recorded immutably. You can always answer:
- "What happened to this order?"
- "When did this position close?"
- "Why was this order rejected?"

### 2. Debugging Power
Replay historical events to understand exactly what happened:
```python
# Replay yesterday's trading session
await replay.replay_by_time_range(yesterday, today)
```

### 3. Loose Coupling
Components don't need to know about each other:
```python
# OrderExecutor doesn't need to know about NotificationManager
# Just publishes events; NotificationManager subscribes
```

### 4. Easy Testing
Test components in isolation with mock event bus:
```python
@pytest.fixture
def mock_event_bus():
    bus = EventBus()
    bus.published_events = []

    original_publish = bus.publish
    async def mock_publish(event):
        bus.published_events.append(event)
        await original_publish(event)

    bus.publish = mock_publish
    return bus
```

### 5. Time Travel
Reconstruct state at any point in time by replaying events.

## Event Types Reference

### Order Events
- `OrderCreatedEvent` - Order created but not yet submitted
- `OrderSubmittedEvent` - Order submitted to broker
- `OrderFilledEvent` - Order completely filled
- `OrderPartiallyFilledEvent` - Order partially filled
- `OrderCancelledEvent` - Order cancelled
- `OrderRejectedEvent` - Order rejected by broker
- `OrderFailedEvent` - Order failed due to system error

### Position Events
- `PositionOpenedEvent` - New position opened
- `PositionIncreasedEvent` - Position quantity increased
- `PositionDecreasedEvent` - Position quantity decreased
- `PositionClosedEvent` - Position completely closed
- `PositionPriceUpdatedEvent` - Position price updated from market data

## Best Practices

### 1. Always Publish Events
Every state change should publish an event:
```python
# Bad: Direct state change without event
order.status = OrderStatus.FILLED

# Good: Publish event for state change
event = OrderFilledEvent(source="OrderExecutor", order=order)
await event_bus.publish(event)
```

### 2. Events are Immutable
Never modify events after creation:
```python
# This will raise an error (frozen=True)
event.source = "ModifiedSource"  # Error!
```

### 3. Use Specific Event Types
Don't use generic events:
```python
# Bad: Generic event
event = BaseEvent(event_type="something_happened", ...)

# Good: Specific typed event
event = OrderFilledEvent(source="...", order=order, stock_name="Samsung")
```

### 4. Add Context to Events
Use the metadata field for additional context:
```python
event = OrderCreatedEvent(
    source="OrderExecutor",
    order=order,
    metadata={
        "user": "trader1",
        "strategy": "momentum",
        "reason": "buy_signal"
    }
)
```

### 5. Handle Errors Gracefully
Event handlers should never crash the system:
```python
async def my_handler(event):
    try:
        # Process event
        await do_something(event)
    except Exception as e:
        logger.error(f"Error processing event: {e}", exc_info=True)
        # Don't re-raise - error isolation
```

## Troubleshooting

### Events not being persisted
Check that EventStore is connected and EventBus is configured with it:
```python
event_bus = EventBus(event_store=event_store)  # Must pass event_store
```

### Handler not receiving events
Check subscription:
```python
# Make sure event type matches exactly
event_bus.subscribe("OrderFilled", handler)  # Exact match required
```

### Slow event processing
Use concurrent handlers wisely. Handlers execute concurrently but heavy work should be offloaded:
```python
async def handler(event):
    # Quick processing here
    await process_light_work(event)

    # Offload heavy work
    asyncio.create_task(process_heavy_work(event))
```

## Performance Considerations

- EventStore uses SQLite with proper indexes (event_type, aggregate_id, timestamp)
- Events are written synchronously but distributed to handlers concurrently
- For high-volume trading, consider batching or async writes
- Event replay should be used for analysis, not production event processing

## Future Enhancements

1. **Event Snapshots**: Periodic snapshots for faster aggregate reconstruction
2. **Event Versioning**: Support for event schema evolution
3. **Distributed Event Store**: PostgreSQL or event streaming (Kafka/RabbitMQ)
4. **Event Projections**: Materialized views/read models from events
5. **CQRS Integration**: Command-Query Responsibility Segregation

## Summary

Event Sourcing provides a complete audit trail of all trading activities with:
- ✅ Immutable event storage (EventStore)
- ✅ Pub/Sub messaging (EventBus)
- ✅ Event replay for debugging (EventReplay)
- ✅ Strong typing (OrderCreatedEvent, PositionOpenedEvent, etc.)
- ✅ Comprehensive test coverage
- ✅ Easy integration with existing components

All trading events are now captured forever and can be replayed for debugging, analysis, or compliance purposes.
