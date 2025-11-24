"""
Event Sourcing Demo Script

This script demonstrates the Event Sourcing system with:
- Creating and publishing events
- Subscribing to events
- Event persistence
- Event replay and analysis
"""

import asyncio
import sys
from pathlib import Path
from decimal import Decimal
from datetime import datetime

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.events import (
    EventStore,
    EventBus,
    EventReplay,
    OrderCreatedEvent,
    OrderSubmittedEvent,
    OrderFilledEvent,
    PositionOpenedEvent,
    PositionClosedEvent,
)
from src.models import (
    Order,
    Position,
    OrderType,
    OrderStatus,
    PriceType,
)


async def demo_basic_event_flow():
    """Demonstrate basic event publishing and subscribing."""
    print("\n" + "=" * 60)
    print("DEMO 1: Basic Event Flow (Pub/Sub)")
    print("=" * 60)

    # Initialize EventBus (without persistence for this demo)
    event_bus = EventBus()

    # Create event handlers
    async def on_order_created(event):
        print(f"[Handler] Order created: {event.order.order_id}")

    async def on_order_filled(event):
        print(f"[Handler] Order filled: {event.order.order_id} - {event.stock_name}")

    # Subscribe handlers
    event_bus.subscribe("OrderCreated", on_order_created)
    event_bus.subscribe("OrderFilled", on_order_filled)

    # Create and publish events
    order = Order(
        order_id="DEMO001",
        account_number="12345678",
        stock_code="005930",
        order_type=OrderType.BUY,
        price_type=PriceType.LIMIT,
        quantity=100,
        limit_price=Decimal("72000"),
        status=OrderStatus.PENDING,
    )

    print("\n[System] Publishing OrderCreatedEvent...")
    event1 = OrderCreatedEvent(source="DemoOrderExecutor", order=order)
    await event_bus.publish(event1)

    print("\n[System] Publishing OrderFilledEvent...")
    filled_order = order.model_copy(
        update={"status": OrderStatus.FILLED, "filled_quantity": 100, "filled_price": Decimal("72000")}
    )
    event2 = OrderFilledEvent(
        source="DemoOrderExecutor",
        order=filled_order,
        stock_name="Samsung Electronics",
    )
    await event_bus.publish(event2)

    print("\n[Result] Events published and handlers executed successfully")


