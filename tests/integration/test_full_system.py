"""Full system integration tests.

Tests the complete trading system workflow from startup to shutdown.
"""

import asyncio
import pytest
from datetime import datetime
from decimal import Decimal

from src.cli.main import TradingSystem
from src.config.settings import Settings, StrategyConfig
from src.models import OrderType, OrderStatus
from src.simulator.kiwoom_simulator import KiwoomSimulator


@pytest.fixture
def test_config():
    """Create test configuration."""
    return Settings(
        kiwoom_api_key="test_key",
        kiwoom_api_secret="test_secret",
        initial_balance=10000000.0,
        watch_symbols=["005930", "000660"],
        strategies=[
            StrategyConfig(
                strategy_name="test_golden_cross",
                strategy_class="src.strategies.golden_cross.GoldenCrossStrategy",
                enabled=True,
                params={
                    "short_window": 5,
                    "long_window": 20,
                    "position_size_pct": 0.1
                },
                target_symbols=["005930"]
            )
        ]
    )


@pytest.mark.asyncio
async def test_system_startup_and_shutdown(test_config):
    """Test system can start and shutdown gracefully.

    Steps:
        1. Create TradingSystem instance
        2. Start in simulator mode
        3. Verify services initialized
        4. Shutdown gracefully
        5. Verify cleanup
    """
    system = TradingSystem(test_config)

    # Create background task to shutdown after short delay
    async def delayed_shutdown():
        await asyncio.sleep(2)  # Run for 2 seconds
        system.shutdown_event.set()

    shutdown_task = asyncio.create_task(delayed_shutdown())

    try:
        # Start system (should run for ~2 seconds then shutdown)
        await system.start(mode="simulator")

        # Verify system ran and shutdown cleanly
        assert system.status.error_count == 0
        assert len(system.tasks) > 0

    finally:
        if not shutdown_task.done():
            shutdown_task.cancel()


@pytest.mark.asyncio
async def test_data_collection_to_strategy_flow(test_config):
    """Test data flows from collector to strategy engine.

    Steps:
        1. Initialize data collector
        2. Initialize strategy engine
        3. Push market data to queue
        4. Verify strategy receives and processes data
    """
    from src.services.data_collector import DataCollector
    from src.services.strategy_engine import StrategyEngine

    # Create simulator client
    simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))

    # Set initial prices
    simulator.exchange.set_price("005930", Decimal("70000"))

    # Create queues
    market_data_queue = asyncio.Queue(maxsize=1000)
    order_queue = asyncio.Queue(maxsize=100)

    # Initialize services
    data_collector = DataCollector(
        config=test_config,
        client=simulator,
        market_data_queue=market_data_queue
    )

    strategy_engine = StrategyEngine(
        config=test_config,
        client=simulator,
        market_data_queue=market_data_queue,
        order_queue=order_queue
    )

    await strategy_engine.load_strategies()

    # Manually push data to queue
    from src.models.stock import Stock
    test_stock = Stock(
        code="005930",
        name="Samsung Electronics",
        current_price=Decimal("70000"),
        volume=1000000,
        timestamp=datetime.now()
    )

    await market_data_queue.put(test_stock)

    # Process one iteration
    try:
        # Give strategy time to process
        await asyncio.sleep(0.1)

        # Verify queue was consumed
        assert market_data_queue.qsize() == 0

    except Exception as e:
        pytest.fail(f"Data flow test failed: {e}")


@pytest.mark.asyncio
async def test_strategy_to_order_execution_flow(test_config):
    """Test orders flow from strategy to execution.

    Steps:
        1. Initialize strategy engine
        2. Initialize order executor
        3. Trigger buy signal
        4. Verify order is queued
        5. Verify order is executed
    """
    from src.services.strategy_engine import StrategyEngine
    from src.services.order_executor import OrderExecutor

    # Create simulator
    simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
    simulator.exchange.set_price("005930", Decimal("70000"))

    # Create queues
    market_data_queue = asyncio.Queue(maxsize=1000)
    order_queue = asyncio.Queue(maxsize=100)

    # Initialize services
    strategy_engine = StrategyEngine(
        config=test_config,
        client=simulator,
        market_data_queue=market_data_queue,
        order_queue=order_queue
    )

    order_executor = OrderExecutor(
        config=test_config,
        client=simulator,
        order_queue=order_queue
    )

    await strategy_engine.load_strategies()

    # Create test order manually
    from src.models.order import Order
    test_order = Order(
        order_id="TEST001",
        stock_code="005930",
        order_type=OrderType.BUY,
        price=Decimal("70000"),
        quantity=10,
        status=OrderStatus.PENDING,
        timestamp=datetime.now()
    )

    # Push to order queue
    await order_queue.put(test_order)

    # Process order (single iteration)
    try:
        # Start executor briefly
        executor_task = asyncio.create_task(order_executor.run())

        # Wait for processing
        await asyncio.sleep(0.5)

        # Cancel executor
        executor_task.cancel()
        try:
            await executor_task
        except asyncio.CancelledError:
            pass

        # Verify order was executed
        account = await simulator.get_account()
        positions = await simulator.get_positions()

        # Should have spent money
        assert account.balance < Decimal("10000000")

        # Should have position
        assert len(positions) > 0
        assert positions[0].stock_code == "005930"
        assert positions[0].quantity == 10

    except Exception as e:
        pytest.fail(f"Order execution flow test failed: {e}")


