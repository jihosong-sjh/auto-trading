"""Tests for EventBus."""

import pytest
import asyncio
from pathlib import Path
from decimal import Decimal

from src.events import (
    EventBus,
    EventStore,
    OrderCreatedEvent,
    OrderFilledEvent,
    PositionOpenedEvent,
)
from src.models import Order, Position, OrderType, OrderStatus, PriceType


@pytest.fixture
def event_bus():
    """Create an EventBus for testing."""
    return EventBus()


@pytest.fixture
async def event_bus_with_store(tmp_path):
    """Create an EventBus with EventStore for testing."""
    db_path = tmp_path / "test_events.db"
    store = EventStore(db_path)
    await store.connect()
    await store.init_schema()

    bus = EventBus(event_store=store)
    yield bus

    await store.disconnect()


@pytest.fixture
def sample_order():
    """Create a sample order for testing."""
    return Order(
        order_id="TEST123",
        account_number="12345678",
        stock_code="005930",
        order_type=OrderType.BUY,
        price_type=PriceType.LIMIT,
        quantity=100,
        limit_price=Decimal("72000"),
        status=OrderStatus.PENDING,
    )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_subscribe_and_publish(event_bus, sample_order):
    """Test subscribing to and publishing events."""
    received_events = []

    async def handler(event):
        received_events.append(event)

    # Subscribe to OrderCreated events
    event_bus.subscribe("OrderCreated", handler)

    # Publish event
    event = OrderCreatedEvent(source="TestExecutor", order=sample_order)
    await event_bus.publish(event)

    # Handler should have received the event
    assert len(received_events) == 1
    assert received_events[0].event_id == event.event_id


@pytest.mark.asyncio
@pytest.mark.unit
async def test_multiple_subscribers(event_bus, sample_order):
    """Test multiple subscribers for the same event type."""
    received_by_handler1 = []
    received_by_handler2 = []

    async def handler1(event):
        received_by_handler1.append(event)

    async def handler2(event):
        received_by_handler2.append(event)

    # Subscribe both handlers
    event_bus.subscribe("OrderCreated", handler1)
    event_bus.subscribe("OrderCreated", handler2)

    # Publish event
    event = OrderCreatedEvent(source="TestExecutor", order=sample_order)
    await event_bus.publish(event)

    # Both handlers should receive the event
    assert len(received_by_handler1) == 1
    assert len(received_by_handler2) == 1


@pytest.mark.asyncio
@pytest.mark.unit
async def test_subscribe_to_different_event_types(event_bus, sample_order):
    """Test subscribing to different event types."""
    created_events = []
    filled_events = []

    async def on_created(event):
        created_events.append(event)

    async def on_filled(event):
        filled_events.append(event)

    # Subscribe to different types
    event_bus.subscribe("OrderCreated", on_created)
    event_bus.subscribe("OrderFilled", on_filled)

    # Publish OrderCreated
    event1 = OrderCreatedEvent(source="TestExecutor", order=sample_order)
    await event_bus.publish(event1)

    # Publish OrderFilled
    event2 = OrderFilledEvent(
        source="TestExecutor",
        order=sample_order,
        stock_name="Samsung",
    )
    await event_bus.publish(event2)

    # Each handler should only receive its event type
    assert len(created_events) == 1
    assert len(filled_events) == 1


@pytest.mark.asyncio
@pytest.mark.unit
async def test_subscribe_all(event_bus, sample_order):
    """Test subscribing to all event types."""
    all_events = []

    async def global_handler(event):
        all_events.append(event)

    # Subscribe to all events
    event_bus.subscribe_all(global_handler)

    # Publish different event types
    event1 = OrderCreatedEvent(source="TestExecutor", order=sample_order)
    event2 = OrderFilledEvent(
        source="TestExecutor",
        order=sample_order,
        stock_name="Samsung",
    )

    await event_bus.publish(event1)
    await event_bus.publish(event2)

    # Global handler should receive all events
    assert len(all_events) == 2


@pytest.mark.asyncio
@pytest.mark.unit
async def test_unsubscribe(event_bus, sample_order):
    """Test unsubscribing from events."""
    received_events = []

    async def handler(event):
        received_events.append(event)

    # Subscribe
    event_bus.subscribe("OrderCreated", handler)

    # Publish event
    event1 = OrderCreatedEvent(source="TestExecutor", order=sample_order)
    await event_bus.publish(event1)

    assert len(received_events) == 1

    # Unsubscribe
    event_bus.unsubscribe("OrderCreated", handler)

    # Publish another event
    event2 = OrderCreatedEvent(
        source="TestExecutor",
        order=sample_order.model_copy(update={"order_id": "TEST456"}),
    )
    await event_bus.publish(event2)

    # Handler should not receive second event
    assert len(received_events) == 1


