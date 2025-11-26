"""WebSocket 기반 실시간 데이터 수집기.

WebSocket으로 실시간 데이터를 수신하고 적절한 큐로 분배합니다.
WebSocket 연결 실패 시 REST API 폴링으로 폴백합니다.
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Set
from zoneinfo import ZoneInfo

from ..api.kiwoom_client import KiwoomClient
from ..api.kiwoom_websocket import KiwoomWebSocketClient, RealTimeType
from ..api.websocket_exceptions import WebSocketError
from ..cache.price_cache import RedisPriceCache
from ..cache.redis_manager import RedisManager
from ..cache.redis_stream_manager import RedisStreamManager
from ..config.settings import Settings
from ..models.order_book import OrderBook
from ..models.realtime_data import (
    BalanceUpdateData,
    OrderBookData,
    OrderExecutionData,
    TradeData,
)
from ..models.stock import Stock
from ..utils.logger import get_logger
from .data_collector import DataCollector
from .websocket_data_transformer import WebSocketDataTransformer

KST = ZoneInfo("Asia/Seoul")
logger = get_logger(__name__)


class WebSocketDataCollector:
    """WebSocket 기반 실시간 데이터 수집기.

    3개의 큐로 데이터를 분배합니다:
    - market_data_queue: 0B 체결 데이터 (Stock)
    - order_book_queue: 0D 호가 데이터 (OrderBook)
    - order_event_queue: 00/04 주문/잔고 알림

    WebSocket 연결 실패 시 REST API 폴링으로 자동 전환됩니다.

    Example:
        ```python
        collector = WebSocketDataCollector(
            config=settings,
            kiwoom_client=client,
            market_data_queue=asyncio.Queue(),
            order_book_queue=asyncio.Queue(),
            order_event_queue=asyncio.Queue(),
            stock_codes=["005930", "000660"],
        )
        await collector.run()
        ```
    """

    def __init__(
        self,
        config: Settings,
        kiwoom_client: KiwoomClient,
        market_data_queue: asyncio.Queue,
        order_book_queue: Optional[asyncio.Queue] = None,
        order_event_queue: Optional[asyncio.Queue] = None,
        stock_codes: Optional[List[str]] = None,
        fallback_to_rest: bool = True,
        redis_manager: Optional[RedisManager] = None,
        stream_manager: Optional[RedisStreamManager] = None,
    ):
        """데이터 수집기 초기화.

        Args:
            config: 애플리케이션 설정.
            kiwoom_client: 키움 REST API 클라이언트.
            market_data_queue: 체결 데이터 큐 (0B -> Stock).
            order_book_queue: 호가 데이터 큐 (0D -> OrderBook).
            order_event_queue: 주문/잔고 이벤트 큐 (00, 04).
            stock_codes: 모니터링할 종목코드 목록.
            fallback_to_rest: WebSocket 실패 시 REST 폴백 사용.
            redis_manager: Redis 매니저 (캐시용).
            stream_manager: Redis Streams 매니저 (버퍼용, Queue 대체).
        """
        self.config = config
        self.kiwoom_client = kiwoom_client
        self.market_data_queue = market_data_queue
        self.order_book_queue = order_book_queue
        self.order_event_queue = order_event_queue
        self.stock_codes = set(stock_codes) if stock_codes else set()
        self.fallback_to_rest = fallback_to_rest

        # WebSocket 클라이언트
        # kiwoom_trading_mode: "real" = 실전투자, "virtual"/"mock" = 모의투자
        trading_mode = getattr(config, "kiwoom_trading_mode", "virtual")
        is_mock = trading_mode != "real"  # "real"이 아니면 모두 모의투자
        self.ws_client = KiwoomWebSocketClient(
            kiwoom_client=kiwoom_client,
            websocket_url=getattr(config, "websocket_url", None),
            is_mock=is_mock,
            auto_reconnect=True,
            heartbeat_interval=getattr(config, "websocket_heartbeat_interval", 30.0),
            reconnect_delay=getattr(config, "websocket_reconnect_delay", 1.0),
            max_reconnect_delay=getattr(config, "websocket_max_reconnect_delay", 60.0),
        )

        # 데이터 변환기
        self.transformer = WebSocketDataTransformer()

        # Redis 캐시 (선택)
        self.redis_manager = redis_manager
        self.redis_price_cache: Optional[RedisPriceCache] = None
        if redis_manager:
            self.redis_price_cache = RedisPriceCache(redis_manager)

        # Redis Streams (Queue 대체 버퍼)
        self.stream_manager = stream_manager
        self._stream_name = "market_data"  # Stream 이름

        # REST 폴백용 데이터 수집기 (lazy initialization)
        self._rest_collector: Optional[DataCollector] = None

        # 상태
        self.running = False
        self.using_websocket = False
        self._last_data_time = datetime.now(KST)
        self._stats = {
            "trade_messages": 0,
            "order_book_messages": 0,
            "order_execution_messages": 0,
            "balance_update_messages": 0,
            "websocket_reconnects": 0,
            "rest_fallback_count": 0,
            "stream_xadd_count": 0,
            "stream_xadd_errors": 0,
        }

        # 콜백 등록
        self._setup_callbacks()

    def _setup_callbacks(self) -> None:
        """WebSocket 콜백 등록."""
        self.ws_client.on_trade_data = self._on_trade_data
        self.ws_client.on_order_book = self._on_order_book
        self.ws_client.on_order_execution = self._on_order_execution
        self.ws_client.on_balance_update = self._on_balance_update
        self.ws_client.on_connect = self._on_connect
        self.ws_client.on_disconnect = self._on_disconnect
        self.ws_client.on_error = self._on_error

    async def run(self) -> None:
        """메인 실행 루프.

        WebSocket 연결을 시도하고, 실패 시 REST 폴백으로 전환합니다.
        """
        self.running = True
        logger.info(
            f"Starting WebSocket data collector with {len(self.stock_codes)} stocks"
        )

        while self.running:
            try:
                # WebSocket 연결 시도
                if await self.ws_client.connect():
                    self.using_websocket = True
                    logger.info("WebSocket connected, waiting for server authentication...")

                    # 백그라운드에서 메시지 수신 시작 (인증 메시지 수신용)
                    receive_task = asyncio.create_task(self.ws_client.run_forever())

                    # 서버 인증 완료 대기 (키움증권 WebSocket 요구사항)
                    # "로그인 인증이 들어오기 전에 다른 전문이 들어왔습니다" 오류 방지
                    auth_success = await self.ws_client.wait_for_auth(timeout=10.0)

                    if not auth_success:
                        logger.warning("WebSocket authentication timeout, falling back to REST")
                        receive_task.cancel()
                        try:
                            await receive_task
                        except asyncio.CancelledError:
                            pass
                        raise WebSocketError("Authentication timeout")

                    logger.info("WebSocket authenticated, subscribing to real-time data")

                    # 시세 등록 (0B, 0D)
                    if self.stock_codes:
                        types_to_subscribe = [RealTimeType.TRADE.value]
                        if self.order_book_queue:
                            types_to_subscribe.append(RealTimeType.ORDER_BOOK.value)

                        await self.ws_client.subscribe(
                            list(self.stock_codes),
                            types=types_to_subscribe,
                            refresh=True,
                        )

                    # 주문/잔고 알림 등록 (00, 04) - 종목코드 불필요
                    if self.order_event_queue:
                        await self.ws_client.subscribe(
                            [""],  # 빈 종목코드
                            types=[
                                RealTimeType.ORDER_EXECUTION.value,
                                RealTimeType.BALANCE.value,
                            ],
                            refresh=True,
                        )

                    # 메시지 수신 루프 완료 대기
                    await receive_task

            except WebSocketError as e:
                logger.error(f"WebSocket error: {e}")
                self.using_websocket = False
                self._stats["websocket_reconnects"] += 1

                if self.fallback_to_rest and self.running:
                    logger.info("Falling back to REST polling")
                    self._stats["rest_fallback_count"] += 1
                    await self._run_rest_fallback()
                else:
                    # 재연결 대기
                    await asyncio.sleep(5)

            except asyncio.CancelledError:
                logger.info("WebSocket data collector cancelled")
                break

            except Exception as e:
                logger.error(f"Unexpected error in WebSocket collector: {e}")
                await asyncio.sleep(5)

    async def _run_rest_fallback(self) -> None:
        """REST API 폴링 폴백 실행."""
        if not self.fallback_to_rest:
            return

        logger.info("Running REST fallback polling")

        # REST 수집기 초기화 (lazy)
        if self._rest_collector is None:
            self._rest_collector = DataCollector(
                config=self.config,
                client=self.kiwoom_client,
                market_data_queue=self.market_data_queue,
                stock_codes=list(self.stock_codes),
            )

        try:
            # REST 폴링 실행 (백그라운드에서 WebSocket 재연결 시도)
            rest_task = asyncio.create_task(self._rest_collector.run())
            reconnect_task = asyncio.create_task(self._try_websocket_reconnect())

            # 둘 중 하나가 완료될 때까지 대기
            done, pending = await asyncio.wait(
                [rest_task, reconnect_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # 미완료 태스크 취소
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            logger.error(f"REST fallback error: {e}")

    async def _try_websocket_reconnect(self) -> None:
        """백그라운드에서 WebSocket 재연결 시도."""
        await asyncio.sleep(30)  # 30초 후 재연결 시도

        while self.running and not self.using_websocket:
            try:
                if await self.ws_client.connect():
                    # 인증 대기를 위해 메시지 수신 시작
                    receive_task = asyncio.create_task(self.ws_client.run_forever())

                    # 인증 완료 대기
                    auth_success = await self.ws_client.wait_for_auth(timeout=10.0)

                    if auth_success:
                        logger.info("WebSocket reconnected and authenticated from REST fallback")
                        self.using_websocket = True
                        # receive_task는 계속 실행 (run 메서드에서 관리)
                        return
                    else:
                        logger.warning("WebSocket reconnect auth timeout")
                        receive_task.cancel()
                        try:
                            await receive_task
                        except asyncio.CancelledError:
                            pass
                        await self.ws_client.disconnect()
            except WebSocketError:
                pass

            await asyncio.sleep(30)

    async def _on_trade_data(self, trade: TradeData) -> None:
        """0B 체결 데이터 처리.

        Args:
            trade: 체결 데이터.
        """
        self._stats["trade_messages"] += 1
        self._last_data_time = datetime.now(KST)

        # Stock 모델로 변환
        stock = self.transformer.trade_to_stock(trade)

        # Redis Streams 또는 Queue에 추가
        if self.stream_manager:
            # Redis Streams (XADD) - 데이터 손실 없음
            try:
                await self.stream_manager.xadd(
                    self._stream_name,
                    {
                        "stock_code": stock.stock_code,
                        "stock_name": stock.stock_name,
                        "current_price": str(stock.current_price),
                        "volume": stock.volume,
                        "change": str(stock.change) if stock.change else "0",
                        "change_rate": str(stock.change_rate) if stock.change_rate else "0",
                        "timestamp": trade.timestamp.isoformat(),
                    },
                )
                self._stats["stream_xadd_count"] += 1
            except Exception as e:
                self._stats["stream_xadd_errors"] += 1
                logger.warning(f"Redis XADD failed, falling back to queue: {e}")
                # Stream 실패 시 Queue 폴백
                try:
                    self.market_data_queue.put_nowait(stock)
                except asyncio.QueueFull:
                    logger.warning(f"market_data_queue full, dropping data for {stock.stock_code}")
        else:
            # 기존 Queue 방식
            try:
                self.market_data_queue.put_nowait(stock)
            except asyncio.QueueFull:
                logger.warning(f"market_data_queue full, dropping data for {stock.stock_code}")

        # Redis 캐시 업데이트
        if self.redis_price_cache:
            try:
                await self.redis_price_cache.set(
                    stock.stock_code,
                    {
                        "code": stock.stock_code,
                        "price": float(stock.current_price),
                        "volume": stock.volume,
                        "timestamp": trade.timestamp.timestamp(),
                    },
                )
            except Exception as e:
                logger.debug(f"Redis cache update failed: {e}")

    async def _on_order_book(self, data: OrderBookData) -> None:
        """0D 호가 데이터 처리.

        Args:
            data: 호가 데이터.
        """
        if not self.order_book_queue:
            return

        self._stats["order_book_messages"] += 1
        self._last_data_time = datetime.now(KST)

        # OrderBook 모델로 변환
        order_book = self.transformer.order_book_data_to_model(data)

        # 큐에 추가
        try:
            self.order_book_queue.put_nowait(order_book)
        except asyncio.QueueFull:
            logger.warning(
                f"order_book_queue full, dropping data for {data.stock_code}"
            )

    async def _on_order_execution(self, data: OrderExecutionData) -> None:
        """00 주문체결 알림 처리.

        Args:
            data: 주문체결 데이터.
        """
        if not self.order_event_queue:
            return

        self._stats["order_execution_messages"] += 1
        logger.info(
            f"Order execution: {data.stock_code} "
            f"status={data.order_status} "
            f"filled={data.filled_quantity}@{data.filled_price}"
        )

        # 큐에 추가
        try:
            self.order_event_queue.put_nowait(data)
        except asyncio.QueueFull:
            logger.warning("order_event_queue full, dropping order execution data")

    async def _on_balance_update(self, data: BalanceUpdateData) -> None:
        """04 잔고 변동 처리.

        Args:
            data: 잔고 데이터.
        """
        if not self.order_event_queue:
            return

        self._stats["balance_update_messages"] += 1
        logger.info(
            f"Balance update: {data.stock_code} "
            f"action={data.action} "
            f"holding={data.holding_quantity}"
        )

        # 큐에 추가
        try:
            self.order_event_queue.put_nowait(data)
        except asyncio.QueueFull:
            logger.warning("order_event_queue full, dropping balance update data")

    async def _on_connect(self) -> None:
        """WebSocket 연결 성공 콜백."""
        logger.info("WebSocket connected callback")
        self.using_websocket = True

    async def _on_disconnect(self, reason: str) -> None:
        """WebSocket 연결 해제 콜백.

        Args:
            reason: 연결 해제 사유.
        """
        logger.warning(f"WebSocket disconnected: {reason}")
        self.using_websocket = False

    async def _on_error(self, error: Exception) -> None:
        """WebSocket 오류 콜백.

        Args:
            error: 발생한 오류.
        """
        logger.error(f"WebSocket error callback: {error}")

    async def stop(self) -> None:
        """데이터 수집 중지."""
        logger.info("Stopping WebSocket data collector")
        self.running = False

        # WebSocket 연결 해제
        await self.ws_client.disconnect()

        # REST 수집기 중지
        if self._rest_collector:
            await self._rest_collector.stop()

        logger.info("WebSocket data collector stopped")

    def add_stock_codes(self, stock_codes: List[str]) -> None:
        """종목 추가.

        Args:
            stock_codes: 추가할 종목코드 목록.
        """
        new_codes = set(stock_codes) - self.stock_codes
        if not new_codes:
            return

        self.stock_codes.update(new_codes)
        logger.info(f"Added {len(new_codes)} stock codes")

        # WebSocket 구독 추가
        if self.using_websocket:
            asyncio.create_task(self._subscribe_new_codes(list(new_codes)))

    def update_stock_codes(self, stock_codes: List[str]) -> None:
        """감시 대상 종목 코드 업데이트 (DataCollector 호환).

        새 종목은 추가하고, 제거된 종목은 구독 해제합니다.

        Args:
            stock_codes: 새 종목코드 목록.
        """
        new_codes_set = set(stock_codes)

        # 추가할 종목
        to_add = new_codes_set - self.stock_codes
        # 제거할 종목
        to_remove = self.stock_codes - new_codes_set

        if to_add:
            self.add_stock_codes(list(to_add))
        if to_remove:
            self.remove_stock_codes(list(to_remove))

    def remove_stock_codes(self, stock_codes: List[str]) -> None:
        """종목 제거.

        Args:
            stock_codes: 제거할 종목코드 목록.
        """
        codes_to_remove = set(stock_codes) & self.stock_codes
        if not codes_to_remove:
            return

        self.stock_codes -= codes_to_remove
        logger.info(f"Removed {len(codes_to_remove)} stock codes")

        # WebSocket 구독 해제
        if self.using_websocket:
            asyncio.create_task(
                self.ws_client.unsubscribe(
                    list(codes_to_remove),
                    types=[RealTimeType.TRADE.value, RealTimeType.ORDER_BOOK.value],
                )
            )

    async def _subscribe_new_codes(self, stock_codes: List[str]) -> None:
        """새 종목 구독.

        Args:
            stock_codes: 종목코드 목록.
        """
        try:
            types = [RealTimeType.TRADE.value]
            if self.order_book_queue:
                types.append(RealTimeType.ORDER_BOOK.value)

            await self.ws_client.subscribe(stock_codes, types=types, refresh=True)
        except Exception as e:
            logger.error(f"Failed to subscribe new codes: {e}")

    def get_stats(self) -> Dict:
        """통계 정보 반환.

        Returns:
            수집 통계 딕셔너리.
        """
        return {
            **self._stats,
            "using_websocket": self.using_websocket,
            "using_redis_streams": self.stream_manager is not None,
            "connected": self.ws_client.is_connected,
            "subscribed_stocks": len(self.stock_codes),
            "last_data_time": self._last_data_time.isoformat(),
        }

    def update_stock_name_cache(self, stock_code: str, stock_name: str) -> None:
        """종목명 캐시 업데이트.

        Args:
            stock_code: 종목코드.
            stock_name: 종목명.
        """
        self.transformer.update_stock_name_cache(stock_code, stock_name)
