"""Order-related events for Event Sourcing.

These events capture all state changes in the order lifecycle.
"""

from pydantic import Field
from typing import Optional, Literal
from decimal import Decimal

from .base import DomainEvent
from ..models.order import Order


class OrderCreatedEvent(DomainEvent):
    """Event published when an order is created.

    Published by: OrderExecutor
    Subscribers: Notifier, RiskManager, OrderRepository

    Attributes:
        order: Created order with PENDING status.
    """

    event_type: Literal["OrderCreated"] = "OrderCreated"
    order: Order

    def __init__(self, **data):
        """Initialize event with aggregate metadata."""
        if "order" in data:
            order = data["order"]
            data.setdefault("aggregate_id", order.order_id)
            data.setdefault("aggregate_type", "Order")
        super().__init__(**data)


class OrderSubmittedEvent(DomainEvent):
    """Event published when an order is submitted to broker.

    Published by: OrderExecutor
    Subscribers: Notifier, OrderRepository, Strategy

    Attributes:
        order: Order with SUBMITTED status and broker order_id.
    """

    event_type: Literal["OrderSubmitted"] = "OrderSubmitted"
    order: Order

    def __init__(self, **data):
        """Initialize event with aggregate metadata."""
        if "order" in data:
            order = data["order"]
            data.setdefault("aggregate_id", order.order_id)
            data.setdefault("aggregate_type", "Order")
        super().__init__(**data)


class OrderFilledEvent(DomainEvent):
    """Event published when an order is fully filled.

    Published by: OrderExecutor
    Subscribers: Notifier, PositionManager, Strategy, RiskManager, Account

    Attributes:
        order: Filled order with FILLED status.
        stock_name: Stock name for notifications.
    """

    event_type: Literal["OrderFilled"] = "OrderFilled"
    order: Order
    stock_name: str

    def __init__(self, **data):
        """Initialize event with aggregate metadata."""
        if "order" in data:
            order = data["order"]
            data.setdefault("aggregate_id", order.order_id)
            data.setdefault("aggregate_type", "Order")
        super().__init__(**data)


class OrderPartiallyFilledEvent(DomainEvent):
    """Event published when an order is partially filled.

    Published by: OrderExecutor
    Subscribers: Notifier, OrderRepository

    Attributes:
        order: Order with PARTIALLY_FILLED status.
        filled_quantity_delta: Additional quantity filled since last update.
    """

    event_type: Literal["OrderPartiallyFilled"] = "OrderPartiallyFilled"
    order: Order
    filled_quantity_delta: int

    def __init__(self, **data):
        """Initialize event with aggregate metadata."""
        if "order" in data:
            order = data["order"]
            data.setdefault("aggregate_id", order.order_id)
            data.setdefault("aggregate_type", "Order")
        super().__init__(**data)


class OrderCancelledEvent(DomainEvent):
    """Event published when an order is cancelled.

    Published by: OrderExecutor
    Subscribers: Notifier, OrderRepository, Strategy

    Attributes:
        order: Order with CANCELLED status.
        cancellation_reason: Reason for cancellation.
    """

    event_type: Literal["OrderCancelled"] = "OrderCancelled"
    order: Order
    cancellation_reason: str

    def __init__(self, **data):
        """Initialize event with aggregate metadata."""
        if "order" in data:
            order = data["order"]
            data.setdefault("aggregate_id", order.order_id)
            data.setdefault("aggregate_type", "Order")
        super().__init__(**data)


class OrderRejectedEvent(DomainEvent):
    """Event published when broker rejects an order.

    Published by: OrderExecutor
    Subscribers: Notifier, Strategy, RiskManager

    Attributes:
        order: Order with REJECTED status.
        rejection_reason: Broker's rejection reason.
    """

    event_type: Literal["OrderRejected"] = "OrderRejected"
    order: Order
    rejection_reason: str

    def __init__(self, **data):
        """Initialize event with aggregate metadata."""
        if "order" in data:
            order = data["order"]
            data.setdefault("aggregate_id", order.order_id)
            data.setdefault("aggregate_type", "Order")
        super().__init__(**data)


class OrderFailedEvent(DomainEvent):
    """Event published when order submission fails due to system error.

    Published by: OrderExecutor
    Subscribers: Notifier, ErrorHandler

    Attributes:
        order: Order with FAILED status.
        error_message: System error message.
    """

    event_type: Literal["OrderFailed"] = "OrderFailed"
    order: Order
    error_message: str

    def __init__(self, **data):
        """Initialize event with aggregate metadata."""
        if "order" in data:
            order = data["order"]
            data.setdefault("aggregate_id", order.order_id)
            data.setdefault("aggregate_type", "Order")
        super().__init__(**data)
