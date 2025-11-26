"""전략 엔진 모듈.

이 모듈은 전략을 동적으로 로드하고 관리하는 기능을 제공합니다.

T078: DataCollector와 asyncio.Queue를 통해 통합되어,
      실시간 시세 데이터를 수신하여 전략 평가를 수행합니다.
T087: RiskManager를 통합하여 매 주문 전 위험 검증을 수행합니다.
Phase 6: order_book_queue를 소비하여 호가 기반 전략에 실시간 호가 데이터 전달.
"""

import asyncio
import importlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Type
from decimal import Decimal

import yaml
from pydantic import BaseModel, Field

from ..models import Stock, PriceType, OrderType, OrderStatus
from ..models.strategy import BaseStrategy
from ..models.account import Account
from ..models.order_book import OrderBook
from ..models.position import Position
from ..models.order import Order
from ..models.realtime_data import OrderBookData
from .risk_manager import RiskManager
from ..utils.logger import get_logger

# Forward declaration for type hints
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .order_executor import OrderExecutor


logger = get_logger(__name__)


class StrategyConfig(BaseModel):
    """전략 설정 모델.

    Attributes:
        strategy_name: 전략 고유 이름
        enabled: 전략 활성화 여부
        class_path: 전략 클래스 경로 (예: "src.strategies.golden_cross.GoldenCrossStrategy")
        symbols: 전략이 감시할 종목 코드 리스트
        parameters: 전략별 파라미터
        price_type: 주문 가격 타입 (MARKET/LIMIT, 기본값: MARKET)
        position_size_pct: 가용 자금 대비 포지션 크기 비율 (0.0~1.0, 기본값: 1.0)
    """

    strategy_name: str = Field(..., min_length=1, max_length=100)
    enabled: bool = Field(default=True)
    class_path: str = Field(..., description="Strategy class path")
    symbols: List[str] = Field(default_factory=list, description="Stock codes to watch")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    price_type: PriceType = Field(default=PriceType.MARKET, description="Order price type")
    position_size_pct: Decimal = Field(
        default=Decimal("1.0"),
        ge=Decimal("0.01"),
        le=Decimal("1.0"),
        description="Position size as percentage of available capital"
    )

    class Config:
        """Pydantic 설정."""

        frozen = False


