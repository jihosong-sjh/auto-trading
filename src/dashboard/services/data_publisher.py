"""Dashboard Data Publisher - Trading System to Redis.

Publishes real-time trading data (positions, portfolio, trades, pending orders) to Redis
for consumption by the dashboard WebSocket server.
"""

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from ...cache.shared_data import SharedDataManager
from ...cache.redis_manager import RedisManager
from ...models.position import Position
from ...models.account import Account
from ...models.order import Order
from ...models.stock import get_kst_now
from ...utils.logger import get_logger
from ..models import (
    DashboardPosition,
    DashboardPortfolio,
    DashboardTrade,
    DashboardSnapshot,
    DashboardPendingOrder,
    OrderStatusChangedData,
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


class DashboardDataPublisher:
    """Publishes trading data to Redis for dashboard consumption.

    This service runs as a background task in the trading system and:
    1. Periodically publishes position/portfolio snapshots to Redis
    2. Publishes real-time events (price updates, trade executions, order status)
    3. Maintains shared state for dashboard REST API queries

    Redis Channels:
    - pubsub:dashboard_snapshot - Full snapshot on request
    - pubsub:position_update - Position/price updates
    - pubsub:portfolio_update - Portfolio summary updates
    - pubsub:trade_executed - Trade execution events
    - pubsub:pending_orders_update - Pending orders updates
    - pubsub:order_status_changed - Individual order status changes

    Redis Keys:
    - shared_state:dashboard:positions - Current positions (JSON)
    - shared_state:dashboard:portfolio - Portfolio summary (JSON)
    - shared_state:dashboard:trades_today - Today's trades (JSON list)
    - shared_state:dashboard:pending_orders - Pending orders (JSON list)
    """

    # Channel names (without pubsub: prefix)
    CHANNEL_SNAPSHOT = "dashboard_snapshot"
    CHANNEL_POSITION_UPDATE = "position_update"
    CHANNEL_PORTFOLIO_UPDATE = "portfolio_update"
    CHANNEL_TRADE_EXECUTED = "trade_executed"
    CHANNEL_PENDING_ORDERS_UPDATE = "pending_orders_update"
    CHANNEL_ORDER_STATUS_CHANGED = "order_status_changed"

    # State keys (without shared_state: prefix)
    STATE_POSITIONS = "dashboard:positions"
    STATE_PORTFOLIO = "dashboard:portfolio"
    STATE_TRADES_TODAY = "dashboard:trades_today"
    STATE_PENDING_ORDERS = "dashboard:pending_orders"

    def __init__(
        self,
        redis_manager: RedisManager,
        positions: Dict[str, Position],
        account: Optional[Account] = None,
        pending_orders: Optional[Dict[str, Order]] = None,
        stock_info_cache: Optional[Any] = None,
        publish_interval: float = 1.0,
    ):
        """Initialize DashboardDataPublisher.

        Args:
            redis_manager: Redis manager instance
            positions: Reference to trading system's positions dict
            account: Reference to account information
            pending_orders: Reference to pending orders dict (order_id -> Order)
            stock_info_cache: StockInfoCache instance for stock name lookup
            publish_interval: How often to publish updates (seconds)
        """
        self.shared_data = SharedDataManager(redis_manager, process_id="dashboard_publisher")
        self.positions = positions
        self.account = account
        self.pending_orders = pending_orders or {}
        self.stock_info_cache = stock_info_cache
        self.publish_interval = publish_interval

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._trades_today: List[DashboardTrade] = []

        # Track last published state to avoid redundant updates
        self._last_positions_hash: Optional[str] = None
        self._last_portfolio_hash: Optional[str] = None
        self._last_pending_orders_hash: Optional[str] = None

    async def start(self) -> None:
        """Start the publisher background task."""
        if self._running:
            logger.warning("DashboardDataPublisher already running")
            return

        await self.shared_data.initialize()
        self._running = True
        self._task = asyncio.create_task(self._publish_loop())
        logger.info("DashboardDataPublisher started")

    async def stop(self) -> None:
        """Stop the publisher background task."""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        await self.shared_data.close()
        logger.info("DashboardDataPublisher stopped")

    def update_account(self, account: Account) -> None:
        """Update account reference.

        Args:
            account: New account instance
        """
        self.account = account

    def set_pending_orders(self, pending_orders: Dict[str, Order]) -> None:
        """Set pending orders reference.

        Args:
            pending_orders: Reference to pending orders dict
        """
        self.pending_orders = pending_orders

    def set_stock_info_cache(self, cache: Any) -> None:
        """Set stock info cache.

        Args:
            cache: StockInfoCache instance
        """
        self.stock_info_cache = cache
        logger.info("DashboardDataPublisher stock_info_cache updated")

    def _get_stock_name(self, stock_code: str) -> str:
        """Get stock name from cache (sync).

        Args:
            stock_code: Stock code

        Returns:
            Stock name or empty string if not cached
        """
        if self.stock_info_cache is not None:
            return self.stock_info_cache.get_sync(stock_code)
        return ""

    async def _get_stock_name_async(self, stock_code: str) -> str:
        """Get stock name from cache (async, may call API).

        Args:
            stock_code: Stock code

        Returns:
            Stock name or empty string if not found
        """
        if self.stock_info_cache is not None:
            return await self.stock_info_cache.get(stock_code)
        return ""

    async def publish_trade(self, order: Order, realized_pnl: Optional[Decimal] = None) -> None:
        """Publish a trade execution event.

        Called by OrderExecutor when an order is filled.

        Args:
            order: Filled order
            realized_pnl: Realized P&L for SELL orders
        """
        order_type_val = order.order_type.value if hasattr(order.order_type, 'value') else order.order_type

        # Get stock name from cache
        stock_name = await self._get_stock_name_async(order.stock_code)

        trade = DashboardTrade(
            order_id=order.order_id,
            stock_code=order.stock_code,
            stock_name=stock_name,
            order_type=order_type_val,
            quantity=order.filled_quantity,
            filled_price=order.filled_price or order.price,
            filled_at=order.filled_at or get_kst_now(),
            strategy_name=order.strategy_name,
            realized_pnl=realized_pnl,
        )

        # Add to today's trades
        self._trades_today.append(trade)

        # Publish trade event
        await self.shared_data.publish(
            self.CHANNEL_TRADE_EXECUTED,
            {
                "type": WSMessageType.TRADE_EXECUTED.value,
                "data": trade.model_dump(mode="json"),
                "timestamp": get_kst_now().isoformat(),
            },
        )

        # Update trades state
        await self._publish_trades_state()

        order_type_log = order.order_type.value if hasattr(order.order_type, 'value') else order.order_type
        logger.debug(f"Published trade: {order.order_id} {order_type_log} {order.stock_code}")

    async def publish_order_status_changed(
        self,
        order: Order,
        previous_status: str,
    ) -> None:
        """Publish an order status change event.

        Called when an order's status changes (submitted, partially filled, etc.)

        Args:
            order: Order with updated status
            previous_status: Previous status value
        """
        order_type_val = order.order_type.value if hasattr(order.order_type, 'value') else order.order_type
        status_val = order.status.value if hasattr(order.status, 'value') else order.status

        # Get stock name from cache
        stock_name = await self._get_stock_name_async(order.stock_code)

        status_changed_data = OrderStatusChangedData(
            order_id=order.order_id,
            stock_code=order.stock_code,
            stock_name=stock_name,
            order_type=order_type_val,
            status=status_val,
            previous_status=previous_status,
            quantity=order.quantity,
            filled_quantity=order.filled_quantity,
            filled_price=order.filled_price,
            changed_at=get_kst_now(),
        )

        await self.shared_data.publish(
            self.CHANNEL_ORDER_STATUS_CHANGED,
            {
                "type": WSMessageType.ORDER_STATUS_CHANGED.value,
                "data": status_changed_data.model_dump(mode="json"),
                "timestamp": get_kst_now().isoformat(),
            },
        )

        logger.debug(
            f"Published order status change: {order.order_id} "
            f"{previous_status} -> {status_val}"
        )

    async def publish_pending_orders_update(self) -> None:
        """Publish current pending orders to Redis."""
        pending_orders = self._build_pending_orders()

        await self.shared_data.publish(
            self.CHANNEL_PENDING_ORDERS_UPDATE,
            {
                "type": WSMessageType.PENDING_ORDERS_UPDATE.value,
                "data": [p.model_dump(mode="json") for p in pending_orders],
                "timestamp": get_kst_now().isoformat(),
            },
        )

        # Also update state
        await self.shared_data.set_state(
            self.STATE_PENDING_ORDERS,
            [p.model_dump(mode="json") for p in pending_orders],
            broadcast=False,
        )

        logger.debug(f"Published pending orders update: {len(pending_orders)} orders")

    async def publish_price_update(self, stock_code: str, price: Decimal) -> None:
        """Publish a price update for a position.

        Args:
            stock_code: Stock code
            price: New price
        """
        if stock_code not in self.positions:
            return

        position = self.positions[stock_code]
        position.update_price(price)

        # Publish position update
        await self.shared_data.publish(
            self.CHANNEL_POSITION_UPDATE,
            {
                "type": WSMessageType.POSITION_UPDATE.value,
                "data": {
                    "stock_code": stock_code,
                    "current_price": str(price),
                    "unrealized_pnl": str(position.unrealized_pnl),
                    "unrealized_pnl_pct": str(position.return_rate * 100),
                    "evaluation_amount": str(position.evaluation_amount),
                },
                "timestamp": get_kst_now().isoformat(),
            },
        )

    async def request_snapshot(self) -> DashboardSnapshot:
        """Generate and return current dashboard snapshot.

        Returns:
            DashboardSnapshot with current positions, portfolio, trades, and pending orders
        """
        positions = self._build_positions()
        portfolio = self._build_portfolio(positions)
        pending_orders = self._build_pending_orders()

        return DashboardSnapshot(
            positions=positions,
            portfolio=portfolio,
            trades_today=self._trades_today.copy(),
            pending_orders=pending_orders,
        )

    async def _publish_loop(self) -> None:
        """Main publish loop - runs periodically."""
        try:
            while self._running:
                try:
                    await self._publish_snapshot()
                    await self._publish_pending_orders_if_changed()
                except Exception as e:
                    logger.error(f"Error publishing dashboard data: {e}")

                await asyncio.sleep(self.publish_interval)

        except asyncio.CancelledError:
            logger.debug("Publish loop cancelled")
            raise

    async def _publish_snapshot(self) -> None:
        """Publish current state to Redis."""
        positions = self._build_positions()
        portfolio = self._build_portfolio(positions)

        # Check if positions changed
        positions_json = json.dumps(
            [p.model_dump(mode="json") for p in positions],
            cls=DecimalEncoder,
            sort_keys=True,
        )
        positions_hash = hash(positions_json)

        if positions_hash != self._last_positions_hash:
            # Positions changed - publish update
            await self.shared_data.set_state(
                self.STATE_POSITIONS,
                [p.model_dump(mode="json") for p in positions],
                broadcast=False,
            )
            self._last_positions_hash = positions_hash

        # Check if portfolio changed
        portfolio_json = json.dumps(portfolio.model_dump(mode="json"), cls=DecimalEncoder, sort_keys=True)
        portfolio_hash = hash(portfolio_json)

        if portfolio_hash != self._last_portfolio_hash:
            # Portfolio changed - publish update
            await self.shared_data.set_state(
                self.STATE_PORTFOLIO,
                portfolio.model_dump(mode="json"),
                broadcast=False,
            )

            # Publish portfolio update event
            await self.shared_data.publish(
                self.CHANNEL_PORTFOLIO_UPDATE,
                {
                    "type": WSMessageType.PORTFOLIO_UPDATE.value,
                    "data": portfolio.model_dump(mode="json"),
                    "timestamp": get_kst_now().isoformat(),
                },
            )

            self._last_portfolio_hash = portfolio_hash

    async def _publish_pending_orders_if_changed(self) -> None:
        """Publish pending orders if changed."""
        pending_orders = self._build_pending_orders()

        pending_orders_json = json.dumps(
            [p.model_dump(mode="json") for p in pending_orders],
            cls=DecimalEncoder,
            sort_keys=True,
        )
        pending_orders_hash = hash(pending_orders_json)

        if pending_orders_hash != self._last_pending_orders_hash:
            await self.shared_data.set_state(
                self.STATE_PENDING_ORDERS,
                [p.model_dump(mode="json") for p in pending_orders],
                broadcast=False,
            )

            # Publish pending orders update event
            await self.shared_data.publish(
                self.CHANNEL_PENDING_ORDERS_UPDATE,
                {
                    "type": WSMessageType.PENDING_ORDERS_UPDATE.value,
                    "data": [p.model_dump(mode="json") for p in pending_orders],
                    "timestamp": get_kst_now().isoformat(),
                },
            )

            self._last_pending_orders_hash = pending_orders_hash

    async def _publish_trades_state(self) -> None:
        """Publish trades state to Redis."""
        await self.shared_data.set_state(
            self.STATE_TRADES_TODAY,
            [t.model_dump(mode="json") for t in self._trades_today],
            broadcast=False,
        )

    def _build_positions(self) -> List[DashboardPosition]:
        """Build list of DashboardPosition from trading positions.

        Returns:
            List of DashboardPosition (only positions with quantity > 0)
        """
        result = []
        for stock_code, pos in self.positions.items():
            # Skip positions with zero quantity (fully closed positions)
            if pos.quantity <= 0:
                continue

            # Skip positions with zero average buy price (invalid state)
            if pos.average_buy_price <= 0:
                continue

            # Get stock name from cache (sync)
            stock_name = self._get_stock_name(stock_code)

            dashboard_pos = DashboardPosition(
                stock_code=pos.stock_code,
                stock_name=stock_name,
                quantity=pos.quantity,
                average_buy_price=pos.average_buy_price,
                current_price=pos.current_price,
                strategy_name=pos.strategy_name,
                updated_at=pos.updated_at,
            )
            result.append(dashboard_pos)

        return result

    def _build_pending_orders(self) -> List[DashboardPendingOrder]:
        """Build list of DashboardPendingOrder from pending orders.

        Returns:
            List of DashboardPendingOrder
        """
        result = []
        for order_id, order in self.pending_orders.items():
            order_type_val = order.order_type.value if hasattr(order.order_type, 'value') else order.order_type
            price_type_val = order.price_type.value if hasattr(order.price_type, 'value') else order.price_type
            status_val = order.status.value if hasattr(order.status, 'value') else order.status

            # Get stock name from cache (sync)
            stock_name = self._get_stock_name(order.stock_code)

            pending_order = DashboardPendingOrder(
                order_id=order.order_id,
                stock_code=order.stock_code,
                stock_name=stock_name,
                order_type=order_type_val,
                price_type=price_type_val,
                quantity=order.quantity,
                limit_price=order.limit_price,
                filled_quantity=order.filled_quantity,
                filled_price=order.filled_price,
                status=status_val,
                strategy_name=order.strategy_name,
                submitted_at=order.submitted_at,
                created_at=order.created_at,
            )
            result.append(pending_order)

        return result

    def _build_portfolio(self, positions: List[DashboardPosition]) -> DashboardPortfolio:
        """Build DashboardPortfolio from positions and account.

        Args:
            positions: List of dashboard positions

        Returns:
            DashboardPortfolio
        """
        total_evaluation = sum(p.evaluation_amount for p in positions)
        total_unrealized_pnl = sum(p.unrealized_pnl for p in positions)

        cash_balance = Decimal("0")
        daily_realized_pnl = Decimal("0")

        if self.account:
            cash_balance = self.account.cash_balance
            daily_realized_pnl = self.account.daily_pnl

        total_asset_value = cash_balance + total_evaluation

        return DashboardPortfolio(
            total_evaluation=total_evaluation,
            total_unrealized_pnl=total_unrealized_pnl,
            daily_realized_pnl=daily_realized_pnl,
            cash_balance=cash_balance,
            total_asset_value=total_asset_value,
            position_count=len(positions),
            updated_at=get_kst_now(),
        )

    def clear_today_trades(self) -> None:
        """Clear today's trade history. Called at market open."""
        self._trades_today.clear()
        logger.info("Cleared today's trade history")
