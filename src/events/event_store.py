"""Event Store for immutable event storage.

The Event Store is the single source of truth for all events in the system.
Events are append-only and never modified or deleted.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Type, TypeVar
from zoneinfo import ZoneInfo

import aiosqlite

from .base import BaseEvent

KST = ZoneInfo("Asia/Seoul")
logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseEvent)


class EventStore:
    """Append-only event store using SQLite.

    Events are stored as immutable records in the database.
    The Event Store provides:
    - Append operations (write-only)
    - Query operations (read-only)
    - Event replay capabilities

    Attributes:
        db_path: Path to SQLite database file.
        connection: Database connection.
    """

    def __init__(self, db_path: Path):
        """Initialize event store.

        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self.connection: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """Connect to the database."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(self.db_path)
        self.connection.row_factory = aiosqlite.Row
        logger.info(f"EventStore connected: {self.db_path}")

    async def disconnect(self) -> None:
        """Disconnect from the database."""
        if self.connection:
            await self.connection.close()
            logger.info("EventStore disconnected")

    async def init_schema(self) -> None:
        """Initialize the events table schema.

        Creates the immutable events table if it doesn't exist.
        """
        if not self.connection:
            raise RuntimeError("EventStore not connected. Call connect() first.")

        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS events (
                sequence_number INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                aggregate_id TEXT,
                aggregate_type TEXT,
                timestamp TEXT NOT NULL,
                source TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                payload TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Indexes for efficient queries
        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)"
        )
        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_aggregate ON events(aggregate_id, aggregate_type)"
        )
        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)"
        )
        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_source ON events(source)"
        )

        await self.connection.commit()
        logger.info("EventStore schema initialized")

    async def append(self, event: BaseEvent) -> int:
        """Append an event to the store (write-only).

        Events are immutable and can never be modified or deleted.

        Args:
            event: Event to append.

        Returns:
            Sequence number of the stored event.

        Raises:
            ValueError: If event with same event_id already exists.
        """
        if not self.connection:
            raise RuntimeError("EventStore not connected")

        # Serialize event to JSON
        event_dict = event.model_dump(mode="json")
        payload = json.dumps(event_dict)
        metadata = json.dumps(event.metadata) if event.metadata else None

        try:
            cursor = await self.connection.execute(
                """
                INSERT INTO events (
                    event_id, event_type, aggregate_id, aggregate_type,
                    timestamp, source, version, payload, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.aggregate_id,
                    event.aggregate_type,
                    event.timestamp.isoformat(),
                    event.source,
                    event.version,
                    payload,
                    metadata,
                ),
            )
            await self.connection.commit()

            sequence_number = cursor.lastrowid
            logger.info(
                f"Event appended: {event.event_type} (id={event.event_id}, seq={sequence_number})"
            )
            return sequence_number

        except aiosqlite.IntegrityError as e:
            if "UNIQUE constraint failed" in str(e):
                raise ValueError(f"Event with id {event.event_id} already exists")
            raise

    async def get_events(
        self,
        from_sequence: Optional[int] = None,
        to_sequence: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[dict]:
        """Get events by sequence number range.

        Args:
            from_sequence: Starting sequence number (inclusive).
            to_sequence: Ending sequence number (inclusive).
            limit: Maximum number of events to return.

        Returns:
            List of event dictionaries.
        """
        if not self.connection:
            raise RuntimeError("EventStore not connected")

        query = "SELECT * FROM events WHERE 1=1"
        params = []

        if from_sequence is not None:
            query += " AND sequence_number >= ?"
            params.append(from_sequence)

        if to_sequence is not None:
            query += " AND sequence_number <= ?"
            params.append(to_sequence)

        query += " ORDER BY sequence_number ASC"

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        cursor = await self.connection.execute(query, params)
        rows = await cursor.fetchall()

        events = []
        for row in rows:
            event_data = dict(row)
            event_data["payload"] = json.loads(event_data["payload"])
            if event_data["metadata"]:
                event_data["metadata"] = json.loads(event_data["metadata"])
            events.append(event_data)

        logger.debug(f"Retrieved {len(events)} events")
        return events

    async def get_events_by_type(
        self,
        event_type: str,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[dict]:
        """Get events by type and optional time range.

        Args:
            event_type: Type of events to retrieve.
            from_time: Starting timestamp (inclusive).
            to_time: Ending timestamp (inclusive).
            limit: Maximum number of events to return.

        Returns:
            List of event dictionaries.
        """
        if not self.connection:
            raise RuntimeError("EventStore not connected")

        query = "SELECT * FROM events WHERE event_type = ?"
        params = [event_type]

        if from_time is not None:
            query += " AND timestamp >= ?"
            params.append(from_time.isoformat())

        if to_time is not None:
            query += " AND timestamp <= ?"
            params.append(to_time.isoformat())

        query += " ORDER BY sequence_number ASC"

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        cursor = await self.connection.execute(query, params)
        rows = await cursor.fetchall()

        events = []
        for row in rows:
            event_data = dict(row)
            event_data["payload"] = json.loads(event_data["payload"])
            if event_data["metadata"]:
                event_data["metadata"] = json.loads(event_data["metadata"])
            events.append(event_data)

        logger.debug(f"Retrieved {len(events)} events of type {event_type}")
        return events

    async def get_events_by_aggregate(
        self,
        aggregate_id: str,
        aggregate_type: Optional[str] = None,
        from_sequence: Optional[int] = None,
    ) -> List[dict]:
        """Get all events for a specific aggregate (e.g., an Order or Position).

        This is useful for reconstructing aggregate state from events.

        Args:
            aggregate_id: ID of the aggregate (e.g., order_id, position_id).
            aggregate_type: Type of aggregate (e.g., "Order", "Position").
            from_sequence: Starting sequence number (inclusive).

        Returns:
            List of event dictionaries in chronological order.
        """
        if not self.connection:
            raise RuntimeError("EventStore not connected")

        query = "SELECT * FROM events WHERE aggregate_id = ?"
        params = [aggregate_id]

        if aggregate_type is not None:
            query += " AND aggregate_type = ?"
            params.append(aggregate_type)

        if from_sequence is not None:
            query += " AND sequence_number >= ?"
            params.append(from_sequence)

        query += " ORDER BY sequence_number ASC"

        cursor = await self.connection.execute(query, params)
        rows = await cursor.fetchall()

        events = []
        for row in rows:
            event_data = dict(row)
            event_data["payload"] = json.loads(event_data["payload"])
            if event_data["metadata"]:
                event_data["metadata"] = json.loads(event_data["metadata"])
            events.append(event_data)

        logger.debug(
            f"Retrieved {len(events)} events for aggregate {aggregate_id} ({aggregate_type})"
        )
        return events

    async def get_event_count(self) -> int:
        """Get total number of events in the store.

        Returns:
            Total event count.
        """
        if not self.connection:
            raise RuntimeError("EventStore not connected")

        cursor = await self.connection.execute("SELECT COUNT(*) FROM events")
        row = await cursor.fetchone()
        return row[0]

    async def get_latest_sequence_number(self) -> Optional[int]:
        """Get the latest sequence number in the store.

        Returns:
            Latest sequence number, or None if store is empty.
        """
        if not self.connection:
            raise RuntimeError("EventStore not connected")

        cursor = await self.connection.execute(
            "SELECT MAX(sequence_number) FROM events"
        )
        row = await cursor.fetchone()
        return row[0]


# Singleton instance
_event_store: Optional[EventStore] = None


async def get_event_store(db_path: Optional[Path] = None) -> EventStore:
    """Get the singleton EventStore instance.

    Args:
        db_path: Path to database file (default: data/events.db).

    Returns:
        EventStore instance.
    """
    global _event_store

    if _event_store is None:
        if db_path is None:
            db_path = Path("data/events.db")
        _event_store = EventStore(db_path)

    return _event_store
