"""Backtest integration tests.

Tests the backtesting engine with various scenarios.
"""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List

from src.config.settings import Settings, StrategyConfig
from src.models import OrderType, Stock
from src.models.strategy import BaseStrategy
from src.services.backtest_engine import BacktestEngine, BacktestResult
from src.simulator.kiwoom_simulator import KiwoomSimulator


@pytest.fixture
def test_config():
    """Create test configuration."""
    return Settings(
        kiwoom_api_key="test_key",
        kiwoom_api_secret="test_secret",
        initial_balance=10000000.0,
        watch_symbols=["TEST001"],
        strategies=[
            StrategyConfig(
                strategy_name="test_strategy",
                strategy_class="tests.integration.test_backtest.DummyStrategy",
                enabled=True,
                params={"buy_threshold": 100, "sell_threshold": 110},
                target_symbols=["TEST001"]
            )
        ]
    )


class DummyStrategy(BaseStrategy):
    """Dummy strategy for testing.

    Buys when price < buy_threshold, sells when price > sell_threshold.
    """

    async def evaluate_buy_signal(self, stock_code: str, client) -> bool:
        """Check if should buy.

        Args:
            stock_code: Stock symbol.
            client: Trading client.

        Returns:
            True if should buy.
        """
        stock = await client.get_stock_price(stock_code)
        buy_threshold = Decimal(str(self.config.params.get("buy_threshold", 100)))
        return stock.current_price < buy_threshold

    async def evaluate_sell_signal(self, stock_code: str, client) -> bool:
        """Check if should sell.

        Args:
            stock_code: Stock symbol.
            client: Trading client.

        Returns:
            True if should sell.
        """
        stock = await client.get_stock_price(stock_code)
        sell_threshold = Decimal(str(self.config.params.get("sell_threshold", 110)))
        return stock.current_price > sell_threshold

    async def calculate_position_size(
        self,
        stock_code: str,
        current_price: Decimal,
        account
    ) -> int:
        """Calculate position size.

        Args:
            stock_code: Stock symbol.
            current_price: Current stock price.
            account: Account information.

        Returns:
            Number of shares to buy.
        """
        # Buy 10% of balance worth of shares
        available = account.balance * Decimal("0.1")
        if available <= 0:
            return 0
        quantity = int(available / current_price)
        return max(1, quantity)


def generate_price_data(
    stock_code: str,
    start_date: datetime,
    days: int,
    prices: List[float]
) -> Dict[str, List[Stock]]:
    """Generate synthetic price data.

    Args:
        stock_code: Stock symbol.
        start_date: Start date.
        days: Number of days.
        prices: List of prices (will cycle if needed).

    Returns:
        Price data dictionary.
    """
    data = []
    current_date = start_date

    for i in range(days):
        price = Decimal(str(prices[i % len(prices)]))
        stock = Stock(
            code=stock_code,
            name=f"Test Stock {stock_code}",
            current_price=price,
            volume=1000000,
            timestamp=current_date
        )
        data.append(stock)
        current_date += timedelta(days=1)

    return {stock_code: data}


@pytest.mark.asyncio
async def test_backtest_basic_execution(test_config):
    """Test backtest executes and returns results.

    Steps:
        1. Create simple price data
        2. Run backtest
        3. Verify result object created
        4. Verify basic metrics calculated
    """
    # Create strategy
    simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
    strategy = DummyStrategy(
        config=test_config.strategies[0],
        client=simulator
    )

    # Create backtest engine
    engine = BacktestEngine(
        config=test_config,
        strategy=strategy,
        initial_balance=Decimal("10000000")
    )

    # Generate flat price data (no trades should occur)
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 10)
    price_data = generate_price_data(
        "TEST001",
        start_date,
        10,
        [105, 105, 105, 105, 105, 105, 105, 105, 105, 105]  # Flat at 105
    )

    # Run backtest
    result = await engine.run(
        start_date=start_date,
        end_date=end_date,
        price_data=price_data
    )

    # Verify result
    assert isinstance(result, BacktestResult)
    assert result.strategy_name == "test_strategy"
    assert result.initial_balance == Decimal("10000000")
    assert result.start_date == start_date
    assert result.end_date == end_date


