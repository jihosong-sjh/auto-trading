"""Event Replay for debugging and analysis.

Event Replay allows reconstructing system state or analyzing behavior
by replaying historical events from the event store.
"""

import logging
from datetime import datetime
from typing import Callable, Dict, List, Optional, Type
from decimal import Decimal

from .base import BaseEvent
from .event_store import EventStore
from .event_bus import EventBus

logger = logging.getLogger(__name__)


class EventReplay:
    """Replay historical events for debugging and analysis.

    Event Replay enables:
    - Debugging by replaying what happened during a trading session
    - Reconstructing aggregate state from events
    - Analyzing system behavior over time
    - Testing event handlers with real historical data

    Attributes:
        event_store: EventStore to replay events from.
        event_bus: Optional EventBus to publish replayed events to.
    """

    def __init__(
        self, event_store: EventStore, event_bus: Optional[EventBus] = None
    ):
        """Initialize event replay.

        Args:
            event_store: EventStore containing historical events.
            event_bus: Optional EventBus to publish replayed events to.
        """
        self.event_store = event_store
        self.event_bus = event_bus

    async def replay_by_time_range(
        self,
        from_time: datetime,
        to_time: datetime,
        event_types: Optional[List[str]] = None,
        speed: float = 1.0,
    ) -> int:
        """Replay events within a time range.

        Args:
            from_time: Start time (inclusive).
            to_time: End time (inclusive).
            event_types: Optional list of event types to replay (None = all).
            speed: Replay speed multiplier (1.0 = real-time, 0 = instant).

        Returns:
            Number of events replayed.

        Example:
            >>> # Replay yesterday's trading session
            >>> from datetime import datetime, timedelta
            >>> yesterday = datetime.now() - timedelta(days=1)
            >>> today = datetime.now()
            >>> await replay.replay_by_time_range(yesterday, today)
        """
        logger.info(
            f"Replaying events from {from_time} to {to_time} at {speed}x speed"
        )

        # Get all events in the time range
        all_events = await self.event_store.get_events()

        # Filter by time and event type
        filtered_events = []
        for event_data in all_events:
            event_time = datetime.fromisoformat(event_data["timestamp"])
            if from_time <= event_time <= to_time:
                if event_types is None or event_data["event_type"] in event_types:
                    filtered_events.append(event_data)

        logger.info(f"Found {len(filtered_events)} events to replay")

        # Replay events
        count = 0
        for event_data in filtered_events:
            # Reconstruct event (as dict for now)
            event_dict = event_data["payload"]

            # Publish to event bus if configured
            if self.event_bus:
                # For full integration, we'd deserialize to actual event objects
                logger.debug(
                    f"Replaying event: {event_data['event_type']} (seq={event_data['sequence_number']})"
                )

            count += 1

        logger.info(f"Replayed {count} events")
        return count

    async def replay_by_aggregate(
        self, aggregate_id: str, aggregate_type: Optional[str] = None
    ) -> List[dict]:
        """Replay all events for a specific aggregate.

        Useful for reconstructing the full history of an Order or Position.

        Args:
            aggregate_id: ID of the aggregate (e.g., order_id).
            aggregate_type: Type of aggregate (e.g., "Order", "Position").

        Returns:
            List of events for the aggregate in chronological order.

        Example:
            >>> # Replay all events for an order
            >>> events = await replay.replay_by_aggregate("2025112212345678", "Order")
            >>> print(f"Order went through {len(events)} state changes")
        """
        logger.info(f"Replaying aggregate: {aggregate_id} ({aggregate_type})")

        events = await self.event_store.get_events_by_aggregate(
            aggregate_id=aggregate_id, aggregate_type=aggregate_type
        )

        logger.info(f"Found {len(events)} events for aggregate {aggregate_id}")
        return events

    async def analyze_order_lifecycle(self, order_id: str) -> Dict[str, any]:
        """Analyze the complete lifecycle of an order.

        Args:
            order_id: Order ID to analyze.

        Returns:
            Dictionary with lifecycle analysis.

        Example:
            >>> analysis = await replay.analyze_order_lifecycle("2025112212345678")
            >>> print(f"Order created at: {analysis['created_at']}")
            >>> print(f"Order filled at: {analysis['filled_at']}")
            >>> print(f"Time to fill: {analysis['time_to_fill']}")
        """
        events = await self.replay_by_aggregate(order_id, "Order")

        if not events:
            logger.warning(f"No events found for order {order_id}")
            return {}

        analysis = {
            "order_id": order_id,
            "total_events": len(events),
            "event_types": [e["event_type"] for e in events],
            "created_at": None,
            "submitted_at": None,
            "filled_at": None,
            "time_to_fill": None,
            "final_status": None,
        }

        # Extract timing information
        for event in events:
            event_type = event["event_type"]
            timestamp = datetime.fromisoformat(event["timestamp"])

            if event_type == "OrderCreated":
                analysis["created_at"] = timestamp
            elif event_type == "OrderSubmitted":
                analysis["submitted_at"] = timestamp
            elif event_type == "OrderFilled":
                analysis["filled_at"] = timestamp
                analysis["final_status"] = "FILLED"
            elif event_type == "OrderRejected":
                analysis["final_status"] = "REJECTED"
            elif event_type == "OrderCancelled":
                analysis["final_status"] = "CANCELLED"

        # Calculate time to fill
        if analysis["created_at"] and analysis["filled_at"]:
            analysis["time_to_fill"] = (
                analysis["filled_at"] - analysis["created_at"]
            ).total_seconds()

        logger.info(f"Order lifecycle analysis: {analysis}")
        return analysis

    async def analyze_position_pnl(self, stock_code: str) -> Dict[str, any]:
        """Analyze P&L history for a position.

        Args:
            stock_code: Stock code of the position.

        Returns:
            Dictionary with P&L analysis.

        Example:
            >>> analysis = await replay.analyze_position_pnl("005930")
            >>> print(f"Total realized P&L: {analysis['total_pnl']}")
            >>> print(f"Number of trades: {analysis['trade_count']}")
        """
        events = await self.replay_by_aggregate(stock_code, "Position")

        if not events:
            logger.warning(f"No events found for position {stock_code}")
            return {}

        analysis = {
            "stock_code": stock_code,
            "total_events": len(events),
            "opened_at": None,
            "closed_at": None,
            "total_pnl": Decimal("0"),
            "return_rate": Decimal("0"),
            "price_updates": 0,
            "increases": 0,
            "decreases": 0,
        }

        # Analyze events
        for event in events:
            event_type = event["event_type"]
            payload = event["payload"]

            if event_type == "PositionOpened":
                analysis["opened_at"] = datetime.fromisoformat(event["timestamp"])

            elif event_type == "PositionClosed":
                analysis["closed_at"] = datetime.fromisoformat(event["timestamp"])
                if "realized_pnl" in payload:
                    analysis["total_pnl"] = Decimal(str(payload["realized_pnl"]))
                if "return_rate" in payload:
                    analysis["return_rate"] = Decimal(str(payload["return_rate"]))

            elif event_type == "PositionIncreased":
                analysis["increases"] += 1

            elif event_type == "PositionDecreased":
                analysis["decreases"] += 1
                if "partial_pnl" in payload:
                    analysis["total_pnl"] += Decimal(str(payload["partial_pnl"]))

            elif event_type == "PositionPriceUpdated":
                analysis["price_updates"] += 1

        logger.info(f"Position P&L analysis: {analysis}")
        return analysis

    async def get_daily_summary(self, date: datetime) -> Dict[str, any]:
        """Get a summary of all events for a specific day.

        Args:
            date: Date to summarize.

        Returns:
            Dictionary with daily summary statistics.

        Example:
            >>> from datetime import datetime
            >>> today = datetime.now().date()
            >>> summary = await replay.get_daily_summary(today)
            >>> print(f"Orders created: {summary['orders_created']}")
            >>> print(f"Orders filled: {summary['orders_filled']}")
        """
        from datetime import timedelta

        start_time = datetime.combine(date, datetime.min.time())
        end_time = start_time + timedelta(days=1)

        # Get all events for the day
        all_events = await self.event_store.get_events()
        daily_events = [
            e
            for e in all_events
            if start_time
            <= datetime.fromisoformat(e["timestamp"])
            < end_time
        ]

        # Count events by type
        event_counts = {}
        for event in daily_events:
            event_type = event["event_type"]
            event_counts[event_type] = event_counts.get(event_type, 0) + 1

        summary = {
            "date": date.isoformat(),
            "total_events": len(daily_events),
            "event_counts": event_counts,
            "orders_created": event_counts.get("OrderCreated", 0),
            "orders_submitted": event_counts.get("OrderSubmitted", 0),
            "orders_filled": event_counts.get("OrderFilled", 0),
            "orders_rejected": event_counts.get("OrderRejected", 0),
            "positions_opened": event_counts.get("PositionOpened", 0),
            "positions_closed": event_counts.get("PositionClosed", 0),
        }

        logger.info(f"Daily summary for {date}: {summary}")
        return summary

    async def export_events_to_json(
        self,
        from_time: datetime,
        to_time: datetime,
        output_file: str,
        event_types: Optional[List[str]] = None,
    ) -> int:
        """Export events to JSON file for external analysis.

        Args:
            from_time: Start time (inclusive).
            to_time: End time (inclusive).
            output_file: Path to output JSON file.
            event_types: Optional list of event types to export.

        Returns:
            Number of events exported.

        Example:
            >>> await replay.export_events_to_json(
            ...     from_time=yesterday,
            ...     to_time=today,
            ...     output_file="trading_events_2025-11-23.json"
            ... )
        """
        import json

        logger.info(f"Exporting events to {output_file}")

        # Get events
        all_events = await self.event_store.get_events()
        filtered_events = []

        for event_data in all_events:
            event_time = datetime.fromisoformat(event_data["timestamp"])
            if from_time <= event_time <= to_time:
                if event_types is None or event_data["event_type"] in event_types:
                    filtered_events.append(event_data)

        # Write to file
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(filtered_events, f, indent=2, ensure_ascii=False, default=str)

        logger.info(f"Exported {len(filtered_events)} events to {output_file}")
        return len(filtered_events)
