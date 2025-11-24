"""Kiwoom Auto-Trading CLI main entry point."""

import argparse
import asyncio
import json
import signal
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

from ..config.settings import Settings
from ..models import SystemMode
from ..models.stock import Stock
from ..models.system_status import SystemStatus
from ..services.data_collector import DataCollector
from ..services.order_executor import OrderExecutor
from ..services.strategy_engine import StrategyEngine
from ..utils.logger import get_logger

logger = get_logger(__name__)


class TradingSystem:
    """Main trading system orchestrator.

    Integrates all services (data collection, strategy execution, order management)
    into a unified system with graceful shutdown support.

    Attributes:
        config: System configuration.
        market_data_queue: Queue for real-time market data.
        order_queue: Queue for order execution requests.
        shutdown_event: Event to signal system shutdown.
        status: Current system status.
        data_collector: Data collection service.
        strategy_engine: Strategy evaluation engine.
        order_executor: Order execution service.
        tasks: List of running background tasks.
    """

    def __init__(self, config: Settings):
        """Initialize trading system with configuration.

        Args:
            config: System configuration settings.
        """
        self.config = config

        # Asyncio primitives for coordination
        self.market_data_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.order_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.shutdown_event: asyncio.Event = asyncio.Event()

        # System status
        self.status = SystemStatus(system_mode=SystemMode.STARTING)

        # Services
        self.data_collector: Optional[DataCollector] = None
        self.strategy_engine: Optional[StrategyEngine] = None
        self.order_executor: Optional[OrderExecutor] = None

        # Background tasks
        self.tasks: list[asyncio.Task] = []

        # Setup signal handlers
        self._setup_signal_handlers()

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Not in async context yet, will setup later
            return

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.create_task(
                    self._handle_signal(s)
                )
            )

    async def _handle_signal(self, sig: signal.Signals) -> None:
        """Handle shutdown signals.

        Args:
            sig: Signal received.
        """
        logger.info(f"Received signal {sig.name}, initiating shutdown...")
        self.shutdown_event.set()

    async def start(self, mode: str = "simulator") -> None:
        """Start the trading system.

        Args:
            mode: Operational mode ("simulator" or "live").
        """
        try:
            logger.info(f"Starting trading system in {mode} mode...")

            # Setup signal handlers again (now in async context)
            self._setup_signal_handlers()

            # Initialize services
            await self._initialize_services(mode)

            # Update status
            self.status.system_mode = SystemMode.RUNNING
            logger.info("Trading system started successfully")

            # Start background services
            await self._start_background_tasks()

            # Wait for shutdown signal
            await self.shutdown_event.wait()

        except Exception as e:
            logger.error(f"Error starting trading system: {e}", exc_info=True)
            self.status.system_mode = SystemMode.ERROR
            self.status.record_error(str(e))
            raise
        finally:
            await self.shutdown()

    async def _initialize_services(self, mode: str) -> None:
        """Initialize all trading services.

        Args:
            mode: Operational mode ("simulator" or "live").
        """
        # Create appropriate client based on mode
        if mode == "simulator":
            from ..simulator.kiwoom_simulator import KiwoomSimulator
            initial_balance = Decimal(str(self.config.initial_balance))
            client = KiwoomSimulator(initial_balance=initial_balance)
            logger.info(f"Initialized simulator with balance: {initial_balance:,} KRW")
        else:
            from ..api.kiwoom_client import KiwoomClient
            client = KiwoomClient(
                api_key=self.config.kiwoom_api_key,
                api_secret=self.config.kiwoom_api_secret
            )
            logger.info("Initialized live Kiwoom API client")

        # Initialize services
        self.data_collector = DataCollector(
            config=self.config,
            client=client,
            market_data_queue=self.market_data_queue
        )

        self.strategy_engine = StrategyEngine(
            config=self.config,
            client=client,
            market_data_queue=self.market_data_queue,
            order_queue=self.order_queue
        )

        self.order_executor = OrderExecutor(
            config=self.config,
            client=client,
            order_queue=self.order_queue
        )

        # Load strategies
        await self.strategy_engine.load_strategies()
        logger.info(
            f"Loaded {len(self.strategy_engine.strategies)} strategies"
        )

    async def _start_background_tasks(self) -> None:
        """Start all background service tasks."""
        if self.data_collector:
            task = asyncio.create_task(
                self.data_collector.run(),
                name="data_collector"
            )
            self.tasks.append(task)

        if self.strategy_engine:
            task = asyncio.create_task(
                self.strategy_engine.run(),
                name="strategy_engine"
            )
            self.tasks.append(task)

        if self.order_executor:
            task = asyncio.create_task(
                self.order_executor.run(),
                name="order_executor"
            )
            self.tasks.append(task)

        logger.info(f"Started {len(self.tasks)} background tasks")

    async def shutdown(self) -> None:
        """Gracefully shutdown the trading system."""
        logger.info("Shutting down trading system...")

        # Update status
        self.status.system_mode = SystemMode.SHUTDOWN

        # Cancel all background tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()

        # Wait for all tasks to complete (with timeout)
        if self.tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self.tasks, return_exceptions=True),
                    timeout=10.0
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Some tasks did not complete within timeout"
                )

        # Close order executor (saves pending orders)
        if self.order_executor:
            await self.order_executor.close()

        # Clear queues
        while not self.market_data_queue.empty():
            try:
                self.market_data_queue.get_nowait()
                self.market_data_queue.task_done()
            except asyncio.QueueEmpty:
                break

        while not self.order_queue.empty():
            try:
                self.order_queue.get_nowait()
                self.order_queue.task_done()
            except asyncio.QueueEmpty:
                break

        logger.info("Trading system shutdown complete")

    async def get_status(self) -> dict:
        """Get current system status.

        Returns:
            Dictionary containing system status information.
        """
        account = None
        positions = []

        if self.order_executor and self.order_executor.client:
            try:
                account = await self.order_executor.client.get_account()
                positions = self.order_executor.client.get_positions()
            except Exception as e:
                logger.error(f"Error fetching status: {e}")

        active_strategies = []
        if self.strategy_engine:
            active_strategies = [
                s.config.strategy_name
                for s in self.strategy_engine.strategies
                if s.config.enabled
            ]

        return {
            "system_mode": self.status.system_mode.value,
            "api_connected": self.status.api_connected,
            "account": account.model_dump() if account else None,
            "positions": [p.model_dump() for p in positions],
            "active_strategies": active_strategies,
            "uptime_seconds": self.status.uptime_seconds,
            "error_count": self.status.error_count,
            "last_error": self.status.last_error_message,
        }


