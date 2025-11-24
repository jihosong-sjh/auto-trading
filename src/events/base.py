"""Base event classes for Event Sourcing.

All events in the system inherit from BaseEvent and are immutable.
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


class BaseEvent(BaseModel):
    """Base class for all events.

    Events are immutable records of state changes that have occurred
    in the system. They form the single source of truth for the event store.

    Attributes:
        event_id: Unique event identifier (UUID).
        event_type: Type of event (e.g., "OrderCreated").
        timestamp: When the event occurred (KST timezone).
        source: Component that published the event.
        metadata: Additional metadata (optional).
        aggregate_id: ID of the aggregate this event belongs to (optional).
        aggregate_type: Type of aggregate (e.g., "Order", "Position").
        version: Event schema version for future compatibility.
    """

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str = Field(..., description="Event type identifier")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=KST))
    source: str = Field(..., description="Event publisher component")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    aggregate_id: Optional[str] = Field(
        default=None, description="Aggregate root ID (e.g., order_id, position_id)"
    )
    aggregate_type: Optional[str] = Field(
        default=None, description="Aggregate type (e.g., Order, Position)"
    )
    version: int = Field(default=1, description="Event schema version")

    class Config:
        """Pydantic configuration."""

        frozen = True  # Events are immutable
        json_encoders = {datetime: lambda v: v.isoformat()}


class DomainEvent(BaseEvent):
    """Base class for domain events that affect business entities.

    Domain events represent state changes in business entities
    (aggregates) like Orders, Positions, and Accounts.
    """

    pass
