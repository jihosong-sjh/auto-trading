"""Event Bus for pub/sub messaging.

The Event Bus enables loose coupling between components through
asynchronous event-driven communication.
"""

import asyncio
import logging
from collections import defaultdict
from typing import Callable, Dict, List, Optional

from .base import BaseEvent
from .event_store import EventStore

logger = logging.getLogger(__name__)


class EventBus:
    """Central event bus for pub/sub messaging.

    All components publish and subscribe to events through this bus.
    The bus handles:
    - Event publishing to subscribers
    - Error isolation (one handler's error doesn't affect others)
    - Concurrent event delivery
    - Optional event store integration for persistence

    Attributes:
        event_store: Optional EventStore for persisting events.
        _subscribers: Dictionary mapping event types to handler functions.
    """

    def __init__(self, event_store: Optional[EventStore] = None):
        """Initialize event bus.

        Args:
            event_store: Optional EventStore to persist all events.
        """
        self.event_store = event_store
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._global_subscribers: List[Callable] = []  # Handlers for all events

    def subscribe(
        self, event_type: str, handler: Callable[[BaseEvent], None]
    ) -> None:
        """Subscribe to a specific event type.

        Args:
            event_type: Type of event to subscribe to.
            handler: Async callback function to handle events.
                     Signature: async def handler(event: BaseEvent) -> None

        Example:
            >>> bus = EventBus()
            >>> async def on_order_filled(event: OrderFilledEvent):
            ...     print(f"Order filled: {event.order.order_id}")
            >>> bus.subscribe("OrderFilled", on_order_filled)
        """
        self._subscribers[event_type].append(handler)
        logger.info(f"Subscribed to {event_type}: {handler.__name__}")

    def subscribe_all(self, handler: Callable[[BaseEvent], None]) -> None:
        """Subscribe to ALL event types.

        Useful for logging, monitoring, or audit trail purposes.

        Args:
            handler: Async callback function that receives all events.

        Example:
            >>> async def log_all_events(event: BaseEvent):
            ...     logger.info(f"Event: {event.event_type}")
            >>> bus.subscribe_all(log_all_events)
        """
        self._global_subscribers.append(handler)
        logger.info(f"Subscribed to ALL events: {handler.__name__}")

    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        """Unsubscribe from an event type.

        Args:
            event_type: Event type.
            handler: Handler to remove.
        """
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(handler)
                logger.info(f"Unsubscribed from {event_type}: {handler.__name__}")
            except ValueError:
                logger.warning(
                    f"Handler {handler.__name__} was not subscribed to {event_type}"
                )

    def unsubscribe_all(self, handler: Callable) -> None:
        """Unsubscribe a handler from all events.

        Args:
            handler: Handler to remove.
        """
        try:
            self._global_subscribers.remove(handler)
            logger.info(f"Unsubscribed from ALL events: {handler.__name__}")
        except ValueError:
            logger.warning(f"Handler {handler.__name__} was not subscribed to ALL events")

    async def publish(self, event: BaseEvent) -> None:
        """Publish an event to all subscribers.

        Calls all registered handlers for the event type concurrently.
        Handlers are executed with error isolation - if one handler fails,
        others still execute.

        If an EventStore is configured, the event is persisted first.

        Args:
            event: Event to publish.

        Example:
            >>> event = OrderFilledEvent(
            ...     source="OrderExecutor",
            ...     order=order,
            ...     stock_name="Samsung"
            ... )
            >>> await bus.publish(event)
        """
        event_type = event.event_type
        logger.info(f"Publishing event: {event_type} (id={event.event_id})")

        # Persist event to store if available
        if self.event_store:
            try:
                await self.event_store.append(event)
            except Exception as e:
                logger.error(f"Failed to persist event to store: {e}", exc_info=True)
                # Continue publishing even if persistence fails

        # Get handlers for this specific event type
        handlers = self._subscribers.get(event_type, [])

        # Add global handlers
        all_handlers = handlers + self._global_subscribers

        if not all_handlers:
            logger.warning(f"No subscribers for event type: {event_type}")
            return

        # Call all handlers concurrently with error isolation
        tasks = [self._call_handler_safe(handler, event) for handler in all_handlers]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _call_handler_safe(self, handler: Callable, event: BaseEvent) -> None:
        """Call handler with error isolation.

        Ensures one handler's error doesn't affect other handlers.

        Args:
            handler: Event handler function.
            event: Event to pass to handler.
        """
        try:
            await handler(event)
            logger.debug(
                f"Handler {handler.__name__} processed {event.event_type} successfully"
            )
        except Exception as e:
            logger.error(
                f"Error in event handler {handler.__name__} for event {event.event_type}: {e}",
                exc_info=True,
            )
            # Error is isolated - don't re-raise

    def get_subscriber_count(self, event_type: Optional[str] = None) -> int:
        """Get number of subscribers for an event type.

        Args:
            event_type: Event type to check (None for global subscribers).

        Returns:
            Number of subscribers.
        """
        if event_type is None:
            return len(self._global_subscribers)
        return len(self._subscribers.get(event_type, []))

    def clear_subscribers(self) -> None:
        """Clear all subscribers.

        Useful for testing or resetting the bus.
        """
        self._subscribers.clear()
        self._global_subscribers.clear()
        logger.info("All subscribers cleared")


# Singleton instance
_event_bus: Optional[EventBus] = None


def get_event_bus(event_store: Optional[EventStore] = None) -> EventBus:
    """Get the singleton EventBus instance.

    Args:
        event_store: Optional EventStore to persist events.

    Returns:
        EventBus instance.
    """
    global _event_bus

    if _event_bus is None:
        _event_bus = EventBus(event_store=event_store)

    return _event_bus