def create_parser() -> argparse.ArgumentParser:
    """Create and configure argument parser.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="kiwoom-trading",
        description="Kiwoom Auto-Trading System CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Global options
    parser.add_argument(
        "--config",
        type=str,
        default="config/config.yaml",
        help="Path to configuration file (default: config/config.yaml)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )

    # Subcommands
    subparsers = parser.add_subparsers(
        dest="command",
        help="Available commands",
        required=True,
    )

    # start command
    start_parser = subparsers.add_parser(
        "start",
        help="Start the trading system",
    )
    start_parser.add_argument(
        "--mode",
        type=str,
        choices=["simulator", "live"],
        default="simulator",
        help="Operational mode (default: simulator)",
    )

    # stop command
    subparsers.add_parser(
        "stop",
        help="Stop the trading system gracefully",
    )

    # emergency-stop command
    subparsers.add_parser(
        "emergency-stop",
        help="Emergency stop - cancel all orders and shutdown immediately",
    )

    # status command
    subparsers.add_parser(
        "status",
        help="Display current system status",
    )

    # validate-config command
    subparsers.add_parser(
        "validate-config",
        help="Validate configuration file",
    )

    # test-api command
    test_api_parser = subparsers.add_parser(
        "test-api",
        help="Test API connectivity and authentication",
    )
    test_api_parser.add_argument(
        "--mode",
        type=str,
        choices=["simulator", "live"],
        default="live",
        help="API mode to test (default: live)",
    )

    # backtest command
    backtest_parser = subparsers.add_parser(
        "backtest",
        help="Run backtesting with historical data",
    )
    backtest_parser.add_argument(
        "--strategy",
        type=str,
        required=True,
        help="Strategy name to backtest",
    )
    backtest_parser.add_argument(
        "--start-date",
        type=str,
        required=True,
        help="Start date (YYYY-MM-DD)",
    )
    backtest_parser.add_argument(
        "--end-date",
        type=str,
        required=True,
        help="End date (YYYY-MM-DD)",
    )
    backtest_parser.add_argument(
        "--initial-balance",
        type=float,
        default=10000000.0,
        help="Initial balance in KRW (default: 10,000,000)",
    )
    backtest_parser.add_argument(
        "--output",
        type=str,
        help="Output file for backtest report (default: stdout)",
    )

    return parser


def _get_pid_file() -> Path:
    """Get path to PID file.

    Returns:
        Path to PID file.
    """
    return Path("logs") / "trading_system.pid"


def _write_pid_file() -> None:
    """Write current process ID to PID file."""
    import os
    pid_file = _get_pid_file()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))
    logger.debug(f"Wrote PID {os.getpid()} to {pid_file}")


def _remove_pid_file() -> None:
    """Remove PID file."""
    pid_file = _get_pid_file()
    if pid_file.exists():
        pid_file.unlink()
        logger.debug(f"Removed PID file {pid_file}")


def _read_pid() -> Optional[int]:
    """Read process ID from PID file.

    Returns:
        Process ID or None if file doesn't exist.
    """
    pid_file = _get_pid_file()
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text().strip())
    except (ValueError, IOError) as e:
        logger.error(f"Failed to read PID file: {e}")
        return None


def _is_process_running(pid: int) -> bool:
    """Check if process with given PID is running.

    Args:
        pid: Process ID to check.

    Returns:
        True if process is running, False otherwise.
    """
    import os
    import platform

    if platform.system() == "Windows":
        # Windows: use tasklist
        import subprocess
        try:
            output = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}"],
                stderr=subprocess.DEVNULL,
            ).decode()
            return str(pid) in output
        except Exception:
            return False
    else:
        # Unix: send signal 0
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


async def cmd_start(args: argparse.Namespace, config: Settings) -> int:
    """Execute start command.

    Args:
        args: Parsed command-line arguments.
        config: System configuration.

    Returns:
        Exit code (0 for success).
    """
    # Check if already running
    existing_pid = _read_pid()
    if existing_pid and _is_process_running(existing_pid):
        logger.error(
            f"Trading system is already running (PID: {existing_pid})"
        )
        logger.error("Use 'stop' command to stop it first")
        return 1

    logger.info(f"Starting system in {args.mode} mode...")

    # Write PID file
    _write_pid_file()

    system = TradingSystem(config)

    try:
        await system.start(mode=args.mode)
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 0
    except Exception as e:
        logger.error(f"Failed to start system: {e}", exc_info=True)
        return 1
    finally:
        _remove_pid_file()


async def cmd_stop(args: argparse.Namespace, config: Settings) -> int:
    """Execute stop command.

    Args:
        args: Parsed command-line arguments.
        config: System configuration.

    Returns:
        Exit code (0 for success).
    """
    import os
    import platform
    import time

    pid = _read_pid()
    if not pid:
        logger.error("No running trading system found (PID file not found)")
        return 1

    if not _is_process_running(pid):
        logger.warning(f"Process {pid} is not running (stale PID file)")
        _remove_pid_file()
        return 1

    logger.info(f"Stopping trading system (PID: {pid})...")

    try:
        if platform.system() == "Windows":
            # Windows: send Ctrl+C event
            import subprocess
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T"],
                check=True,
                capture_output=True,
            )
        else:
            # Unix: send SIGTERM
            os.kill(pid, signal.SIGTERM)

        # Wait for process to terminate (max 30 seconds)
        for i in range(30):
            if not _is_process_running(pid):
                logger.info("Trading system stopped successfully")
                _remove_pid_file()
                return 0
            time.sleep(1)

        logger.warning(
            "Process did not stop within 30 seconds, "
            "use 'emergency-stop' to force termination"
        )
        return 1

    except Exception as e:
        logger.error(f"Failed to stop process: {e}")
        return 1


async def cmd_emergency_stop(args: argparse.Namespace, config: Settings) -> int:
    """Execute emergency-stop command.

    Args:
        args: Parsed command-line arguments.
        config: System configuration.

    Returns:
        Exit code (0 for success).
    """
    import os
    import platform
    import time

    pid = _read_pid()
    if not pid:
        logger.error("No running trading system found (PID file not found)")
        return 1

    if not _is_process_running(pid):
        logger.warning(f"Process {pid} is not running (stale PID file)")
        _remove_pid_file()
        return 1

    logger.warning(f"Emergency stop - force killing process (PID: {pid})...")
    logger.warning("This may result in incomplete order cleanup!")

    try:
        if platform.system() == "Windows":
            # Windows: force kill
            import subprocess
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid), "/T"],
                check=True,
                capture_output=True,
            )
        else:
            # Unix: send SIGKILL
            os.kill(pid, signal.SIGKILL)

        # Wait briefly for process to terminate
        for i in range(5):
            if not _is_process_running(pid):
                logger.info("Process terminated")
                _remove_pid_file()
                return 0
            time.sleep(1)

        logger.error("Failed to terminate process")
        return 1

    except Exception as e:
        logger.error(f"Failed to kill process: {e}")
        return 1


async def cmd_status(args: argparse.Namespace, config: Settings) -> int:
    """Execute status command.

    계좌 현황, 활성 전략, 포지션 정보를 출력합니다.

    Args:
        args: Parsed command-line arguments.
        config: System configuration.

    Returns:
        Exit code (0 for success).
    """
    pid = _read_pid()

    if not pid:
        print("[STATUS] Trading system is NOT running")
        return 0

    if not _is_process_running(pid):
        print(
            f"[STATUS] PID file exists but process {pid} is not running (stale)"
        )
        _remove_pid_file()
        return 1

    print("=" * 70)
    print("[SYSTEM STATUS]")
    print("=" * 70)
    print(f"Status: RUNNING")
    print(f"PID: {pid}")
    print(f"PID file: {_get_pid_file()}")
    print("")

    # NOTE: 실제 구현에서는 IPC를 통해 실행 중인 시스템에서 상태를 가져와야 함
    # 현재는 간단히 설정 파일 기반으로 예시를 보여줌
    print("[ACCOUNT STATUS]")
    print("-" * 70)
    print("Note: Live status requires IPC implementation")
    print("      Showing configuration-based data structure below:")
    print("")

    # 예시 데이터 구조 표시 (설정 기반)
    print(f"Initial Balance:    {config.initial_balance:>15,.0f} KRW")
    print(f"Watch Symbols:      {config.watch_symbols}")
    print("")

    print("[POSITIONS]")
    print("-" * 70)
    print("No live position data available (IPC required)")
    print("")

    print("[ACTIVE STRATEGIES]")
    print("-" * 70)
    enabled_strategies = [s for s in config.strategies if s.enabled]
    if enabled_strategies:
        for strategy in enabled_strategies:
            print(f"  - {strategy.strategy_name}")
            print(f"    Capital Allocation: {strategy.capital_allocation:,.0f} KRW")
            print(f"    Max Positions: {strategy.max_positions}")
            print(f"    Watched Stocks: {len(strategy.watched_stocks)}")
    else:
        print("No active strategies")
    print("")

    print("=" * 70)
    print("[IMPLEMENTATION NOTE]")
    print("=" * 70)
    print("To display live account and position data, implement:")
    print("1. IPC (Inter-Process Communication) mechanism")
    print("2. Status endpoint via HTTP/socket or shared memory")
    print("3. Periodic status file updates by running system")
    print("")
    print("For now, monitor logs for real-time activity.")
    print("=" * 70)

    return 0


async def cmd_validate_config(args: argparse.Namespace, config: Settings) -> int:
    """Execute validate-config command.

    Args:
        args: Parsed command-line arguments.
        config: System configuration.

    Returns:
        Exit code (0 for success).
    """
    logger.info("Validating configuration...")

    try:
        # Configuration already loaded and validated by Settings
        logger.info("[SUCCESS] Configuration is valid")
        logger.info(f"  - Kiwoom API configured: {bool(config.kiwoom_api_key)}")
        logger.info(f"  - Initial balance: {config.initial_balance:,} KRW")
        logger.info(f"  - Strategies defined: {len(config.strategies)}")
        logger.info(f"  - Watch symbols: {len(config.watch_symbols)}")
        return 0
    except Exception as e:
        logger.error(f"[FAILED] Configuration validation failed: {e}")
        return 1


async def cmd_test_api(args: argparse.Namespace, config: Settings) -> int:
    """Execute test-api command.

    Args:
        args: Parsed command-line arguments.
        config: System configuration.

    Returns:
        Exit code (0 for success).
    """
    logger.info(f"Testing API connectivity ({args.mode} mode)...")

    try:
        if args.mode == "simulator":
            from ..simulator.kiwoom_simulator import KiwoomSimulator
            client = KiwoomSimulator(initial_balance=Decimal("10000000"))
            logger.info("[SUCCESS] Simulator initialized successfully")

            # Test basic operations
            account = await client.get_account()
            logger.info(f"  - Account balance: {account.cash_balance:,} KRW")
            logger.info(f"  - Total asset value: {account.total_asset_value:,} KRW")

            positions = client.get_positions()
            logger.info(f"  - Positions: {len(positions)}")

            logger.info("[SUCCESS] API connectivity test passed")
            return 0

        else:
            from ..api.kiwoom_client import KiwoomClient

            # Validate required configuration
            if not config.kiwoom_api_key:
                raise ValueError("KIWOOM_API_KEY is required for live mode. Set it in .env file.")
            if not config.kiwoom_api_secret:
                raise ValueError("KIWOOM_API_SECRET is required for live mode. Set it in .env file.")
            if not config.kiwoom_account_number:
                raise ValueError("KIWOOM_ACCOUNT_NUMBER is required for live mode. Set it in .env file.")

            # Use async context manager to properly connect and disconnect
            async with KiwoomClient(
                api_key=config.kiwoom_api_key,
                api_secret=config.kiwoom_api_secret,
                account_number=config.kiwoom_account_number,
                base_url=config.get_kiwoom_api_url()
            ) as client:
                logger.info(f"[SUCCESS] API client initialized successfully (mode: {config.kiwoom_trading_mode}, url: {config.get_kiwoom_api_url()})")

                # Test basic operations
                account = await client.get_account()
                logger.info(f"  - Account balance: {account.cash_balance:,} KRW")
                logger.info(f"  - Total asset value: {account.total_asset_value:,} KRW")

                positions = await client.get_positions()
                logger.info(f"  - Positions: {len(positions)}")

                logger.info("[SUCCESS] API connectivity test passed")
                return 0

    except Exception as e:
        logger.error(f"[FAILED] API connectivity test failed: {e}", exc_info=True)
        return 1


async def cmd_backtest(args: argparse.Namespace, config: Settings) -> int:
    """Execute backtest command.

    Args:
        args: Parsed command-line arguments.
        config: System configuration.

    Returns:
        Exit code (0 for success).
    """
    from datetime import datetime
    from ..services.backtest_engine import BacktestEngine
    from ..simulator.kiwoom_simulator import KiwoomSimulator

    logger.info("Running backtest...")
    logger.info(f"  - Strategy: {args.strategy}")
    logger.info(f"  - Period: {args.start_date} to {args.end_date}")
    logger.info(f"  - Initial balance: {args.initial_balance:,} KRW")

    try:
        # Parse dates
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")

        # Load strategy
        strategy_config = next(
            (s for s in config.strategies if s.strategy_name == args.strategy),
            None
        )
        if not strategy_config:
            logger.error(f"Strategy '{args.strategy}' not found in configuration")
            logger.error(f"Available strategies: {[s.strategy_name for s in config.strategies]}")
            return 1

        # Import strategy class dynamically
        import importlib
        module_path, class_name = strategy_config.strategy_class.rsplit(".", 1)
        module = importlib.import_module(module_path)
        strategy_class = getattr(module, class_name)

        # Create simulator and strategy instance
        initial_balance = Decimal(str(args.initial_balance))
        simulator = KiwoomSimulator(initial_balance=initial_balance)
        strategy = strategy_class(
            config=strategy_config,
            client=simulator
        )

        # Create backtest engine
        engine = BacktestEngine(
            config=config,
            strategy=strategy,
            initial_balance=initial_balance
        )

        # Load historical price data
        # For now, generate dummy data
        # TODO: Load from CSV or database
        price_data = _load_price_data(
            config.watch_symbols,
            start_date,
            end_date
        )

        if not price_data:
            logger.error("No price data available for backtest")
            logger.error("Price data loading is not yet implemented")
            logger.error("TODO: Implement CSV or API-based historical data loading")
            return 1

        # Run backtest
        result = await engine.run(
            start_date=start_date,
            end_date=end_date,
            price_data=price_data
        )

        # Generate and save report
        report = _generate_backtest_report(result)

        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report)
            logger.info(f"Report saved to: {output_path}")
        else:
            print("\n" + "=" * 60)
            print(report)
            print("=" * 60)

        return 0

    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        return 1


def _load_price_data(
    symbols: List[str],
    start_date: datetime,
    end_date: datetime
) -> Dict[str, List[Stock]]:
    """Load historical price data.

    Args:
        symbols: List of stock symbols.
        start_date: Start date.
        end_date: End date.

    Returns:
        Price data dictionary.
    """
    # TODO: Implement actual data loading from CSV or API
    # For now, return empty dict to indicate not implemented
    logger.warning("Historical data loading not implemented yet")
    return {}


def _generate_backtest_report(result) -> str:
    """Generate backtest report text.

    Args:
        result: BacktestResult object.

    Returns:
        Formatted report string.
    """
    from ..services.backtest_engine import BacktestResult

    lines = []
    lines.append("BACKTEST REPORT")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Strategy: {result.strategy_name}")
    lines.append(f"Period: {result.start_date.date()} to {result.end_date.date()}")
    lines.append(f"Duration: {(result.end_date - result.start_date).days} days")
    lines.append("")
    lines.append("PERFORMANCE")
    lines.append("-" * 60)
    lines.append(f"Initial Balance:  {result.initial_balance:>20,.0f} KRW")
    lines.append(f"Final Balance:    {result.final_balance:>20,.0f} KRW")
    lines.append(f"Total Return:     {result.total_return:>20.2f} %")
    lines.append("")
    lines.append("TRADING STATISTICS")
    lines.append("-" * 60)
    lines.append(f"Total Trades:     {result.total_trades:>20}")
    lines.append(f"Winning Trades:   {result.winning_trades:>20}")
    lines.append(f"Losing Trades:    {result.losing_trades:>20}")
    lines.append(f"Win Rate:         {result.win_rate:>20.2f} %")
    lines.append("")
    lines.append("RISK METRICS")
    lines.append("-" * 60)
    lines.append(f"Max Drawdown:     {result.max_drawdown:>20.2f} %")
    lines.append(f"Sharpe Ratio:     {result.sharpe_ratio:>20.2f}")
    lines.append("")
    lines.append("ORDER HISTORY (First 10)")
    lines.append("-" * 60)

    for i, order in enumerate(result.orders[:10]):
        lines.append(
            f"{i+1:3}. {order.timestamp.date()} "
            f"{order.order_type.value:4} "
            f"{order.stock_code:6} "
            f"{order.quantity:>5} @ {order.filled_price:>10,.0f} "
            f"[{order.status.value}]"
        )

    if len(result.orders) > 10:
        lines.append(f"... and {len(result.orders) - 10} more orders")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    """Main entry point for CLI.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    # Parse arguments
    parser = create_parser()
    args = parser.parse_args()

    # Setup logging
    import logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Load configuration
    try:
        config = Settings.from_yaml(args.config)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        return 1

    # Dispatch command
    command_handlers = {
        "start": cmd_start,
        "stop": cmd_stop,
        "emergency-stop": cmd_emergency_stop,
        "status": cmd_status,
        "validate-config": cmd_validate_config,
        "test-api": cmd_test_api,
        "backtest": cmd_backtest,
    }

    handler = command_handlers.get(args.command)
    if not handler:
        logger.error(f"Unknown command: {args.command}")
        return 1

    # Run async handler
    try:
        return asyncio.run(handler(args, config))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 0
    except Exception as e:
        logger.error(f"Command failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
