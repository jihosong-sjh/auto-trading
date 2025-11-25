"""Dashboard Data Subscriber - Redis to WebSocket clients.

Subscribes to Redis Pub/Sub channels and broadcasts updates
to connected WebSocket clients.
"""

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Set

from fastapi import WebSocket

from ...cache.shared_data import SharedDataManager
from ...cache.redis_manager import RedisManager
from ...models.stock import get_kst_now
from ...utils.logger import get_logger
from ..models import (
    DashboardPosition,
    DashboardPortfolio,
    DashboardTrade,
    DashboardSnapshot,
    WSMessageType,
)

logger = get_logger(__name__)


class DecimalEncoder(json.JSONEncoder):
    """JSON Encoder for Decimal types."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class DashboardDataSubscriber:
    """Subscribes to Redis and broadcasts to WebSocket clients.

    This service:
    1. Subscribes to Redis Pub/Sub channels for real-time updates
    2. Manages WebSocket client connections
    3. Broadcasts updates to all connected clients
    4. Provides REST API data from Redis shared state

    Redis Channels Subscribed:
    - pubsub:position_update - Position/price updates
    - pubsub:portfolio_update - Portfolio summary updates
    - pubsub:trade_executed - Trade execution events
    """

    # Channel names (without pubsub: prefix)
    CHANNEL_POSITION_UPDATE = "position_update"
    CHANNEL_PORTFOLIO_UPDATE = "portfolio_update"
    CHANNEL_TRADE_EXECUTED = "trade_executed"

    # State keys (without shared_state: prefix)
    STATE_POSITIONS = "dashboard:positions"
    STATE_PORTFOLIO = "dashboard:portfolio"
    STATE_TRADES_TODAY = "dashboard:trades_today"

    def __init__(self, redis_manager: RedisManager):
        """Initialize DashboardDataSubscriber.

        Args:
            redis_manager: Redis manager instance
        """
        self.shared_data = SharedDataManager(redis_manager, process_id="dashboard_subscriber")
        self._clients: Set[WebSocket] = set()
        self._running = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the subscriber and connect to Redis."""
        if self._running:
            logger.warning("DashboardDataSubscriber already running")
            return

        await self.shared_data.initialize()

        # Subscribe to channels
        await self.shared_data.subscribe(
            self.CHANNEL_POSITION_UPDATE,
            self._on_position_update,
        )
        await self.shared_data.subscribe(
            self.CHANNEL_PORTFOLIO_UPDATE,
            self._on_portfolio_update,
        )
        await self.shared_data.subscribe(
            self.CHANNEL_TRADE_EXECUTED,
            self._on_trade_executed,
        )

        self._running = True
        logger.info("DashboardDataSubscriber started")

    async def stop(self) -> None:
        """Stop the subscriber and disconnect all clients."""
        self._running = False

        # Close all WebSocket connections
        async with self._lock:
            for client in list(self._clients):
                try:
                    await client.close()
                except Exception:
                    pass
            self._clients.clear()

        await self.shared_data.close()
        logger.info("DashboardDataSubscriber stopped")

    async def add_client(self, websocket: WebSocket) -> None:
        """Add a WebSocket client and send initial snapshot.

        Args:
            websocket: WebSocket connection
        """
        async with self._lock:
            self._clients.add(websocket)

        # Send initial snapshot
        snapshot = await self.get_snapshot()
        await self._send_to_client(
            websocket,
            {
                "type": WSMessageType.FULL_SNAPSHOT.value,
                "data": snapshot,
                "timestamp": get_kst_now().isoformat(),
            },
        )

        logger.info(f"WebSocket client connected. Total clients: {len(self._clients)}")

    async def remove_client(self, websocket: WebSocket) -> None:
        """Remove a WebSocket client.

        Args:
            websocket: WebSocket connection
        """
        async with self._lock:
            self._clients.discard(websocket)

        logger.info(f"WebSocket client disconnected. Total clients: {len(self._clients)}")

    @property
    def client_count(self) -> int:
        """Get number of connected clients."""
        return len(self._clients)

    async def get_snapshot(self) -> Dict[str, Any]:
        """Get current dashboard snapshot from Redis.

        Returns:
            Dashboard snapshot dict
        """
        positions = await self.get_positions()
        portfolio = await self.get_portfolio()
        trades = await self.get_trades_today()

        return {
            "positions": positions,
            "portfolio": portfolio,
            "trades_today": trades,
        }

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get current positions from Redis.

        Returns:
            List of position dicts
        """
        positions = await self.shared_data.get_state(self.STATE_POSITIONS, [])
        return positions if positions else []

    async def get_portfolio(self) -> Dict[str, Any]:
        """Get current portfolio from Redis.

        Returns:
            Portfolio dict
        """
        portfolio = await self.shared_data.get_state(self.STATE_PORTFOLIO, None)
        if portfolio:
            return portfolio

        # Return empty portfolio if not available
        return {
            "total_evaluation": "0",
            "total_unrealized_pnl": "0",
            "daily_realized_pnl": "0",
            "cash_balance": "0",
            "total_asset_value": "0",
            "position_count": 0,
            "updated_at": get_kst_now().isoformat(),
            "total_return_pct": "0",
        }

    async def get_trades_today(self) -> List[Dict[str, Any]]:
        """Get today's trades from Redis.

        Returns:
            List of trade dicts
        """
        trades = await self.shared_data.get_state(self.STATE_TRADES_TODAY, [])
        return trades if trades else []

    async def _on_position_update(self, message: Dict[str, Any]) -> None:
        """Handle position update from Redis.

        Args:
            message: Position update message
        """
        await self._broadcast(message)

    async def _on_portfolio_update(self, message: Dict[str, Any]) -> None:
        """Handle portfolio update from Redis.

        Args:
            message: Portfolio update message
        """
        await self._broadcast(message)

    async def _on_trade_executed(self, message: Dict[str, Any]) -> None:
        """Handle trade executed from Redis.

        Args:
            message: Trade executed message
        """
        await self._broadcast(message)

    async def _broadcast(self, message: Dict[str, Any]) -> None:
        """Broadcast message to all connected WebSocket clients.

        Args:
            message: Message to broadcast
        """
        if not self._clients:
            return

        # Get copy of clients to avoid modification during iteration
        async with self._lock:
            clients = list(self._clients)

        # Send to all clients
        disconnected = []
        for client in clients:
            try:
                await self._send_to_client(client, message)
            except Exception as e:
                logger.debug(f"Failed to send to client: {e}")
                disconnected.append(client)

        # Remove disconnected clients
        if disconnected:
            async with self._lock:
                for client in disconnected:
                    self._clients.discard(client)

    async def _send_to_client(self, websocket: WebSocket, message: Dict[str, Any]) -> None:
        """Send message to a single WebSocket client.

        Args:
            websocket: WebSocket connection
            message: Message to send
        """
        try:
            # Serialize with custom encoder for Decimal
            json_str = json.dumps(message, cls=DecimalEncoder, ensure_ascii=False)
            await websocket.send_text(json_str)
        except Exception as e:
            logger.debug(f"Error sending to WebSocket: {e}")
            raise
