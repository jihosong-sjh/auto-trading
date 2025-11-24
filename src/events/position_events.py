"""Position-related events for Event Sourcing.

These events capture all state changes in position lifecycle.
"""

from pydantic import Field
from typing import Literal
from decimal import Decimal

from .base import DomainEvent
from ..models.position import Position


class PositionOpenedEvent(DomainEvent):
    """Event published when a new position is opened.

    Published by: PositionManager
    Subscribers: Notifier, RiskManager, Account

    Attributes:
        position: Newly opened position.
    """

    event_type: Literal["PositionOpened"] = "PositionOpened"
    position: Position

    def __init__(self, **data):
        """Initialize event with aggregate metadata."""
        if "position" in data:
            position = data["position"]
            # Use stock_code as aggregate_id since Position doesn't have an ID
            data.setdefault("aggregate_id", position.stock_code)
            data.setdefault("aggregate_type", "Position")
        super().__init__(**data)


class PositionIncreasedEvent(DomainEvent):
    """Event published when an existing position is increased (additional buy).

    Published by: PositionManager
    Subscribers: Notifier, RiskManager, Account

    Attributes:
        position: Updated position after increase.
        quantity_added: Quantity added to position.
        previous_quantity: Quantity before increase.
        previous_average_price: Average price before increase.
    """

    event_type: Literal["PositionIncreased"] = "PositionIncreased"
    position: Position
    quantity_added: int
    previous_quantity: int
    previous_average_price: Decimal

    def __init__(self, **data):
        """Initialize event with aggregate metadata."""
        if "position" in data:
            position = data["position"]
            data.setdefault("aggregate_id", position.stock_code)
            data.setdefault("aggregate_type", "Position")
        super().__init__(**data)


class PositionDecreasedEvent(DomainEvent):
    """Event published when a position is decreased (partial sell).

    Published by: PositionManager
    Subscribers: Notifier, RiskManager, Account

    Attributes:
        position: Updated position after decrease.
        quantity_sold: Quantity sold from position.
        sell_price: Price at which position was partially sold.
        partial_pnl: Realized P&L from this partial sell.
    """

    event_type: Literal["PositionDecreased"] = "PositionDecreased"
    position: Position
    quantity_sold: int
    sell_price: Decimal
    partial_pnl: Decimal

    def __init__(self, **data):
        """Initialize event with aggregate metadata."""
        if "position" in data:
            position = data["position"]
            data.setdefault("aggregate_id", position.stock_code)
            data.setdefault("aggregate_type", "Position")
        super().__init__(**data)


class PositionClosedEvent(DomainEvent):
    """Event published when a position is completely closed.

    Published by: PositionManager
    Subscribers: Notifier, RiskManager, Account, ReportGenerator

    Attributes:
        position: Closed position with final P&L.
        realized_pnl: Final realized profit/loss.
        return_rate: Rate of return (percentage).
    """

    event_type: Literal["PositionClosed"] = "PositionClosed"
    position: Position
    realized_pnl: Decimal
    return_rate: Decimal

    def __init__(self, **data):
        """Initialize event with aggregate metadata."""
        if "position" in data:
            position = data["position"]
            data.setdefault("aggregate_id", position.stock_code)
            data.setdefault("aggregate_type", "Position")
        super().__init__(**data)


class PositionPriceUpdatedEvent(DomainEvent):
    """Event published when position's current price is updated.

    Published by: PositionManager (from market data)
    Subscribers: RiskManager, UI/Dashboard

    Attributes:
        stock_code: Stock code.
        previous_price: Previous current price.
        new_price: New current price.
        unrealized_pnl: Current unrealized P&L.
        unrealized_pnl_rate: Current unrealized P&L rate (%).
    """

    event_type: Literal["PositionPriceUpdated"] = "PositionPriceUpdated"
    stock_code: str
    previous_price: Decimal
    new_price: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_rate: Decimal

    def __init__(self, **data):
        """Initialize event with aggregate metadata."""
        if "stock_code" in data:
            data.setdefault("aggregate_id", data["stock_code"])
            data.setdefault("aggregate_type", "Position")
        super().__init__(**data)