async def demo_event_persistence():
    """Demonstrate event persistence to EventStore."""
    print("\n" + "=" * 60)
    print("DEMO 2: Event Persistence (Immutable Storage)")
    print("=" * 60)

    # Initialize EventStore
    db_path = Path("data/demo_events.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    event_store = EventStore(db_path)
    await event_store.connect()
    await event_store.init_schema()

    # Initialize EventBus with EventStore
    event_bus = EventBus(event_store=event_store)

    # Create and publish events
    orders = [
        Order(
            order_id=f"DEMO{i:03d}",
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.LIMIT,
            quantity=100,
            limit_price=Decimal("72000"),
            status=OrderStatus.PENDING,
        )
        for i in range(1, 6)
    ]

    print("\n[System] Publishing 5 OrderCreatedEvents...")
    for order in orders:
        event = OrderCreatedEvent(source="DemoOrderExecutor", order=order)
        await event_bus.publish(event)
        print(f"  - Event for order {order.order_id} persisted")

    # Query events
    print("\n[System] Querying EventStore...")
    total_count = await event_store.get_event_count()
    print(f"  - Total events in store: {total_count}")

    order_events = await event_store.get_events_by_type("OrderCreated")
    print(f"  - OrderCreated events: {len(order_events)}")

    # Cleanup
    await event_store.disconnect()
    print("\n[Result] Events persisted immutably in EventStore")


async def demo_event_replay():
    """Demonstrate event replay for debugging."""
    print("\n" + "=" * 60)
    print("DEMO 3: Event Replay (Debugging & Analysis)")
    print("=" * 60)

    # Initialize infrastructure
    db_path = Path("data/demo_events.db")
    event_store = EventStore(db_path)
    await event_store.connect()
    await event_store.init_schema()

    event_bus = EventBus(event_store=event_store)

    # Simulate order lifecycle
    print("\n[System] Simulating order lifecycle for DEMO999...")

    order = Order(
        order_id="DEMO999",
        account_number="12345678",
        stock_code="005930",
        order_type=OrderType.BUY,
        price_type=PriceType.LIMIT,
        quantity=100,
        limit_price=Decimal("72000"),
        status=OrderStatus.PENDING,
    )

    # Event 1: Order Created
    event1 = OrderCreatedEvent(source="DemoOrderExecutor", order=order)
    await event_bus.publish(event1)
    print("  1. Order created")
    await asyncio.sleep(0.1)  # Simulate time passing

    # Event 2: Order Submitted
    submitted_order = order.model_copy(update={"status": OrderStatus.SUBMITTED})
    event2 = OrderSubmittedEvent(source="DemoOrderExecutor", order=submitted_order)
    await event_bus.publish(event2)
    print("  2. Order submitted")
    await asyncio.sleep(0.1)

    # Event 3: Order Filled
    filled_order = order.model_copy(
        update={
            "status": OrderStatus.FILLED,
            "filled_quantity": 100,
            "filled_price": Decimal("71500"),
        }
    )
    event3 = OrderFilledEvent(
        source="DemoOrderExecutor",
        order=filled_order,
        stock_name="Samsung Electronics",
    )
    await event_bus.publish(event3)
    print("  3. Order filled")

    # Now replay and analyze
    print("\n[System] Analyzing order lifecycle...")
    replay = EventReplay(event_store=event_store)
    analysis = await replay.analyze_order_lifecycle("DEMO999")

    print(f"\n[Analysis Results]")
    print(f"  - Order ID: {analysis['order_id']}")
    print(f"  - Total events: {analysis['total_events']}")
    print(f"  - Event sequence: {' -> '.join(analysis['event_types'])}")
    print(f"  - Created at: {analysis['created_at']}")
    print(f"  - Submitted at: {analysis['submitted_at']}")
    print(f"  - Filled at: {analysis['filled_at']}")
    print(f"  - Time to fill: {analysis['time_to_fill']:.2f} seconds")
    print(f"  - Final status: {analysis['final_status']}")

    # Cleanup
    await event_store.disconnect()
    print("\n[Result] Event replay provides complete audit trail")


async def demo_position_tracking():
    """Demonstrate position event tracking."""
    print("\n" + "=" * 60)
    print("DEMO 4: Position Event Tracking")
    print("=" * 60)

    # Initialize infrastructure
    db_path = Path("data/demo_events.db")
    event_store = EventStore(db_path)
    await event_store.connect()
    await event_store.init_schema()

    event_bus = EventBus(event_store=event_store)

    # Simulate position lifecycle
    print("\n[System] Simulating position lifecycle for 005930...")

    position = Position(
        account_number="12345678",
        stock_code="005930",
        quantity=100,
        average_buy_price=Decimal("72000"),
        current_price=Decimal("72000"),
    )

    # Event 1: Position Opened
    event1 = PositionOpenedEvent(source="DemoPositionManager", position=position)
    await event_bus.publish(event1)
    print("  1. Position opened: 100 shares at 72,000 KRW")

    # Event 2: Position Closed (with profit)
    closed_position = position.model_copy(update={"current_price": Decimal("75000")})
    realized_pnl = (Decimal("75000") - Decimal("72000")) * 100
    return_rate = ((Decimal("75000") / Decimal("72000")) - 1) * 100

    event2 = PositionClosedEvent(
        source="DemoPositionManager",
        position=closed_position,
        realized_pnl=realized_pnl,
        return_rate=return_rate,
    )
    await event_bus.publish(event2)
    print(f"  2. Position closed: 100 shares at 75,000 KRW")
    print(f"     Realized P&L: {realized_pnl:,} KRW")
    print(f"     Return: {return_rate:.2f}%")

    # Analyze position
    print("\n[System] Analyzing position P&L...")
    replay = EventReplay(event_store=event_store)
    analysis = await replay.analyze_position_pnl("005930")

    print(f"\n[Analysis Results]")
    print(f"  - Stock code: {analysis['stock_code']}")
    print(f"  - Total events: {analysis['total_events']}")
    print(f"  - Opened at: {analysis['opened_at']}")
    print(f"  - Closed at: {analysis['closed_at']}")
    print(f"  - Total P&L: {analysis['total_pnl']:,} KRW")
    print(f"  - Return rate: {analysis['return_rate']:.2f}%")

    # Cleanup
    await event_store.disconnect()
    print("\n[Result] Position events captured for P&L analysis")


async def main():
    """Run all demos."""
    print("\n" + "=" * 60)
    print("EVENT SOURCING SYSTEM DEMONSTRATION")
    print("Auto-Trading System - Phase 4")
    print("=" * 60)

    try:
        await demo_basic_event_flow()
        await demo_event_persistence()
        await demo_event_replay()
        await demo_position_tracking()

        print("\n" + "=" * 60)
        print("ALL DEMOS COMPLETED SUCCESSFULLY")
        print("=" * 60)
        print("\nEvent Sourcing System Features:")
        print("  [SUCCESS] Event publishing and subscribing (Pub/Sub)")
        print("  [SUCCESS] Immutable event storage (EventStore)")
        print("  [SUCCESS] Event replay for debugging (EventReplay)")
        print("  [SUCCESS] Order lifecycle analysis")
        print("  [SUCCESS] Position P&L tracking")
        print("\nNext steps:")
        print("  1. Integrate EventBus into OrderExecutor")
        print("  2. Integrate EventBus into PositionManager")
        print("  3. Use EventReplay for debugging production issues")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\n[ERROR] Demo failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