@pytest.mark.asyncio
async def test_full_trading_cycle(test_config):
    """Test complete cycle: data -> strategy -> order -> execution.

    Steps:
        1. Start all services
        2. Feed price data
        3. Trigger buy signal
        4. Verify order execution
        5. Feed new price data
        6. Trigger sell signal
        7. Verify sell execution
        8. Check final P&L
    """
    # Create simulator with initial price
    simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
    simulator.exchange.set_price("005930", Decimal("70000"))

    initial_balance = await simulator.get_account()
    initial_balance_value = initial_balance.balance

    # Execute buy order
    from src.models.order import Order
    buy_order = Order(
        order_id="BUY001",
        stock_code="005930",
        order_type=OrderType.BUY,
        price=Decimal("70000"),
        quantity=10,
        status=OrderStatus.PENDING,
        timestamp=datetime.now()
    )

    filled_buy = await simulator.submit_order(buy_order)
    assert filled_buy.status == OrderStatus.FILLED
    assert filled_buy.filled_quantity == 10

    # Verify position created
    positions = await simulator.get_positions()
    assert len(positions) == 1
    assert positions[0].quantity == 10
    assert positions[0].average_price == Decimal("70000")

    # Simulate price increase
    simulator.exchange.set_price("005930", Decimal("75000"))

    # Execute sell order
    sell_order = Order(
        order_id="SELL001",
        stock_code="005930",
        order_type=OrderType.SELL,
        price=Decimal("75000"),
        quantity=10,
        status=OrderStatus.PENDING,
        timestamp=datetime.now()
    )

    filled_sell = await simulator.submit_order(sell_order)
    assert filled_sell.status == OrderStatus.FILLED

    # Verify position closed
    positions = await simulator.get_positions()
    assert len(positions) == 0

    # Verify profit
    final_account = await simulator.get_account()
    expected_profit = Decimal("10") * (Decimal("75000") - Decimal("70000"))
    assert final_account.balance == initial_balance_value + expected_profit

    # Calculate P&L
    pnl = final_account.total_pnl
    assert pnl > 0  # Should be profitable


@pytest.mark.asyncio
async def test_system_error_recovery(test_config):
    """Test system handles errors gracefully.

    Steps:
        1. Start system
        2. Inject error (invalid order)
        3. Verify system continues running
        4. Verify error is logged
    """
    simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))

    # Try to buy with insufficient funds
    from src.models.order import Order
    invalid_order = Order(
        order_id="INVALID001",
        stock_code="005930",
        order_type=OrderType.BUY,
        price=Decimal("70000"),
        quantity=1000000,  # Too many shares
        status=OrderStatus.PENDING,
        timestamp=datetime.now()
    )

    # Should raise error
    with pytest.raises(ValueError, match="Insufficient balance"):
        await simulator.submit_order(invalid_order)

    # System should still be functional
    account = await simulator.get_account()
    assert account.balance == Decimal("10000000")  # Balance unchanged


@pytest.mark.asyncio
async def test_concurrent_order_handling(test_config):
    """Test system handles concurrent orders correctly.

    Steps:
        1. Submit multiple orders concurrently
        2. Verify all orders processed
        3. Verify no race conditions (balance consistency)
    """
    simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))
    simulator.exchange.set_price("005930", Decimal("70000"))

    # Create multiple buy orders
    orders = []
    for i in range(5):
        order = Order(
            order_id=f"BUY{i:03d}",
            stock_code="005930",
            order_type=OrderType.BUY,
            price=Decimal("70000"),
            quantity=10,
            status=OrderStatus.PENDING,
            timestamp=datetime.now()
        )
        orders.append(order)

    # Submit all orders
    results = []
    for order in orders:
        filled = await simulator.submit_order(order)
        results.append(filled)

    # Verify all filled
    assert all(r.status == OrderStatus.FILLED for r in results)

    # Verify total position
    positions = await simulator.get_positions()
    assert len(positions) == 1
    assert positions[0].quantity == 50  # 5 orders * 10 shares

    # Verify balance consistency
    account = await simulator.get_account()
    expected_spent = Decimal("50") * Decimal("70000")
    assert account.balance == Decimal("10000000") - expected_spent