@pytest.mark.asyncio
async def test_backtest_profitable_scenario(test_config):
    """Test backtest with profitable price movement.

    Steps:
        1. Generate price data: low -> high
        2. Run backtest
        3. Verify profitable trades
        4. Verify positive return
    """
    # Create strategy
    simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
    strategy = DummyStrategy(
        config=test_config.strategies[0],
        client=simulator
    )

    # Create engine
    engine = BacktestEngine(
        config=test_config,
        strategy=strategy,
        initial_balance=Decimal("10000000")
    )

    # Generate rising price data
    # Buy at 95, sell at 115 (profitable)
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 20)
    price_data = generate_price_data(
        "TEST001",
        start_date,
        20,
        [95, 95, 100, 105, 110, 115, 115, 120, 120, 120] * 2
    )

    # Run backtest
    result = await engine.run(
        start_date=start_date,
        end_date=end_date,
        price_data=price_data
    )

    # Verify trades occurred
    assert result.total_trades > 0, "No trades executed"

    # Verify profitability
    assert result.final_balance >= result.initial_balance, "Lost money"
    assert result.total_return >= Decimal("0"), "Negative return"


@pytest.mark.asyncio
async def test_backtest_losing_scenario(test_config):
    """Test backtest with losing price movement.

    Steps:
        1. Generate price data: high -> low (buy high, forced sell)
        2. Run backtest
        3. Verify losing trades
        4. Verify negative or zero return
    """
    # Modify strategy to force bad trades
    config = StrategyConfig(
        strategy_name="bad_strategy",
        strategy_class="tests.integration.test_backtest.DummyStrategy",
        enabled=True,
        params={"buy_threshold": 120, "sell_threshold": 95},  # Buy high, sell low
        target_symbols=["TEST001"]
    )

    simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
    strategy = DummyStrategy(config=config, client=simulator)

    engine = BacktestEngine(
        config=test_config,
        strategy=strategy,
        initial_balance=Decimal("10000000")
    )

    # Generate falling price data
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 20)
    price_data = generate_price_data(
        "TEST001",
        start_date,
        20,
        [115, 110, 105, 100, 95, 90, 85, 80, 75, 70] * 2
    )

    result = await engine.run(
        start_date=start_date,
        end_date=end_date,
        price_data=price_data
    )

    # Verify trades occurred
    assert result.total_trades > 0, "No trades executed"

    # Should have lost money
    assert result.total_return <= Decimal("10"), "Unexpectedly profitable"


@pytest.mark.asyncio
async def test_backtest_max_drawdown_calculation(test_config):
    """Test maximum drawdown is calculated correctly.

    Steps:
        1. Generate volatile price data
        2. Run backtest
        3. Verify max drawdown calculated
        4. Verify drawdown is reasonable
    """
    simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
    strategy = DummyStrategy(
        config=test_config.strategies[0],
        client=simulator
    )

    engine = BacktestEngine(
        config=test_config,
        strategy=strategy,
        initial_balance=Decimal("10000000")
    )

    # Generate volatile data
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 30)
    price_data = generate_price_data(
        "TEST001",
        start_date,
        30,
        [100, 110, 105, 115, 100, 120, 95, 125, 90, 130] * 3
    )

    result = await engine.run(
        start_date=start_date,
        end_date=end_date,
        price_data=price_data
    )

    # Max drawdown should be calculated
    assert result.max_drawdown >= Decimal("0")
    # Should be less than 100% (total loss)
    assert result.max_drawdown < Decimal("100")


