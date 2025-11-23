"""Backtesting engine for strategy validation with historical data."""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from ..config.settings import Settings
from ..models import OrderType, OrderStatus, Stock
from ..models.account import Account
from ..models.order import Order
from ..models.position import Position
from ..models.strategy import BaseStrategy
from ..simulator.kiwoom_simulator import KiwoomSimulator
from ..utils.logger import get_logger

logger = get_logger(__name__)


class BacktestResult:
    """Backtest execution result.

    Attributes:
        strategy_name: Name of the tested strategy.
        start_date: Backtest start date.
        end_date: Backtest end date.
        initial_balance: Initial account balance.
        final_balance: Final account balance.
        total_return: Total return percentage.
        total_trades: Total number of trades executed.
        winning_trades: Number of profitable trades.
        losing_trades: Number of losing trades.
        win_rate: Winning trade percentage.
        max_drawdown: Maximum drawdown percentage.
        sharpe_ratio: Sharpe ratio (annualized).
        orders: List of all executed orders.
    """

    def __init__(
        self,
        strategy_name: str,
        start_date: datetime,
        end_date: datetime,
        initial_balance: Decimal,
    ):
        """Initialize backtest result.

        Args:
            strategy_name: Name of the tested strategy.
            start_date: Backtest start date.
            end_date: Backtest end date.
            initial_balance: Initial account balance.
        """
        self.strategy_name = strategy_name
        self.start_date = start_date
        self.end_date = end_date
        self.initial_balance = initial_balance
        self.final_balance = initial_balance
        self.orders: List[Order] = []

        # Performance metrics
        self.total_return = Decimal("0")
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.win_rate = Decimal("0")
        self.max_drawdown = Decimal("0")
        self.sharpe_ratio = Decimal("0")

        # Track equity curve for metrics calculation
        self._equity_curve: List[Decimal] = []
        self._timestamps: List[datetime] = []

    def add_order(self, order: Order) -> None:
        """Add executed order to results.

        Args:
            order: Executed order.
        """
        self.orders.append(order)
        if order.status == OrderStatus.FILLED:
            self.total_trades += 1

    def record_equity(self, timestamp: datetime, equity: Decimal) -> None:
        """Record equity at a point in time.

        Args:
            timestamp: Current timestamp.
            equity: Total equity (balance + positions value).
        """
        self._equity_curve.append(equity)
        self._timestamps.append(timestamp)

    def calculate_metrics(self) -> None:
        """Calculate performance metrics from collected data."""
        if not self._equity_curve:
            return

        self.final_balance = self._equity_curve[-1]

        # Total return
        if self.initial_balance > 0:
            self.total_return = (
                (self.final_balance - self.initial_balance)
                / self.initial_balance
                * Decimal("100")
            )

        # Win rate (requires tracking individual trade P&L)
        # For now, we approximate by checking order pairs
        if self.total_trades > 0:
            # Simplified: count filled buy and sell orders
            buy_orders = [
                o for o in self.orders
                if o.order_type == OrderType.BUY and o.status == OrderStatus.FILLED
            ]
            sell_orders = [
                o for o in self.orders
                if o.order_type == OrderType.SELL and o.status == OrderStatus.FILLED
            ]

            # Match buy/sell pairs to calculate wins/losses
            # This is simplified - production would track positions properly
            profitable = 0
            for sell in sell_orders:
                matching_buy = next(
                    (b for b in buy_orders if b.stock_code == sell.stock_code),
                    None
                )
                if matching_buy:
                    if sell.filled_price > matching_buy.filled_price:
                        profitable += 1

            self.winning_trades = profitable
            self.losing_trades = len(sell_orders) - profitable

            if len(sell_orders) > 0:
                self.win_rate = (
                    Decimal(str(profitable)) / Decimal(str(len(sell_orders)))
                    * Decimal("100")
                )

        # Maximum drawdown
        peak = self.initial_balance
        max_dd = Decimal("0")

        for equity in self._equity_curve:
            if equity > peak:
                peak = equity
            drawdown = (peak - equity) / peak * Decimal("100")
            if drawdown > max_dd:
                max_dd = drawdown

        self.max_drawdown = max_dd

        # Sharpe ratio (simplified - assumes daily returns)
        if len(self._equity_curve) > 1:
            returns = []
            for i in range(1, len(self._equity_curve)):
                daily_return = (
                    (self._equity_curve[i] - self._equity_curve[i-1])
                    / self._equity_curve[i-1]
                )
                returns.append(float(daily_return))

            if returns:
                import statistics
                avg_return = statistics.mean(returns)
                std_return = statistics.stdev(returns) if len(returns) > 1 else 0

                if std_return > 0:
                    # Annualized Sharpe (assume 252 trading days)
                    sharpe = (avg_return / std_return) * (252 ** 0.5)
                    self.sharpe_ratio = Decimal(str(sharpe))


