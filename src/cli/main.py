"""Kiwoom Auto-Trading CLI main entry point."""

import argparse
import asyncio
import json
import logging
import signal
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

from ..config.settings import Settings
from ..models import SystemMode
from ..models.order import Order
from ..models.position import Position
from ..models.stock import Stock
from ..models.system_status import SystemStatus
from ..services.data_collector import DataCollector
from ..services.order_executor import OrderExecutor
from ..services.risk_monitor import RiskMonitor
from ..services.strategy_engine import StrategyEngine
from ..utils.logger import get_logger

# WebSocket 실시간 데이터 수집기
try:
    from ..services.websocket_data_collector import WebSocketDataCollector
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False

# TimescaleDB 관련 임포트
try:
    from ..timeseries.database import TimeSeriesDB
    from ..timeseries.collector import DataCollector as TimeSeriesDataCollector
    from ..timeseries.models import OrderHistory, BalanceHistory
    from ..utils.timescale_log_handler import AsyncTimescaleLogHandler
    TIMESCALEDB_AVAILABLE = True
except ImportError:
    TIMESCALEDB_AVAILABLE = False

# Prometheus 모니터링 관련 임포트
try:
    from ..monitoring.metrics_collector import MetricsCollector
    from ..monitoring.prometheus_exporter import PrometheusExporter
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

# Dashboard 데이터 발행 관련 임포트
try:
    from ..cache.redis_manager import RedisManager
    from ..dashboard.services.data_publisher import DashboardDataPublisher
    from ..services.stock_info_cache import StockInfoCache
    DASHBOARD_AVAILABLE = True
except ImportError:
    DASHBOARD_AVAILABLE = False

# Redis Streams / Account Cache 관련 임포트 (Phase 3)
try:
    from ..cache.redis_stream_manager import RedisStreamManager
    from ..cache.account_cache import AccountCache
    REDIS_STREAMS_AVAILABLE = True