class StrategyEngine:
    """전략 엔진.

    YAML 파일에서 전략 설정을 로드하고, importlib을 사용하여 동적으로 전략 클래스를 생성합니다.
    T087: RiskManager를 통합하여 매 주문 전 위험 검증을 수행합니다.

    Attributes:
        config_path: 전략 설정 YAML 파일 경로
        strategies: 로드된 전략 인스턴스 딕셔너리 (strategy_name -> BaseStrategy)
        strategy_configs: 전략 설정 딕셔너리 (strategy_name -> StrategyConfig)
        risk_manager: 위험 관리자 (T087)
        account: 현재 계좌 정보
        positions: 현재 포지션 딕셔너리
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        market_data_queue: Optional[asyncio.Queue] = None,
        order_book_queue: Optional[asyncio.Queue] = None,
        risk_manager: Optional[RiskManager] = None,
        account: Optional[Account] = None,
        positions: Optional[Dict[str, Position]] = None,
        order_executor: Optional["OrderExecutor"] = None
    ):
        """전략 엔진 초기화.

        Args:
            config_path: 전략 설정 YAML 파일 경로. None이면 기본 경로 사용.
            market_data_queue: 시장 데이터를 수신할 asyncio.Queue (T078).
            order_book_queue: 호가 데이터를 수신할 asyncio.Queue (Phase 6).
            risk_manager: 위험 관리자 (T087). None이면 기본 설정으로 생성.
            account: 현재 계좌 정보 (T087).
            positions: 현재 포지션 딕셔너리 (T087).
            order_executor: 주문 실행기. None이면 주문 실행 기능 비활성화.
        """
        self.config_path = config_path or Path("config/strategies.yaml")
        self.strategies: Dict[str, BaseStrategy] = {}
        self.strategy_configs: Dict[str, StrategyConfig] = {}

        # T078: DataCollector와의 통합을 위한 큐
        self.market_data_queue = market_data_queue
        self.running = False
        self.consumer_task: Optional[asyncio.Task] = None

        # Phase 6: 호가 데이터 큐
        self.order_book_queue = order_book_queue
        self._order_book_task: Optional[asyncio.Task] = None

        # T087: RiskManager 통합
        self.risk_manager = risk_manager or RiskManager(
            daily_loss_limit_pct=Decimal("0.02"),  # 기본값: 2%
            max_position_concentration=Decimal("0.3"),  # 기본값: 30%
            warning_threshold=Decimal("0.8")  # 기본값: 80%
        )
        self.account = account
        self.positions = positions or {}

        # 주문 실행기
        self.order_executor = order_executor

    def load_strategies_from_yaml(self) -> List[StrategyConfig]:
        """YAML 파일에서 전략 설정 로드.

        Returns:
            전략 설정 리스트

        Raises:
            FileNotFoundError: 설정 파일이 존재하지 않는 경우
            yaml.YAMLError: YAML 파싱 오류
            ValueError: 설정 검증 오류
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"Strategy config file not found: {self.config_path}")

        logger.info(f"Loading strategies from {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f)

        if not config_data or "strategies" not in config_data:
            raise ValueError("Invalid strategy config: 'strategies' key not found")

        strategy_configs = []
        for strategy_dict in config_data["strategies"]:
            try:
                config = StrategyConfig(**strategy_dict)
                strategy_configs.append(config)
                logger.info(f"Loaded strategy config: {config.strategy_name}")
            except Exception as e:
                logger.error(f"Failed to load strategy config: {e}")
                raise

        return strategy_configs

    def import_strategy_class(self, class_path: str) -> Type[BaseStrategy]:
        """전략 클래스 동적 import.

        Args:
            class_path: 전략 클래스 경로 (예: "src.strategies.golden_cross.GoldenCrossStrategy")

        Returns:
            전략 클래스

        Raises:
            ImportError: 모듈 또는 클래스를 찾을 수 없는 경우
            ValueError: 클래스가 BaseStrategy를 상속하지 않는 경우

        Example:
            >>> engine = StrategyEngine()
            >>> cls = engine.import_strategy_class("src.strategies.golden_cross.GoldenCrossStrategy")
            >>> isinstance(cls, type) and issubclass(cls, BaseStrategy)
            True
        """
        try:
            # class_path를 모듈 경로와 클래스 이름으로 분리
            module_path, class_name = class_path.rsplit(".", 1)

            # 모듈 import
            module = importlib.import_module(module_path)

            # 클래스 가져오기
            strategy_class = getattr(module, class_name)

            # BaseStrategy 상속 확인
            if not issubclass(strategy_class, BaseStrategy):
                raise ValueError(
                    f"Class {class_name} does not inherit from BaseStrategy"
                )

            logger.info(f"Successfully imported strategy class: {class_path}")
            return strategy_class

        except ImportError as e:
            logger.error(f"Failed to import strategy class {class_path}: {e}")
            raise
        except AttributeError as e:
            logger.error(f"Class {class_name} not found in module {module_path}: {e}")
            raise ImportError(f"Class {class_name} not found in module {module_path}")

    def create_strategy_instance(
        self, strategy_class: Type[BaseStrategy], parameters: Dict[str, any]
    ) -> BaseStrategy:
        """전략 인스턴스 생성.

        Args:
            strategy_class: 전략 클래스
            parameters: 전략 파라미터

        Returns:
            전략 인스턴스

        Raises:
            TypeError: 파라미터가 잘못된 경우
        """
        try:
            # 전략 클래스 생성자에 파라미터 전달
            strategy_instance = strategy_class(**parameters)
            logger.info(f"Created strategy instance: {strategy_class.__name__}")
            return strategy_instance

        except TypeError as e:
            logger.error(f"Failed to create strategy instance: {e}")
            raise

    def load_and_initialize_strategies(self) -> Dict[str, BaseStrategy]:
        """전략 설정을 로드하고 인스턴스 생성.

        Returns:
            전략 인스턴스 딕셔너리 (strategy_name -> BaseStrategy)

        Raises:
            FileNotFoundError: 설정 파일이 존재하지 않는 경우
            ImportError: 전략 클래스를 import할 수 없는 경우
            ValueError: 설정 검증 오류
        """
        # YAML에서 전략 설정 로드
        strategy_configs = self.load_strategies_from_yaml()

        # 각 전략 인스턴스 생성
        strategies = {}
        for config in strategy_configs:
            # 비활성화된 전략은 스킵
            if not config.enabled:
                logger.info(f"Skipping disabled strategy: {config.strategy_name}")
                continue

            try:
                # 전략 클래스 import
                strategy_class = self.import_strategy_class(config.class_path)

                # 전략 인스턴스 생성
                strategy_instance = self.create_strategy_instance(
                    strategy_class, config.parameters
                )

                # 저장
                strategies[config.strategy_name] = strategy_instance
                self.strategy_configs[config.strategy_name] = config

                logger.info(f"Initialized strategy: {config.strategy_name}")

            except Exception as e:
                logger.error(
                    f"Failed to initialize strategy {config.strategy_name}: {e}"
                )
                raise

        self.strategies = strategies
        return strategies

    def get_strategy(self, strategy_name: str) -> Optional[BaseStrategy]:
        """전략 인스턴스 조회.

        Args:
            strategy_name: 전략 이름

        Returns:
            전략 인스턴스. 존재하지 않으면 None.
        """
        return self.strategies.get(strategy_name)

    def enable_strategy(self, strategy_name: str) -> None:
        """전략 활성화.

        Args:
            strategy_name: 전략 이름

        Raises:
            KeyError: 전략이 존재하지 않는 경우
        """
        if strategy_name not in self.strategy_configs:
            raise KeyError(f"Strategy not found: {strategy_name}")

        config = self.strategy_configs[strategy_name]
        config.enabled = True

        # 비활성화 상태였다면 다시 초기화
        if strategy_name not in self.strategies:
            strategy_class = self.import_strategy_class(config.class_path)
            strategy_instance = self.create_strategy_instance(
                strategy_class, config.parameters
            )
            self.strategies[strategy_name] = strategy_instance

        logger.info(f"Enabled strategy: {strategy_name}")

    def disable_strategy(self, strategy_name: str) -> None:
        """전략 비활성화.

        Args:
            strategy_name: 전략 이름

        Raises:
            KeyError: 전략이 존재하지 않는 경우
        """
        if strategy_name not in self.strategy_configs:
            raise KeyError(f"Strategy not found: {strategy_name}")

        config = self.strategy_configs[strategy_name]
        config.enabled = False

        # 인스턴스 제거
        if strategy_name in self.strategies:
            del self.strategies[strategy_name]

        logger.info(f"Disabled strategy: {strategy_name}")

    def get_active_strategies(self) -> List[str]:
        """활성 전략 목록 조회.

        Returns:
            활성 전략 이름 리스트
        """
        return list(self.strategies.keys())

    def reload_strategies(self) -> Dict[str, BaseStrategy]:
        """전략 재로드.

        YAML 설정 파일을 다시 읽고 모든 전략을 재초기화합니다.

        Returns:
            전략 인스턴스 딕셔너리
        """
        logger.info("Reloading all strategies")

        # 기존 전략 제거
        self.strategies.clear()
        self.strategy_configs.clear()

        # 전략 재로드
        return self.load_and_initialize_strategies()

    async def initialize_historical_data(self, client) -> None:
        """전략에 필요한 과거 차트 데이터 로드.

        각 전략이 감시하는 종목에 대해 과거 차트 데이터를 조회하여
        전략의 chart_data_cache에 저장합니다.

        Args:
            client: KiwoomClient 인스턴스
        """
        from ..models import ChartInterval

        logger.info("Initializing historical chart data for strategies")

        for strategy_name, strategy in self.strategies.items():
            config = self.strategy_configs[strategy_name]

            logger.info(f"[{strategy_name}] Loading historical data for {len(config.symbols)} stocks")

            for stock_code in config.symbols:
                try:
                    # 전략이 차트 데이터를 사용하는지 확인 (set_chart_data 메서드 존재 여부)
                    if not hasattr(strategy, 'set_chart_data'):
                        logger.debug(
                            f"[{strategy_name}] Strategy does not use chart data, skipping"
                        )
                        continue

                    # 과거 100개 일봉 조회 (전략 priority에 따라 우선순위 부여)
                    chart_data = await client.get_chart_data(
                        stock_code=stock_code,
                        interval=ChartInterval.DAY,
                        limit=100,
                        priority=strategy.priority
                    )

                    if chart_data:
                        strategy.set_chart_data(stock_code, chart_data)
                        logger.info(
                            f"[{strategy_name}] Loaded {len(chart_data)} candles for {stock_code} "
                            f"(priority={strategy.priority.name})"
                        )
                    else:
                        logger.warning(
                            f"[{strategy_name}] No chart data returned for {stock_code}"
                        )

                except Exception as e:
                    logger.error(
                        f"[{strategy_name}] Failed to load chart data for {stock_code}: {e}",
                        exc_info=True
                    )

        logger.info("Historical chart data initialization completed")

    # T078: DataCollector 통합 메서드
    async def consume_market_data(self) -> None:
        """시장 데이터 큐에서 데이터를 소비하고 전략 평가 (T078).

        market_data_queue에서 Stock 데이터를 수신하여
        각 전략의 매수/매도 시그널을 평가합니다.

        Raises:
            RuntimeError: market_data_queue가 설정되지 않은 경우
        """
        if self.market_data_queue is None:
            raise RuntimeError("market_data_queue is not configured")

        if not self.strategies:
            logger.warning("No strategies loaded. Call load_and_initialize_strategies() first.")
            return

        self.running = True
        logger.info(
            f"Starting market data consumer with {len(self.strategies)} strategies"
        )

        try:
            while self.running:
                try:
                    # 큐에서 시장 데이터 수신 (1초 타임아웃)
                    stock = await asyncio.wait_for(
                        self.market_data_queue.get(),
                        timeout=1.0
                    )

                    # 모든 활성 전략에 대해 평가
                    await self._evaluate_strategies(stock)

                except asyncio.TimeoutError:
                    # 큐에 데이터 없음 (정상)
                    continue

                except Exception as e:
                    logger.error(f"Error consuming market data: {e}")
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            logger.info("Market data consumer cancelled")
            raise

        finally:
            self.running = False
            logger.info("Market data consumer stopped")

    async def _evaluate_strategies(self, stock: Stock) -> None:
        """모든 전략에 대해 시그널 평가 (내부 메서드).

        T087: 주문 생성 전 위험 관리 검증을 수행합니다.

        Args:
            stock: 평가할 종목 데이터.
        """
        # T087: 위험 관리 검증 (주문 전)
        if self.account and self.positions is not None:
            should_stop, risk_message = self.risk_manager.should_stop_trading(
                self.account,
                list(self.positions.values())
            )

            if should_stop:
                logger.error(f"[위험 관리] 거래 중단: {risk_message}")
                logger.info("전략 평가를 중단합니다.")
                return

            # 경고 메시지가 있다면 로그 출력 (중단은 아님)
            if risk_message:
                logger.warning(f"[위험 관리] 경고: {risk_message}")

        for strategy_name, strategy in self.strategies.items():
            try:
                # 매수 시그널 평가
                buy_signal = await strategy.evaluate_buy_signal(stock)

                if buy_signal:
                    logger.info(
                        f"[{strategy_name}] BUY signal for {stock.stock_code} "
                        f"at {stock.current_price}"
                    )

                    # 주문 실행 로직 (OrderExecutor 호출)
                    if self.order_executor is None:
                        logger.warning(
                            f"[{strategy_name}] OrderExecutor not configured, skipping order execution"
                        )
                        continue

                    # 진행 중인 주문이 있으면 스킵 (중복 주문 방지)
                    pending_orders = self.order_executor.get_pending_orders_by_stock(stock.stock_code)
                    buy_pending = [o for o in pending_orders if o.order_type == OrderType.BUY]
                    if buy_pending:
                        logger.debug(
                            f"[{strategy_name}] Skipping BUY signal for {stock.stock_code} - "
                            f"pending order exists (ID: {buy_pending[0].order_id})"
                        )
                        continue

                    try:
                        # 1. 계좌 정보 조회
                        account = await self.order_executor.client.get_account()

                        # 2. 전략 설정에서 포지션 크기 비율 가져오기
                        config = self.strategy_configs[strategy_name]
                        position_size_pct = config.position_size_pct

                        # 3. 가용 자금 계산 (예수금 * 비율)
                        available_capital = account.cash_balance * position_size_pct

                        logger.debug(
                            f"[{strategy_name}] Position sizing: "
                            f"cash={account.cash_balance:,.0f} * {position_size_pct} = "
                            f"{available_capital:,.0f} KRW"
                        )

                        # 4. 포지션 크기(수량) 계산
                        quantity = await strategy.calculate_position_size(stock, available_capital)

                        if quantity is None or quantity <= 0:
                            logger.info(
                                f"[{strategy_name}] Position size is 0 or None, skipping order"
                            )
                            continue

                        # 5. 주문 가격 설정
                        limit_price = None
                        if config.price_type == PriceType.LIMIT:
                            limit_price = stock.current_price

                        # 6. Order 객체 생성
                        order = Order(
                            account_number=account.account_number,
                            stock_code=stock.stock_code,
                            order_type=OrderType.BUY,
                            price_type=config.price_type,
                            quantity=quantity,
                            limit_price=limit_price,
                            strategy_name=strategy_name
                        )

                        order_type_str = order.order_type.value if hasattr(order.order_type, 'value') else str(order.order_type)
                        price_type_str = config.price_type.value if hasattr(config.price_type, 'value') else str(config.price_type)
                        logger.info(
                            f"[{strategy_name}] Creating order: "
                            f"{order_type_str} {order.stock_code} "
                            f"{order.quantity}주 @ {price_type_str} "
                            f"(ID: {order.order_id})"
                        )

                        # 7. 주문 실행 (OrderExecutor가 다시 한 번 위험 검증 수행 - T086)
                        success, error_msg, filled_order = await self.order_executor.execute_order(order)

                        if success:
                            logger.info(
                                f"[{strategy_name}] Order executed successfully: {order.order_id}"
                            )
                            if filled_order:
                                # filled_price가 있을 때만 가격 정보 출력 (PENDING 상태에서는 None)
                                if filled_order.filled_price is not None:
                                    logger.info(
                                        f"[{strategy_name}] Filled: {filled_order.filled_quantity}주 "
                                        f"@ {filled_order.filled_price:,.0f}원 "
                                        f"(Status: {filled_order.status.value})"
                                    )
                                else:
                                    logger.info(
                                        f"[{strategy_name}] Order submitted: {filled_order.order_id} "
                                        f"(Status: {filled_order.status.value})"
                                    )

                                # Phase 1.5: 매수 체결 시 손절가/익절가 자동 설정
                                if filled_order.order_type == OrderType.BUY and filled_order.status == OrderStatus.FILLED:
                                    await self._set_stop_loss_take_profit(filled_order, config)
                        else:
                            logger.error(
                                f"[{strategy_name}] Order execution failed: {error_msg}"
                            )

                    except Exception as e:
                        logger.error(
                            f"[{strategy_name}] Error creating/executing order for {stock.stock_code}: {e}",
                            exc_info=True
                        )

                # 매도 시그널 평가 (현재 포지션이 있는 경우)
                position = self.positions.get(stock.stock_code)
                if position:
                    try:
                        # 1. 전략의 매도 신호 확인
                        sell_signal = await strategy.evaluate_sell_signal(position, stock)

                        # 2. 손절/익절 트리거 확인 (병행 처리)
                        stop_loss_triggered = position.check_stop_loss_triggered()
                        take_profit_triggered = position.check_take_profit_triggered()

                        # 어느 하나라도 발생하면 매도
                        should_sell = sell_signal or stop_loss_triggered or take_profit_triggered

                        if should_sell:
                            # 매도 사유 수집
                            reasons = []
                            if sell_signal:
                                reasons.append("전략 신호")
                            if stop_loss_triggered:
                                reasons.append("손절")
                            if take_profit_triggered:
                                reasons.append("익절")

                            logger.info(
                                f"[{strategy_name}] SELL signal for {stock.stock_code} "
                                f"at {stock.current_price} (사유: {', '.join(reasons)})"
                            )

                            # 매도 주문 생성 및 실행
                            if self.order_executor is None:
                                logger.warning(
                                    f"[{strategy_name}] OrderExecutor not configured, skipping sell order"
                                )
                            else:
                                # 전략 설정에서 가격 타입 가져오기
                                config = self.strategy_configs[strategy_name]

                                # 매도 주문 가격 설정
                                limit_price = None
                                if config.price_type == PriceType.LIMIT:
                                    limit_price = stock.current_price

                                # Order 객체 생성 (전량 매도)
                                sell_order = Order(
                                    account_number=position.account_number,
                                    stock_code=stock.stock_code,
                                    order_type=OrderType.SELL,
                                    price_type=config.price_type,
                                    quantity=position.quantity,
                                    limit_price=limit_price,
                                    strategy_name=strategy_name
                                )

                                sell_order_type_str = sell_order.order_type.value if hasattr(sell_order.order_type, 'value') else str(sell_order.order_type)
                                sell_price_type_str = config.price_type.value if hasattr(config.price_type, 'value') else str(config.price_type)
                                logger.info(
                                    f"[{strategy_name}] Creating sell order: "
                                    f"{sell_order_type_str} {sell_order.stock_code} "
                                    f"{sell_order.quantity}주 @ {sell_price_type_str} "
                                    f"(ID: {sell_order.order_id})"
                                )

                                # 주문 실행
                                success, error_msg, filled_order = await self.order_executor.execute_order(sell_order)

                                if success:
                                    logger.info(
                                        f"[{strategy_name}] Sell order executed successfully: {sell_order.order_id}"
                                    )
                                    if filled_order:
                                        logger.info(
                                            f"[{strategy_name}] Filled: {filled_order.filled_quantity}주 "
                                            f"@ {filled_order.filled_price:,.0f}원 "
                                            f"(Status: {filled_order.status.value})"
                                        )
                                else:
                                    logger.error(
                                        f"[{strategy_name}] Sell order execution failed: {error_msg}"
                                    )

                    except Exception as e:
                        logger.error(
                            f"[{strategy_name}] Error evaluating/executing sell signal for {stock.stock_code}: {e}",
                            exc_info=True
                        )

            except Exception as e:
                logger.error(
                    f"Error evaluating strategy {strategy_name} for {stock.stock_code}: {e}"
                )

    async def run(self) -> None:
        """전략 엔진 실행 (T078).

        market_data_queue 및 order_book_queue에서 데이터를 소비하는
        백그라운드 태스크를 시작합니다.
        """
        if self.consumer_task is not None and not self.consumer_task.done():
            logger.warning("Strategy engine is already running")
            return

        self.consumer_task = asyncio.create_task(self.consume_market_data())
        logger.info("Strategy engine started (market data consumer)")

        # Phase 6: order_book_queue 소비 태스크 시작
        if self.order_book_queue is not None:
            self._order_book_task = asyncio.create_task(self._consume_order_book_data())
            logger.info("Strategy engine started (order book consumer)")

    async def stop(self) -> None:
        """전략 엔진 중지 (T078)."""
        if not self.running:
            return

        logger.info("Stopping strategy engine")
        self.running = False

        # Consumer 태스크 취소 대기
        if self.consumer_task and not self.consumer_task.done():
            self.consumer_task.cancel()
            try:
                await self.consumer_task
            except asyncio.CancelledError:
                pass

        # Phase 6: order_book 태스크 취소 대기
        if self._order_book_task and not self._order_book_task.done():
            self._order_book_task.cancel()
            try:
                await self._order_book_task
            except asyncio.CancelledError:
                pass

        logger.info("Strategy engine stopped")

    # =========================================================================
    # Phase 6: order_book_queue 소비 로직
    # =========================================================================

    async def _consume_order_book_data(self) -> None:
        """order_book_queue에서 호가 데이터를 소비하고 전략에 전달 (Phase 6).

        호가 기반 전략(OrderBookImbalance 등)에 실시간 호가 데이터를
        전달하여 전략 평가에 활용합니다.
        """
        if self.order_book_queue is None:
            logger.debug("[Phase6] order_book_queue not configured, skipping")
            return

        logger.info(
            "[Phase6] Starting order book data consumer for "
            f"{len(self.strategies)} strategies"
        )

        try:
            while self.running:
                try:
                    # 큐에서 호가 데이터 수신 (1초 타임아웃)
                    order_book_data = await asyncio.wait_for(
                        self.order_book_queue.get(),
                        timeout=1.0
                    )

                    # OrderBookData -> OrderBook 변환 후 전략에 전달
                    await self._distribute_order_book(order_book_data)

                except asyncio.TimeoutError:
                    # 큐에 데이터 없음 (정상)
                    continue
                except Exception as e:
                    logger.error(f"[Phase6] Error consuming order book data: {e}")
                    await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.info("[Phase6] Order book data consumer cancelled")
            raise
        finally:
            logger.info("[Phase6] Order book data consumer stopped")

    async def _distribute_order_book(
        self,
        data
    ) -> None:
        """호가 데이터를 관련 전략에 전달 (Phase 6).

        set_order_book() 메서드를 가진 전략에만 데이터를 전달합니다.

        Args:
            data: WebSocket에서 수신한 호가 데이터 (OrderBookData 또는 OrderBook).
        """
        # 이미 OrderBook인 경우 변환 건너뛰기
        if isinstance(data, OrderBook):
            order_book = data
            stock_code = data.stock_code
        else:
            # OrderBookData -> OrderBook 모델 변환
            stock_code = data.stock_code
            order_book = self._convert_order_book_data(data)

        # 호가 기반 전략에 데이터 전달
        for strategy_name, strategy in self.strategies.items():
            # set_order_book 메서드가 있는 전략만 처리
            if not hasattr(strategy, 'set_order_book'):
                continue

            # 해당 종목을 감시하는 전략인지 확인
            config = self.strategy_configs.get(strategy_name)
            if config and stock_code not in config.symbols:
                continue

            try:
                strategy.set_order_book(stock_code, order_book)
                logger.debug(
                    f"[Phase6] Order book updated: {strategy_name} <- {stock_code} "
                    f"(imbalance: {order_book.get_imbalance_ratio():.2%})"
                )
            except Exception as e:
                logger.error(
                    f"[Phase6] Error setting order book for {strategy_name}: {e}"
                )

    def _convert_order_book_data(self, data: OrderBookData) -> OrderBook:
        """OrderBookData(WebSocket 모델)를 OrderBook(도메인 모델)으로 변환.

        Args:
            data: WebSocket에서 수신한 호가 데이터.

        Returns:
            OrderBook 도메인 모델.
        """
        from ..models.order_book import OrderBookLevel

        # 호가 레벨 리스트 생성
        ask_levels = []
        bid_levels = []

        for i in range(min(len(data.ask_prices), 10)):
            if i < len(data.ask_prices) and i < len(data.ask_quantities):
                ask_levels.append(OrderBookLevel(
                    price=data.ask_prices[i],
                    quantity=data.ask_quantities[i]
                ))

        for i in range(min(len(data.bid_prices), 10)):
            if i < len(data.bid_prices) and i < len(data.bid_quantities):
                bid_levels.append(OrderBookLevel(
                    price=data.bid_prices[i],
                    quantity=data.bid_quantities[i]
                ))

        return OrderBook(
            stock_code=data.stock_code,
            ask_levels=ask_levels,
            bid_levels=bid_levels,
            total_ask_quantity=data.total_ask_quantity,
            total_bid_quantity=data.total_bid_quantity,
            timestamp=data.timestamp
        )

    async def _set_stop_loss_take_profit(
        self,
        filled_order: Order,
        config: StrategyConfig
    ) -> None:
        """매수 체결 후 포지션에 손절가/익절가를 자동 설정합니다 (Phase 1.5).

        전략 설정의 stop_loss_pct, take_profit_pct를 사용하여
        평균 매수가 기준으로 손절가/익절가를 계산하고 설정합니다.

        Args:
            filled_order: 체결된 매수 주문.
            config: 전략 설정 (parameters에 stop_loss_pct, take_profit_pct 포함).
        """
        try:
            # 포지션 확인
            position = self.positions.get(filled_order.stock_code)
            if not position:
                logger.warning(
                    f"[Phase1.5] 포지션을 찾을 수 없음: {filled_order.stock_code}"
                )
                return

            # 전략 파라미터에서 손절/익절 비율 가져오기
            stop_loss_pct = config.parameters.get("stop_loss_pct")
            take_profit_pct = config.parameters.get("take_profit_pct")

            if stop_loss_pct is None and take_profit_pct is None:
                logger.debug(
                    f"[Phase1.5] 전략 '{config.strategy_name}'에 손절/익절 설정 없음"
                )
                return

            # 손절가 설정
            if stop_loss_pct is not None:
                stop_loss_price = position.average_buy_price * (
                    Decimal("1") - Decimal(str(stop_loss_pct))
                )
                position.set_stop_loss(stop_loss_price)
                logger.info(
                    f"[Phase1.5] 손절가 설정: {filled_order.stock_code} "
                    f"@ {stop_loss_price:,.0f}원 "
                    f"(평균가 {position.average_buy_price:,.0f}원에서 {stop_loss_pct*100:.1f}% 하락)"
                )

            # 익절가 설정
            if take_profit_pct is not None:
                take_profit_price = position.average_buy_price * (
                    Decimal("1") + Decimal(str(take_profit_pct))
                )
                position.set_take_profit(take_profit_price)
                logger.info(
                    f"[Phase1.5] 익절가 설정: {filled_order.stock_code} "
                    f"@ {take_profit_price:,.0f}원 "
                    f"(평균가 {position.average_buy_price:,.0f}원에서 {take_profit_pct*100:.1f}% 상승)"
                )

        except ValueError as e:
            # set_stop_loss/set_take_profit에서 발생하는 검증 오류
            logger.warning(
                f"[Phase1.5] 손절/익절 가격 검증 실패: {e}"
            )
        except Exception as e:
            logger.error(
                f"[Phase1.5] 손절/익절 설정 중 오류: {e}",
                exc_info=True
            )
