"""Tests for EventStore."""

import pytest
import asyncio
from pathlib import Path
from datetime import datetime
from decimal import Decimal

from src.events import (
    EventStore,
    OrderCreatedEvent,
    OrderFilledEvent,
    PositionOpenedEvent,
)
from src.models import Order, Position, OrderType, OrderStatus, PriceType


@pytest.fixture
async def event_store(tmp_path):
    """Create a temporary EventStore for testing."""
    db_path = tmp_path / "test_events.db"
    store = EventStore(db_path)
    await store.connect()
    await store.init_schema()
    yield store
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


@pytest.fixture
def sample_position():
    """Create a sample position for testing."""
    return Position(
        account_number="12345678",
        stock_code="005930",
        quantity=100,
        average_buy_price=Decimal("72000"),
        current_price=Decimal("72000"),
    )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_event_store_initialization(event_store):
    """Test EventStore initialization."""
    # Check that store is connected
    assert event_store.connection is not None

    # Check that initial count is 0
    count = await event_store.get_event_count()
    assert count == 0


@pytest.mark.asyncio
@pytest.mark.unit
async def test_append_and_retrieve_event(event_store, sample_order):
    """Test appending and retrieving an event."""
    # Create and append an event
    event = OrderCreatedEvent(source="TestExecutor", order=sample_order)
    sequence_number = await event_store.append(event)

    assert sequence_number == 1

    # Retrieve the event
    events = await event_store.get_events()
    assert len(events) == 1

    stored_event = events[0]
    assert stored_event["event_id"] == event.event_id
    assert stored_event["event_type"] == "OrderCreated"
    assert stored_event["aggregate_id"] == "TEST123"
    assert stored_event["aggregate_type"] == "Order"
    assert stored_event["source"] == "TestExecutor"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_append_multiple_events(event_store, sample_order):
    """Test appending multiple events."""
    # Append multiple events
    event1 = OrderCreatedEvent(source="TestExecutor", order=sample_order)
    event2 = OrderFilledEvent(
        source="TestExecutor",
        order=sample_order.model_copy(update={"status": OrderStatus.FILLED}),
        stock_name="Samsung",
    )

    seq1 = await event_store.append(event1)
    seq2 = await event_store.append(event2)

    assert seq1 == 1
    assert seq2 == 2

    # Retrieve all events
    events = await event_store.get_events()
    assert len(events) == 2


@pytest.mark.asyncio
@pytest.mark.unit
async def test_duplicate_event_id_rejected(event_store, sample_order):
    """Test that duplicate event IDs are rejected."""
    # Create event with fixed ID
    event1 = OrderCreatedEvent(source="TestExecutor", order=sample_order)
    await event_store.append(event1)

    # Try to append same event again
    with pytest.raises(ValueError, match="already exists"):
        await event_store.append(event1)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_events_by_type(event_store, sample_order, sample_position):
    """Test retrieving events by type."""
    # Append different event types
    event1 = OrderCreatedEvent(source="TestExecutor", order=sample_order)
    event2 = OrderFilledEvent(
        source="TestExecutor",
        order=sample_order,
        stock_name="Samsung",
    )
    event3 = PositionOpenedEvent(source="PositionManager", position=sample_position)

    await event_store.append(event1)
    await event_store.append(event2)
    await event_store.append(event3)

    # Get only OrderCreated events
    order_created_events = await event_store.get_events_by_type("OrderCreated")
    assert len(order_created_events) == 1
    assert order_created_events[0]["event_type"] == "OrderCreated"

    # Get only OrderFilled events
    order_filled_events = await event_store.get_events_by_type("OrderFilled")
    assert len(order_filled_events) == 1
    assert order_filled_events[0]["event_type"] == "OrderFilled"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_events_by_aggregate(event_store, sample_order):
    """Test retrieving events by aggregate ID."""
    # Create multiple events for the same order
    event1 = OrderCreatedEvent(source="TestExecutor", order=sample_order)
    event2 = OrderFilledEvent(
        source="TestExecutor",
        order=sample_order,
        stock_name="Samsung",
    )

    # Create event for different order
    other_order = sample_order.model_copy(update={"order_id": "TEST456"})
    event3 = OrderCreatedEvent(source="TestExecutor", order=other_order)

    await event_store.append(event1)
    await event_store.append(event2)
    await event_store.append(event3)

    # Get events for first order only
    order_events = await event_store.get_events_by_aggregate("TEST123", "Order")
    assert len(order_events) == 2
    assert all(e["aggregate_id"] == "TEST123" for e in order_events)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_events_by_sequence_range(event_store, sample_order):
    """Test retrieving events by sequence number range."""
    # Append 5 events
    for i in range(5):
        event = OrderCreatedEvent(
            source="TestExecutor",
            order=sample_order.model_copy(update={"order_id": f"TEST{i}"}),
        )
        await event_store.append(event)

    # Get events in range [2, 4]
    events = await event_store.get_events(from_sequence=2, to_sequence=4)
    assert len(events) == 3
    assert events[0]["sequence_number"] == 2
    assert events[1]["sequence_number"] == 3
    assert events[2]["sequence_number"] == 4


@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_latest_sequence_number(event_store, sample_order):
    """Test getting the latest sequence number."""
    # Initially should be None
    latest = await event_store.get_latest_sequence_number()
    assert latest is None

    # Append events
    for i in range(3):
        event = OrderCreatedEvent(
            source="TestExecutor",
            order=sample_order.model_copy(update={"order_id": f"TEST{i}"}),
        )
        await event_store.append(event)

    # Latest should be 3
    latest = await event_store.get_latest_sequence_number()
    assert latest == 3


@pytest.mark.asyncio
@pytest.mark.unit
async def test_event_immutability(event_store, sample_order):
    """Test that events cannot be modified after creation."""
    event = OrderCreatedEvent(source="TestExecutor", order=sample_order)

    # Attempting to modify frozen event should raise error
    with pytest.raises(Exception):
        event.source = "ModifiedSource"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_event_metadata(event_store, sample_order):
    """Test storing and retrieving event metadata."""
    metadata = {"user": "trader1", "reason": "manual_order"}
    event = OrderCreatedEvent(
        source="TestExecutor", order=sample_order, metadata=metadata
    )

    await event_store.append(event)

    # Retrieve and check metadata
    events = await event_store.get_events()
    assert len(events) == 1
    assert events[0]["metadata"] == metadata


@pytest.mark.asyncio
@pytest.mark.unit
async def test_concurrent_appends(event_store, sample_order):
    """Test concurrent event appending."""

    async def append_event(i):
        event = OrderCreatedEvent(
            source="TestExecutor",
            order=sample_order.model_copy(update={"order_id": f"TEST{i}"}),
        )
        return await event_store.append(event)

    # Append 10 events concurrently
    tasks = [append_event(i) for i in range(10)]
    sequence_numbers = await asyncio.gather(*tasks)

    # All should succeed
    assert len(sequence_numbers) == 10
    assert len(set(sequence_numbers)) == 10  # All unique

    # Total count should be 10
    count = await event_store.get_event_count()
    assert count == 10