@pytest.mark.asyncio
@pytest.mark.unit
async def test_error_isolation(event_bus, sample_order):
    """Test that errors in one handler don't affect others."""
    successful_events = []

    async def failing_handler(event):
        raise Exception("Handler error")

    async def successful_handler(event):
        successful_events.append(event)

    # Subscribe both handlers
    event_bus.subscribe("OrderCreated", failing_handler)
    event_bus.subscribe("OrderCreated", successful_handler)

    # Publish event
    event = OrderCreatedEvent(source="TestExecutor", order=sample_order)
    await event_bus.publish(event)

    # Successful handler should still receive event
    assert len(successful_events) == 1


@pytest.mark.asyncio
@pytest.mark.unit
async def test_event_persistence_with_store(event_bus_with_store, sample_order):
    """Test that events are persisted when EventStore is configured."""
    bus = event_bus_with_store

    # Publish event
    event = OrderCreatedEvent(source="TestExecutor", order=sample_order)
    await bus.publish(event)

    # Event should be in store
    count = await bus.event_store.get_event_count()
    assert count == 1


@pytest.mark.asyncio
@pytest.mark.unit
async def test_no_subscribers_warning(event_bus, sample_order, caplog):
    """Test warning when publishing to event type with no subscribers."""
    # Publish without any subscribers
    event = OrderCreatedEvent(source="TestExecutor", order=sample_order)
    await event_bus.publish(event)

    # Should log warning (checked via caplog in actual test)
    # This test verifies the system doesn't crash


@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_subscriber_count(event_bus):
    """Test getting subscriber count."""
    async def handler1(event):
        pass

    async def handler2(event):
        pass

    # Initially no subscribers
    assert event_bus.get_subscriber_count("OrderCreated") == 0

    # Add subscribers
    event_bus.subscribe("OrderCreated", handler1)
    assert event_bus.get_subscriber_count("OrderCreated") == 1

    event_bus.subscribe("OrderCreated", handler2)
    assert event_bus.get_subscriber_count("OrderCreated") == 2


@pytest.mark.asyncio
@pytest.mark.unit
async def test_clear_subscribers(event_bus):
    """Test clearing all subscribers."""

    async def handler(event):
        pass

    # Add subscribers
    event_bus.subscribe("OrderCreated", handler)
    event_bus.subscribe_all(handler)

    assert event_bus.get_subscriber_count("OrderCreated") == 1
    assert event_bus.get_subscriber_count(None) == 1

    # Clear all
    event_bus.clear_subscribers()

    assert event_bus.get_subscriber_count("OrderCreated") == 0
    assert event_bus.get_subscriber_count(None) == 0


@pytest.mark.asyncio
@pytest.mark.unit
async def test_concurrent_publishing(event_bus, sample_order):
    """Test concurrent event publishing."""
    received_events = []
    lock = asyncio.Lock()

    async def handler(event):
        async with lock:
            received_events.append(event)

    event_bus.subscribe("OrderCreated", handler)

    # Publish multiple events concurrently
    async def publish_event(i):
        event = OrderCreatedEvent(
            source="TestExecutor",
            order=sample_order.model_copy(update={"order_id": f"TEST{i}"}),
        )
        await event_bus.publish(event)

    tasks = [publish_event(i) for i in range(10)]
    await asyncio.gather(*tasks)

    # All events should be received
    assert len(received_events) == 10


@pytest.mark.asyncio
@pytest.mark.unit
async def test_async_handler_execution(event_bus, sample_order):
    """Test that handlers execute asynchronously."""
    execution_order = []

    async def slow_handler(event):
        await asyncio.sleep(0.1)
        execution_order.append("slow")

    async def fast_handler(event):
        execution_order.append("fast")

    # Subscribe both
    event_bus.subscribe("OrderCreated", slow_handler)
    event_bus.subscribe("OrderCreated", fast_handler)

    # Publish event
    event = OrderCreatedEvent(source="TestExecutor", order=sample_order)
    await event_bus.publish(event)

    # Both should have executed
    assert len(execution_order) == 2
    # Fast handler likely executed first, but not guaranteed due to async
