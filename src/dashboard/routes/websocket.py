"""WebSocket endpoint for real-time dashboard updates.

Provides a WebSocket endpoint that:
- Sends full snapshot on connection
- Broadcasts real-time position/portfolio/trade updates
- Handles client disconnection gracefully
"""

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ...utils.logger import get_logger
from ..services.data_subscriber import DashboardDataSubscriber
from ..models import WSMessageType

logger = get_logger(__name__)

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time dashboard updates.

    Protocol:
    1. Client connects
    2. Server sends full_snapshot message
    3. Server broadcasts updates as they occur:
       - position_update: Position price/P&L changed
       - portfolio_update: Portfolio summary changed
       - trade_executed: New trade executed
    4. Client can send ping messages (server responds with pong)
    5. Connection closes on disconnect or error

    Message Format (Server -> Client):
    {
        "type": "full_snapshot" | "position_update" | "portfolio_update" | "trade_executed",
        "data": { ... },
        "timestamp": "2024-01-01T10:00:00+09:00"
    }
    """
    subscriber: DashboardDataSubscriber = websocket.app.state.subscriber

    # Accept connection
    await websocket.accept()
    logger.info("WebSocket client connecting...")

    try:
        # Add client and send initial snapshot
        await subscriber.add_client(websocket)

        # Keep connection alive and handle client messages
        while True:
            try:
                # Wait for client message (ping/pong, etc.)
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=60.0,  # 60 second timeout
                )

                # Handle ping
                if data == "ping":
                    await websocket.send_text("pong")

            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                try:
                    await websocket.send_text('{"type": "ping"}')
                except Exception:
                    break

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected normally")

    except Exception as e:
        logger.error(f"WebSocket error: {e}")

    finally:
        # Remove client on disconnect
        await subscriber.remove_client(websocket)