class BacktestEngine:
    """Engine for backtesting trading strategies with historical data.

    Attributes:
        config: System configuration.
        simulator: KiwoomSimulator instance for execution.
        strategy: Strategy to backtest.
        result: Backtest result object.
    """

    def __init__(
        self,
        config: Settings,
        strategy: BaseStrategy,
        initial_balance: Decimal,
    ):
        """Initialize backtest engine.

        Args:
            config: System configuration.
            strategy: Strategy instance to backtest.
            initial_balance: Initial account balance.
        """
        self.config = config
        self.strategy = strategy
        self.initial_balance = initial_balance

        # Create simulator for execution
        self.simulator = KiwoomSimulator(initial_balance=initial_balance)

        # Backtest result
        self.result: Optional[BacktestResult] = None

    async def run(
        self,
        start_date: datetime,
        end_date: datetime,
        price_data: Dict[str, List[Stock]],
    ) -> BacktestResult:
        """Run backtest for the given period.

        Args:
            start_date: Start date for backtest.
            end_date: End date for backtest.
            price_data: Historical price data.
                        Format: {stock_code: [Stock, Stock, ...]}
                        Each Stock should have timestamp, current_price.

        Returns:
            BacktestResult with performance metrics.
        """
        logger.info(f"Starting backtest: {start_date} to {end_date}")
        logger.info(f"Strategy: {self.strategy.config.strategy_name}")
        logger.info(f"Initial balance: {self.initial_balance:,} KRW")

        # Initialize result
        self.result = BacktestResult(
            strategy_name=self.strategy.config.strategy_name,
            start_date=start_date,
            end_date=end_date,
            initial_balance=self.initial_balance,
        )

        # Collect all timestamps and sort
        all_timestamps = set()
        for stock_code, stocks in price_data.items():
            for stock in stocks:
                if start_date <= stock.timestamp <= end_date:
                    all_timestamps.add(stock.timestamp)

        sorted_timestamps = sorted(all_timestamps)

        if not sorted_timestamps:
            logger.warning("No price data found in the specified date range")
            return self.result

        logger.info(f"Processing {len(sorted_timestamps)} time points...")

        # Simulate trading at each timestamp
        for idx, timestamp in enumerate(sorted_timestamps):
            # Update simulator prices
            current_prices = {}
            for stock_code, stocks in price_data.items():
                # Find the stock data for this timestamp (or most recent)
                stock_at_time = None
                for stock in stocks:
                    if stock.timestamp <= timestamp:
                        stock_at_time = stock
                    else:
                        break

                if stock_at_time:
                    current_prices[stock_code] = stock_at_time.current_price
                    self.simulator.exchange.set_price(
                        stock_code,
                        stock_at_time.current_price
                    )

            # Process pending orders (simulate market tick)
            self.simulator.exchange.tick()

            # Evaluate strategy
            account = await self.simulator.get_account()
            positions = await self.simulator.get_positions()

            # Check buy signals
            for stock_code in price_data.keys():
                if stock_code not in current_prices:
                    continue

                buy_signal = await self.strategy.evaluate_buy_signal(
                    stock_code,
                    self.simulator
                )

                if buy_signal:
                    position_size = await self.strategy.calculate_position_size(
                        stock_code,
                        current_prices[stock_code],
                        account
                    )

                    if position_size > 0:
                        order = Order(
                            order_id=f"BT{idx}_{stock_code}_BUY",
                            stock_code=stock_code,
                            order_type=OrderType.BUY,
                            price=current_prices[stock_code],
                            quantity=position_size,
                            status=OrderStatus.PENDING,
                            timestamp=timestamp,
                        )

                        try:
                            filled_order = await self.simulator.submit_order(order)
                            self.result.add_order(filled_order)
                            logger.debug(
                                f"{timestamp}: BUY {stock_code} "
                                f"{position_size}@{current_prices[stock_code]}"
                            )
                        except Exception as e:
                            logger.debug(f"Buy order failed: {e}")

            # Check sell signals
            for position in positions:
                if position.quantity <= 0:
                    continue

                sell_signal = await self.strategy.evaluate_sell_signal(
                    position.stock_code,
                    self.simulator
                )

                if sell_signal:
                    order = Order(
                        order_id=f"BT{idx}_{position.stock_code}_SELL",
                        stock_code=position.stock_code,
                        order_type=OrderType.SELL,
                        price=position.current_price,
                        quantity=position.quantity,
                        status=OrderStatus.PENDING,
                        timestamp=timestamp,
                    )

                    try:
                        filled_order = await self.simulator.submit_order(order)
                        self.result.add_order(filled_order)
                        logger.debug(
                            f"{timestamp}: SELL {position.stock_code} "
                            f"{position.quantity}@{position.current_price}"
                        )
                    except Exception as e:
                        logger.debug(f"Sell order failed: {e}")

            # Record equity for this timestamp
            account = await self.simulator.get_account()
            self.result.record_equity(timestamp, account.total_value)

            # Progress logging
            if (idx + 1) % 100 == 0:
                logger.info(
                    f"Progress: {idx + 1}/{len(sorted_timestamps)} "
                    f"({(idx + 1) / len(sorted_timestamps) * 100:.1f}%)"
                )

        # Calculate final metrics
        self.result.calculate_metrics()

        logger.info("Backtest completed")
        logger.info(f"  - Total trades: {self.result.total_trades}")
        logger.info(f"  - Final balance: {self.result.final_balance:,} KRW")
        logger.info(f"  - Total return: {self.result.total_return:.2f}%")
        logger.info(f"  - Win rate: {self.result.win_rate:.2f}%")
        logger.info(f"  - Max drawdown: {self.result.max_drawdown:.2f}%")
        logger.info(f"  - Sharpe ratio: {self.result.sharpe_ratio:.2f}")

        return self.result