except ImportError:
    REDIS_STREAMS_AVAILABLE = False

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
        self.order_book_queue: asyncio.Queue = asyncio.Queue(maxsize=500)  # 0D 호가 데이터
        self.order_event_queue: asyncio.Queue = asyncio.Queue(maxsize=100)  # 00/04 주문/잔고
        self.order_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.shutdown_event: asyncio.Event = asyncio.Event()

        # System status
        self.status = SystemStatus(system_mode=SystemMode.STARTING)

        # Services
        self.data_collector: Optional[DataCollector] = None
        self.strategy_engine: Optional[StrategyEngine] = None
        self.order_executor: Optional[OrderExecutor] = None
        self.risk_monitor: Optional[RiskMonitor] = None
        self.client = None  # Store client for cleanup

        # Shared state for services
        self.pending_orders: Dict[str, Order] = {}
        self.positions: Dict[str, Position] = {}

        # TimescaleDB 관련
        self.tsdb: Optional[TimeSeriesDB] = None
        self.ts_log_handler: Optional[AsyncTimescaleLogHandler] = None
        self.timeseries_collector: Optional[TimeSeriesDataCollector] = None

        # Prometheus 모니터링 관련
        self.metrics_collector: Optional[MetricsCollector] = None
        self.prometheus_exporter: Optional[PrometheusExporter] = None

        # Dashboard 데이터 발행 관련
        self.redis_manager: Optional[RedisManager] = None
        self.dashboard_publisher: Optional[DashboardDataPublisher] = None

        # Redis Streams / Account Cache (Phase 3 - Queue Overflow 해결)
        self.stream_manager: Optional[RedisStreamManager] = None
        self.account_cache: Optional[AccountCache] = None

        # Background tasks
        self.tasks: list[asyncio.Task] = []

        # Setup signal handlers
        self._setup_signal_handlers()

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        # Use standard signal.signal() for cross-platform compatibility
        # add_signal_handler() is not supported on Windows
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._signal_handler)

    def _signal_handler(self, signum: int, frame) -> None:
        """Handle shutdown signals (sync wrapper).

        Args:
            signum: Signal number.
            frame: Current stack frame.
        """
        logger.info(f"Received signal {signum}, initiating shutdown...")
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
        # TimescaleDB 초기화 (활성화된 경우)
        if self.config.enable_timescaledb and TIMESCALEDB_AVAILABLE:
            try:
                self.tsdb = TimeSeriesDB(
                    host=self.config.timescaledb_host,
                    port=self.config.timescaledb_port,
                    database=self.config.timescaledb_database,
                    user=self.config.timescaledb_user,
                    password=self.config.timescaledb_password,
                    min_size=self.config.timescaledb_min_pool_size,
                    max_size=self.config.timescaledb_max_pool_size
                )
                await self.tsdb.connect()
                logger.info(
                    f"Connected to TimescaleDB at {self.config.timescaledb_host}:"
                    f"{self.config.timescaledb_port}/{self.config.timescaledb_database}"
                )

                # TimescaleDB 로그 핸들러 추가
                self.ts_log_handler = AsyncTimescaleLogHandler(
                    db_pool=self.tsdb.pool,
                    level=getattr(logging, self.config.log_level.upper()),
                    buffer_size=20  # 더 작은 버퍼로 자주 플러시
                )

                # 루트 로거에 핸들러 추가
                root_logger = logging.getLogger()
                root_logger.addHandler(self.ts_log_handler)
                logger.info("TimescaleDB log handler attached to root logger")

                # TimeSeriesDataCollector 초기화 (주문/잔고/성능 지표 저장)
                self.timeseries_collector = TimeSeriesDataCollector(
                    db=self.tsdb,
                    ws_client=None  # WebSocket 클라이언트는 나중에 설정
                )
                # start()에서 db.connect() 호출하지만 이미 연결됨, 플러시 루프만 시작
                await self.timeseries_collector.start()
                logger.info("TimeSeriesDataCollector initialized for order/balance/metrics storage")

            except Exception as e:
                logger.error(f"Failed to initialize TimescaleDB: {e}", exc_info=True)
                logger.warning("Continuing without TimescaleDB logging")
                self.tsdb = None
                self.ts_log_handler = None
                self.timeseries_collector = None
        elif self.config.enable_timescaledb and not TIMESCALEDB_AVAILABLE:
            logger.warning(
                "TimescaleDB is enabled in config but required dependencies "
                "(asyncpg, pandas) are not installed. Skipping TimescaleDB setup."
            )

        # Prometheus 모니터링 초기화 (활성화된 경우)
        if self.config.enable_prometheus and PROMETHEUS_AVAILABLE:
            try:
                self.metrics_collector = MetricsCollector()
                self.prometheus_exporter = PrometheusExporter(
                    metrics_collector=self.metrics_collector,
                    host=self.config.prometheus_host,
                    port=self.config.prometheus_port,
                )
                logger.info(
                    f"Prometheus monitoring initialized "
                    f"(endpoint=http://{self.config.prometheus_host}:{self.config.prometheus_port}/metrics)"
                )
            except Exception as e:
                logger.error(f"Failed to initialize Prometheus monitoring: {e}", exc_info=True)
                logger.warning("Continuing without Prometheus monitoring")
                self.metrics_collector = None
                self.prometheus_exporter = None
        elif self.config.enable_prometheus and not PROMETHEUS_AVAILABLE:
            logger.warning(
                "Prometheus is enabled in config but required dependencies "
                "(prometheus_client, aiohttp) are not installed. Skipping Prometheus setup."
            )

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
                api_secret=self.config.kiwoom_api_secret,
                account_number=self.config.kiwoom_account_number,
                base_url=self.config.get_kiwoom_api_url(),
                max_requests_per_second=self.config.get_rate_limit_per_second()
            )
            # Connect to Kiwoom API
            await client.connect()
            logger.info(
                f"Initialized and connected live Kiwoom API client with rate limit: "
                f"{self.config.get_rate_limit_per_second()} req/s"
            )

        # Store client reference for cleanup
        self.client = client

        # Phase 3: Redis Streams / Account Cache 초기화 (Queue Overflow 해결)
        use_redis_streams = (
            getattr(self.config, "redis_streams_enabled", True)
            and getattr(self.config, "redis_enabled", False)
            and REDIS_STREAMS_AVAILABLE
            and mode != "simulator"  # 시뮬레이터 모드에서는 기존 Queue 사용
        )

        if use_redis_streams:
            try:
                # Redis 연결 초기화 (Dashboard와 별도 또는 공유)
                if not self.redis_manager:
                    self.redis_manager = RedisManager(
                        host=self.config.redis_host,
                        port=self.config.redis_port,
                        db=self.config.redis_db,
                        password=self.config.redis_password,
                        max_connections=self.config.redis_max_connections,
                        default_ttl=self.config.redis_cache_ttl
                    )
                    await self.redis_manager.initialize()
                    logger.info(
                        f"Connected to Redis at {self.config.redis_host}:{self.config.redis_port} "
                        f"for Redis Streams"
                    )

                # RedisStreamManager 초기화
                self.stream_manager = RedisStreamManager(
                    redis_manager=self.redis_manager,
                    stream_prefix="trading:",
                    max_len=getattr(self.config, "redis_stream_max_len", 100000),
                    retention_hours=getattr(self.config, "redis_stream_retention_hours", 1),
                )
                logger.info(
                    f"RedisStreamManager initialized "
                    f"(max_len={getattr(self.config, 'redis_stream_max_len', 100000)}, "
                    f"retention={getattr(self.config, 'redis_stream_retention_hours', 1)}h)"
                )

                # AccountCache 초기화
                if getattr(self.config, "account_cache_enabled", True):
                    self.account_cache = AccountCache(
                        redis_manager=self.redis_manager,
                        sync_interval=getattr(self.config, "account_cache_sync_interval", 10),
                    )
                    logger.info(
                        f"AccountCache initialized "
                        f"(sync_interval={getattr(self.config, 'account_cache_sync_interval', 10)}s)"
                    )

            except Exception as e:
                logger.error(f"Failed to initialize Redis Streams/Account Cache: {e}", exc_info=True)
                logger.warning("Continuing with traditional Queue-based approach")
                self.stream_manager = None
                self.account_cache = None
        elif not REDIS_STREAMS_AVAILABLE:
            logger.debug("Redis Streams dependencies not available, using Queue-based approach")

        # Initialize data collector (WebSocket or REST polling)
        use_websocket = (
            getattr(self.config, "websocket_enabled", True)
            and WEBSOCKET_AVAILABLE
            and mode != "simulator"  # 시뮬레이터 모드에서는 REST 폴링 사용
        )

        if use_websocket:
            self.data_collector = WebSocketDataCollector(
                config=self.config,
                kiwoom_client=client,
                market_data_queue=self.market_data_queue,
                order_book_queue=self.order_book_queue,
                order_event_queue=self.order_event_queue,
                stock_codes=list(self.config.watch_symbols),
                fallback_to_rest=getattr(self.config, "websocket_fallback_to_rest", True),
                redis_manager=self.redis_manager,
                stream_manager=self.stream_manager,  # Phase 3: Redis Streams
            )
            logger.info(
                "Initialized WebSocket data collector "
                f"(stocks={len(self.config.watch_symbols)}, "
                f"fallback_to_rest={getattr(self.config, 'websocket_fallback_to_rest', True)}, "
                f"redis_streams={'enabled' if self.stream_manager else 'disabled'})"
            )
        else:
            self.data_collector = DataCollector(
                config=self.config,
                client=client,
                market_data_queue=self.market_data_queue
            )
            if mode == "simulator":
                logger.info("Initialized REST data collector (simulator mode)")
            elif not WEBSOCKET_AVAILABLE:
                logger.warning(
                    "WebSocket not available (missing dependencies), "
                    "falling back to REST polling"
                )
            else:
                logger.info("Initialized REST data collector (websocket_enabled=False)")

        # Initialize OrderExecutor first (StrategyEngine will need it)
        # Phase 6: order_event_queue 전달하여 실시간 주문 이벤트 처리
        self.order_executor = OrderExecutor(
            client=client,
            pending_orders=self.pending_orders,
            positions=self.positions,
            risk_manager=None,  # Uses default RiskManager
            account_service=None,  # Will be set up later if needed
            order_event_queue=self.order_event_queue,  # Phase 6
            timeseries_collector=self.timeseries_collector  # TimescaleDB 데이터 저장
        )

        # Initialize RiskMonitor (Phase 2)
        from ..services.risk_manager import RiskManager
        risk_manager = RiskManager(
            daily_loss_limit_pct=Decimal("0.02"),
            max_position_concentration=Decimal("0.3"),
            warning_threshold=Decimal("0.8")
        )
        self.risk_monitor = RiskMonitor(
            risk_manager=risk_manager,
            order_executor=self.order_executor,
            positions=self.positions,
            client=client,
            check_interval=1.0  # 1초마다 체크
        )
        logger.info("RiskMonitor initialized (1-second interval)")

        # Initialize StrategyEngine with OrderExecutor
        # Phase 6: order_book_queue 전달하여 호가 기반 전략 지원
        # Phase 3: Redis Streams + Account Cache (Queue Overflow 해결)
        self.strategy_engine = StrategyEngine(
            config_path=None,  # Uses default path: config/strategies.yaml
            market_data_queue=self.market_data_queue,
            order_book_queue=self.order_book_queue,  # Phase 6
            risk_manager=None,  # Uses default RiskManager
            account=None,  # Will be updated when account info is fetched
            positions=self.positions,  # Share positions with OrderExecutor
            order_executor=self.order_executor,  # Enable order execution
            stream_manager=self.stream_manager,  # Phase 3: Redis Streams
            account_cache=self.account_cache,  # Phase 3: Account Cache
            throttle_ms=getattr(self.config, "market_data_throttle_ms", 100),  # Phase 3
        )

        # Load strategies
        self.strategy_engine.load_and_initialize_strategies()
        logger.info(
            f"Loaded {len(self.strategy_engine.strategies)} strategies"
        )

        # Initialize historical chart data for strategies
        await self.strategy_engine.initialize_historical_data(client)
        logger.info("Historical chart data initialized for all strategies")

        # Collect all stock codes from strategies and register them to DataCollector
        all_stock_codes = set()
        for strategy_name, config in self.strategy_engine.strategy_configs.items():
            all_stock_codes.update(config.symbols)

        if all_stock_codes:
            # Merge with existing stock codes and update DataCollector
            existing_codes = set(self.data_collector.stock_codes)
            all_stock_codes.update(existing_codes)
            self.data_collector.update_stock_codes(list(all_stock_codes))
            logger.info(
                f"Registered {len(all_stock_codes)} stock codes from strategies: {sorted(all_stock_codes)}"
            )

        # Dashboard 데이터 발행 초기화 (활성화된 경우)
        if self.config.enable_dashboard and self.config.redis_enabled and DASHBOARD_AVAILABLE:
            try:
                # Redis 연결 초기화
                self.redis_manager = RedisManager(
                    host=self.config.redis_host,
                    port=self.config.redis_port,
                    db=self.config.redis_db,
                    password=self.config.redis_password,
                    max_connections=self.config.redis_max_connections,
                    default_ttl=self.config.redis_cache_ttl
                )
                await self.redis_manager.initialize()
                logger.info(
                    f"Connected to Redis at {self.config.redis_host}:{self.config.redis_port} "
                    f"for dashboard data publishing"
                )

                # StockInfoCache 초기화 (종목명 캐시)
                stock_info_cache = StockInfoCache(client=client)
                logger.info("StockInfoCache initialized for dashboard")

                # DashboardDataPublisher 초기화
                self.dashboard_publisher = DashboardDataPublisher(
                    redis_manager=self.redis_manager,
                    positions=self.positions,
                    account=None,  # Account will be updated dynamically
                    pending_orders=self.pending_orders,  # pending orders for status tracking
                    stock_info_cache=stock_info_cache,  # stock name lookup
                    publish_interval=self.config.dashboard_update_interval
                )

                # OrderExecutor에 trade callback 연결
                if self.order_executor:
                    self.order_executor.on_trade_filled_callback = self._on_trade_filled

                logger.info(
                    f"DashboardDataPublisher initialized "
                    f"(update_interval={self.config.dashboard_update_interval}s, "
                    f"stock_name_cache=enabled, pending_orders=enabled)"
                )

            except Exception as e:
                logger.error(f"Failed to initialize Dashboard publisher: {e}", exc_info=True)
                logger.warning("Continuing without Dashboard data publishing")
                self.redis_manager = None
                self.dashboard_publisher = None
        elif self.config.enable_dashboard and not DASHBOARD_AVAILABLE:
            logger.warning(
                "Dashboard is enabled in config but required dependencies "
                "(redis, dashboard module) are not installed. Skipping Dashboard setup."
            )

    async def _on_trade_filled(self, order: Order, realized_pnl: Optional[Decimal] = None) -> None:
        """체결 완료 시 Dashboard에 데이터 발행.

        Args:
            order: 체결된 주문
            realized_pnl: 실현 손익 (매도 주문의 경우)
        """
        if self.dashboard_publisher:
            try:
                await self.dashboard_publisher.publish_trade(order, realized_pnl)
            except Exception as e:
                logger.error(f"Failed to publish trade to dashboard: {e}")

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

        # Phase 3: AccountCache 백그라운드 동기화 태스크
        if self.account_cache and self.client:
            try:
                await self.account_cache.start_sync_task(self.client)
                logger.info("AccountCache sync task started")
            except Exception as e:
                logger.error(f"Failed to start AccountCache sync: {e}")

        # Phase 2: RiskMonitor 백그라운드 태스크
        if self.risk_monitor:
            task = asyncio.create_task(
                self.risk_monitor.run(),
                name="risk_monitor"
            )
            self.tasks.append(task)
            logger.info("RiskMonitor background task started")

        # Phase 6: OrderExecutor order_event_queue 소비 태스크
        if self.order_executor and self.order_event_queue:
            task = asyncio.create_task(
                self.order_executor.run(),
                name="order_executor_events"
            )
            self.tasks.append(task)
            logger.info("OrderExecutor event consumer started")

        # TimescaleDB 로그 플러시 태스크
        if self.ts_log_handler:
            task = asyncio.create_task(
                self._log_flush_loop(),
                name="timescaledb_log_flush"
            )
            self.tasks.append(task)

        # Prometheus exporter 시작 및 메트릭 수집 태스크
        if self.prometheus_exporter:
            await self.prometheus_exporter.start()
            logger.info("Prometheus exporter started")

            # 시스템 메트릭 수집 루프 시작
            task = asyncio.create_task(
                self._metrics_collection_loop(),
                name="metrics_collection"
            )
            self.tasks.append(task)
            logger.info("System metrics collection task started")

        # Dashboard 데이터 발행 시작
        if self.dashboard_publisher:
            await self.dashboard_publisher.start()
            logger.info("DashboardDataPublisher background task started")

        # Note: OrderExecutor is not a background task service
        # It's called on-demand when orders need to be executed

        logger.info(f"Started {len(self.tasks)} background tasks")

    async def _log_flush_loop(self) -> None:
        """주기적으로 TimescaleDB 로그 플러시."""
        try:
            while not self.shutdown_event.is_set():
                await asyncio.sleep(5.0)  # 5초마다 플러시
                if self.ts_log_handler and len(self.ts_log_handler.buffer) > 0:
                    await self.ts_log_handler._flush_buffer()
        except asyncio.CancelledError:
            # 마지막 플러시
            if self.ts_log_handler:
                await self.ts_log_handler._flush_buffer()
            raise

    async def _metrics_collection_loop(self) -> None:
        """주기적으로 시스템 메트릭 수집."""
        try:
            while not self.shutdown_event.is_set():
                await asyncio.sleep(self.config.metrics_collection_interval)

                if self.metrics_collector:
                    # 시스템 메트릭 수집 (CPU, Memory, Disk)
                    await self.metrics_collector.collect_system_metrics()

                    # 파이프라인 메트릭 업데이트
                    if self.order_executor:
                        self.metrics_collector.set_pipeline_queue_depth(
                            len(self.pending_orders)
                        )

                    # 포지션 집중도 메트릭 업데이트
                    if self.positions:
                        total_value = sum(
                            p.current_value for p in self.positions.values()
                            if hasattr(p, 'current_value')
                        )
                        if total_value > 0:
                            for code, position in self.positions.items():
                                if hasattr(position, 'current_value'):
                                    ratio = float(position.current_value / total_value)
                                    self.metrics_collector.set_position_concentration(
                                        code, ratio
                                    )

        except asyncio.CancelledError:
            logger.debug("Metrics collection loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in metrics collection loop: {e}", exc_info=True)

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

        # Phase 2: RiskMonitor cleanup
        if self.risk_monitor:
            logger.info("Stopping RiskMonitor...")
            await self.risk_monitor.stop()

        # Phase 6: OrderExecutor cleanup
        if self.order_executor:
            logger.info("Stopping OrderExecutor event consumer...")
            await self.order_executor.stop()
            logger.info("OrderExecutor stopped")

        # Phase 3: AccountCache cleanup
        if self.account_cache:
            logger.info("Stopping AccountCache sync task...")
            await self.account_cache.stop_sync_task()
            logger.info("AccountCache stopped")

        # Close API client connection
        if self.client:
            # Check if client has close method (KiwoomClient does, simulator may not)
            if hasattr(self.client, 'close'):
                logger.info("Closing API client connection...")
                await self.client.close()
                logger.info("API client connection closed")

        # Clear queues
        for queue_name, queue in [
            ("market_data_queue", self.market_data_queue),
            ("order_book_queue", self.order_book_queue),
            ("order_event_queue", self.order_event_queue),
            ("order_queue", self.order_queue),
        ]:
            count = 0
            while not queue.empty():
                try:
                    queue.get_nowait()
                    queue.task_done()
                    count += 1
                except asyncio.QueueEmpty:
                    break
            if count > 0:
                logger.debug(f"Cleared {count} items from {queue_name}")

        # Dashboard 데이터 발행 종료
        if self.dashboard_publisher:
            logger.info("Stopping DashboardDataPublisher...")
            await self.dashboard_publisher.stop()
            logger.info("DashboardDataPublisher stopped")

        # Redis 연결 종료
        if self.redis_manager:
            logger.info("Closing Redis connection...")
            await self.redis_manager.close()
            logger.info("Redis connection closed")

        # Prometheus exporter 종료
        if self.prometheus_exporter:
            logger.info("Stopping Prometheus exporter...")
            await self.prometheus_exporter.stop()
            logger.info("Prometheus exporter stopped")

        # TimescaleDB 정리
        if self.ts_log_handler:
            logger.info("Stopping TimescaleDB log handler...")
            await self.ts_log_handler.close_async()  # 마지막 로그 플러시
            # 루트 로거에서 제거
            root_logger = logging.getLogger()
            root_logger.removeHandler(self.ts_log_handler)
            logger.info("TimescaleDB log handler stopped")

        if self.tsdb:
            logger.info("Disconnecting from TimescaleDB...")
            await self.tsdb.disconnect()
            logger.info("Disconnected from TimescaleDB")

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

    # dashboard command
    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help="Start the web dashboard server",
    )
    dashboard_parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Dashboard server host (default: from config)",
    )
    dashboard_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Dashboard server port (default: from config)",
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
                base_url=config.get_kiwoom_api_url(),
                max_requests_per_second=config.get_rate_limit_per_second()
            ) as client:
                logger.info(
                    f"[SUCCESS] API client initialized successfully "
                    f"(mode: {config.kiwoom_trading_mode}, "
                    f"url: {config.get_kiwoom_api_url()}, "
                    f"rate limit: {config.get_rate_limit_per_second()} req/s)"
                )

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