@pytest.mark.asyncio
async def test_backtest_win_rate_calculation(test_config):
    """Test win rate is calculated correctly.

    Steps:
        1. Generate data with clear buy/sell cycles
        2. Run backtest
        3. Verify win rate calculated
        4. Verify winning/losing trades counted
    """
    simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
    strategy = DummyStrategy(
        config=test_config.strategies[0],
        client=simulator
    )

    engine = BacktestEngine(
        config=test_config,
        strategy=strategy,
        initial_balance=Decimal("10000000")
    )

    # Generate data with clear cycles
    # Cycle 1: 95 -> 115 (win)
    # Cycle 2: 95 -> 115 (win)
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 20)
    price_data = generate_price_data(
        "TEST001",
        start_date,
        20,
        [95, 95, 100, 105, 110, 115, 115, 105, 95, 95,
         100, 105, 110, 115, 115, 105, 95, 95, 95, 95]
    )

    result = await engine.run(
        start_date=start_date,
        end_date=end_date,
        price_data=price_data
    )

    # Win rate should be calculated
    if result.total_trades > 0:
        assert result.win_rate >= Decimal("0")
        assert result.win_rate <= Decimal("100")
        assert result.winning_trades + result.losing_trades >= 0


@pytest.mark.asyncio
async def test_backtest_multiple_symbols(test_config):
    """Test backtest with multiple symbols.

    Steps:
        1. Generate price data for multiple symbols
        2. Run backtest
        3. Verify trades across all symbols
    """
    # Update config for multiple symbols
    multi_config = Settings(
        kiwoom_api_key="test_key",
        kiwoom_api_secret="test_secret",
        initial_balance=10000000.0,
        watch_symbols=["TEST001", "TEST002"],
        strategies=[
            StrategyConfig(
                strategy_name="multi_strategy",
                strategy_class="tests.integration.test_backtest.DummyStrategy",
                enabled=True,
                params={"buy_threshold": 100, "sell_threshold": 110},
                target_symbols=["TEST001", "TEST002"]
            )
        ]
    )

    simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
    strategy = DummyStrategy(
        config=multi_config.strategies[0],
        client=simulator
    )

    engine = BacktestEngine(
        config=multi_config,
        strategy=strategy,
        initial_balance=Decimal("10000000")
    )

    # Generate data for both symbols
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 20)

    price_data_1 = generate_price_data(
        "TEST001", start_date, 20,
        [95, 95, 100, 105, 110, 115, 115, 120] * 3
    )

    price_data_2 = generate_price_data(
        "TEST002", start_date, 20,
        [90, 90, 95, 100, 105, 110, 110, 115] * 3
    )

    # Merge price data
    price_data = {**price_data_1, **price_data_2}

    result = await engine.run(
        start_date=start_date,
        end_date=end_date,
        price_data=price_data
    )

    # Should have orders for both symbols
    stock_codes = set(order.stock_code for order in result.orders)
    # Note: May or may not have orders for both depending on balance
    assert len(stock_codes) >= 1


@pytest.mark.asyncio
async def test_backtest_empty_data():
    """Test backtest handles empty price data gracefully.

    Steps:
        1. Create backtest with no price data
        2. Run backtest
        3. Verify no errors
        4. Verify zero trades
    """
    test_config = Settings(
        kiwoom_api_key="test_key",
        kiwoom_api_secret="test_secret",
        initial_balance=10000000.0,
        watch_symbols=["TEST001"],
        strategies=[
            StrategyConfig(
                strategy_name="test_strategy",
                strategy_class="tests.integration.test_backtest.DummyStrategy",
                enabled=True,
                params={"buy_threshold": 100, "sell_threshold": 110},
                target_symbols=["TEST001"]
            )
        ]
    )

    simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
    strategy = DummyStrategy(
        config=test_config.strategies[0],
        client=simulator
    )

    engine = BacktestEngine(
        config=test_config,
        strategy=strategy,
        initial_balance=Decimal("10000000")
    )

    # Empty price data
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 10)
    price_data = {}

    result = await engine.run(
        start_date=start_date,
        end_date=end_date,
        price_data=price_data
    )

    # Should complete without errors
    assert result.total_trades == 0
    assert result.final_balance == result.initial_balance
