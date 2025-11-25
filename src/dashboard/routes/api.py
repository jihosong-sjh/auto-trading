"""REST API routes for Dashboard.

Provides endpoints for:
- GET /api/positions - Current positions
- GET /api/portfolio - Portfolio summary
- GET /api/trades - Today's trades
- GET /api/snapshot - Full dashboard snapshot
"""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Request

from ...utils.logger import get_logger
from ..services.data_subscriber import DashboardDataSubscriber

logger = get_logger(__name__)

router = APIRouter()


def get_subscriber(request: Request) -> DashboardDataSubscriber:
    """Dependency to get subscriber from app state."""
    return request.app.state.subscriber


@router.get("/positions")
async def get_positions(
    subscriber: DashboardDataSubscriber = Depends(get_subscriber),
) -> List[Dict[str, Any]]:
    """Get current positions.

    Returns:
        List of position objects with:
        - stock_code: Stock code
        - stock_name: Stock name
        - quantity: Quantity held
        - average_buy_price: Average buy price
        - current_price: Current market price
        - evaluation_amount: Total value
        - unrealized_pnl: Unrealized P&L
        - unrealized_pnl_pct: Unrealized P&L percentage
    """
    return await subscriber.get_positions()


@router.get("/portfolio")
async def get_portfolio(
    subscriber: DashboardDataSubscriber = Depends(get_subscriber),
) -> Dict[str, Any]:
    """Get portfolio summary.

    Returns:
        Portfolio object with:
        - total_evaluation: Sum of all position values
        - total_unrealized_pnl: Sum of unrealized P&L
        - daily_realized_pnl: Daily realized P&L
        - cash_balance: Available cash
        - total_asset_value: Cash + evaluation
        - position_count: Number of positions
        - total_return_pct: Total return percentage
    """
    return await subscriber.get_portfolio()


@router.get("/trades")
async def get_trades(
    subscriber: DashboardDataSubscriber = Depends(get_subscriber),
) -> List[Dict[str, Any]]:
    """Get today's trades.

    Returns:
        List of trade objects with:
        - order_id: Order ID
        - stock_code: Stock code
        - stock_name: Stock name
        - order_type: BUY or SELL
        - quantity: Filled quantity
        - filled_price: Fill price
        - filled_at: Fill time
        - strategy_name: Strategy name
        - realized_pnl: Realized P&L (for SELL)
    """
    return await subscriber.get_trades_today()


@router.get("/snapshot")
async def get_snapshot(
    subscriber: DashboardDataSubscriber = Depends(get_subscriber),
) -> Dict[str, Any]:
    """Get full dashboard snapshot.

    Returns:
        Object containing:
        - positions: List of positions
        - portfolio: Portfolio summary
        - trades_today: Today's trades
    """
    return await subscriber.get_snapshot()