async def cmd_dashboard(args: argparse.Namespace, config: Settings) -> int:
    """Execute dashboard command - start web dashboard server.

    Args:
        args: Parsed command-line arguments.
        config: System configuration.

    Returns:
        Exit code (0 for success).
    """
    # Check Redis availability
    if not config.redis_enabled:
        logger.error("Redis is required for dashboard. Enable redis_enabled in config.")
        return 1

    # Override host/port if provided
    if args.host:
        config.dashboard_host = args.host
    if args.port:
        config.dashboard_port = args.port

    logger.info(f"Starting Dashboard server on {config.dashboard_host}:{config.dashboard_port}")
    logger.info("Dashboard requires Redis for data sharing with trading system")
    logger.info("")
    logger.info("Access the dashboard at:")
    logger.info(f"  http://localhost:{config.dashboard_port}/")
    logger.info("")
    logger.info("For development with React hot reload:")
    logger.info("  cd dashboard-ui && npm run dev")
    logger.info(f"  http://localhost:5173/")
    logger.info("")

    try:
        from ..dashboard.app import run_dashboard_server
        await run_dashboard_server(settings=config)
        return 0
    except ImportError as e:
        logger.error(f"Dashboard dependencies not installed: {e}")
        logger.error("Install with: pip install fastapi uvicorn")
        return 1
    except Exception as e:
        logger.error(f"Dashboard server failed: {e}", exc_info=True)
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
        order_type_val = order.order_type.value if hasattr(order.order_type, 'value') else order.order_type
        status_val = order.status.value if hasattr(order.status, 'value') else order.status
        lines.append(
            f"{i+1:3}. {order.timestamp.date()} "
            f"{order_type_val:4} "
            f"{order.stock_code:6} "
            f"{order.quantity:>5} @ {order.filled_price:>10,.0f} "
            f"[{status_val}]"
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
        "dashboard": cmd_dashboard,
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
