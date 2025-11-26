"""키움증권 WebSocket API 클라이언트.

실시간 시세 데이터를 WebSocket으로 수신합니다.
- 0B: 주식체결
- 0D: 주식호가잔량
- 00: 주문체결 알림
- 04: 잔고 변동
"""

import asyncio
import json
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set
from zoneinfo import ZoneInfo

import websockets
from websockets import State
from websockets.client import WebSocketClientProtocol
from websockets.exceptions import (
    ConnectionClosed,
    ConnectionClosedError,
    ConnectionClosedOK,
    InvalidStatusCode,
    WebSocketException,
)

from ..models.realtime_data import (
    BalanceUpdateData,
    OrderBookData,
    OrderExecutionData,
    TradeData,
)
from ..services.websocket_data_transformer import WebSocketDataTransformer
from ..utils.logger import get_logger
from .kiwoom_client import KiwoomClient
from .websocket_exceptions import (
    WebSocketAuthError,
    WebSocketConnectionError,
    WebSocketMessageError,
    WebSocketReconnectError,
    WebSocketSubscriptionError,
)

KST = ZoneInfo("Asia/Seoul")
logger = get_logger(__name__)

# WebSocket URL
WEBSOCKET_URL_REAL = "wss://api.kiwoom.com:10000/api/dostk/websocket"
WEBSOCKET_URL_MOCK = "wss://mockapi.kiwoom.com:10000/api/dostk/websocket"


class ConnectionState(str, Enum):
    """WebSocket 연결 상태."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class RealTimeType(str, Enum):
    """실시간 데이터 타입."""

    TRADE = "0B"  # 주식체결
    ORDER_BOOK = "0D"  # 주식호가잔량
    ORDER_EXECUTION = "00"  # 주문체결
    BALANCE = "04"  # 잔고


class KiwoomWebSocketClient:
    """키움증권 WebSocket 클라이언트.

    실시간 시세를 WebSocket으로 수신하고 콜백을 통해 데이터를 전달합니다.

    Example:
        ```python
        async with KiwoomClient(...) as client:
            ws_client = KiwoomWebSocketClient(client)
            ws_client.on_trade_data = handle_trade
            ws_client.on_order_book = handle_order_book

            await ws_client.connect()
            await ws_client.subscribe(["005930", "000660"], ["0B", "0D"])
            # 메시지 수신 루프
            await ws_client.run_forever()
        ```
    """

    def __init__(
        self,
        kiwoom_client: KiwoomClient,
        websocket_url: Optional[str] = None,
        is_mock: bool = True,
        auto_reconnect: bool = True,
        heartbeat_interval: float = 30.0,
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 60.0,
        max_reconnect_attempts: int = 0,  # 0 = unlimited
    ):
        """WebSocket 클라이언트 초기화.

        Args:
            kiwoom_client: REST API 클라이언트 (토큰 관리용).
            websocket_url: WebSocket URL (None이면 is_mock에 따라 자동 선택).
            is_mock: 모의투자 여부.
            auto_reconnect: 자동 재연결 활성화.
            heartbeat_interval: 하트비트 간격 (초).
            reconnect_delay: 초기 재연결 대기 시간 (초).
            max_reconnect_delay: 최대 재연결 대기 시간 (초).
            max_reconnect_attempts: 최대 재연결 시도 횟수 (0=무제한).
        """
        self.kiwoom_client = kiwoom_client
        self.is_mock = is_mock

        # WebSocket URL 설정
        if websocket_url:
            self.websocket_url = websocket_url
        else:
            self.websocket_url = WEBSOCKET_URL_MOCK if is_mock else WEBSOCKET_URL_REAL

        # 재연결 설정
        self.auto_reconnect = auto_reconnect
        self.heartbeat_interval = heartbeat_interval
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts
        self._current_reconnect_delay = reconnect_delay
        self._reconnect_attempts = 0

        # 연결 상태
        self._state = ConnectionState.DISCONNECTED
        self._websocket: Optional[WebSocketClientProtocol] = None
        self._running = False

        # 구독 관리
        self._subscribed_items: Dict[str, Set[str]] = {}  # type -> set of stock_codes
        self._group_number = "1"

        # 데이터 변환기
        self._transformer = WebSocketDataTransformer()

        # 콜백 함수
        self.on_trade_data: Optional[Callable[[TradeData], Awaitable[None]]] = None
        self.on_order_book: Optional[Callable[[OrderBookData], Awaitable[None]]] = None
        self.on_order_execution: Optional[
            Callable[[OrderExecutionData], Awaitable[None]]
        ] = None
        self.on_balance_update: Optional[
            Callable[[BalanceUpdateData], Awaitable[None]]
        ] = None
        self.on_connect: Optional[Callable[[], Awaitable[None]]] = None
        self.on_disconnect: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_error: Optional[Callable[[Exception], Awaitable[None]]] = None

        # 내부 태스크
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._receive_task: Optional[asyncio.Task] = None

    @property
    def state(self) -> ConnectionState:
        """현재 연결 상태."""
        return self._state

    @property
    def is_connected(self) -> bool:
        """연결 여부 (실제 WebSocket 상태 확인)."""
        return (
            self._state == ConnectionState.CONNECTED
            and self._websocket is not None
            and self._websocket.state == State.OPEN
        )

    async def connect(self) -> bool:
        """WebSocket 연결.

        Returns:
            연결 성공 여부.

        Raises:
            WebSocketConnectionError: 연결 실패.
            WebSocketAuthError: 인증 실패.
        """
        # 실제 WebSocket 연결 상태 확인 (state만으로는 부족)
        if self._state == ConnectionState.CONNECTED and self._websocket is not None:
            # 실제 연결이 살아있는지 확인 (websockets 15.x: state 속성 사용)
            if self._websocket.state == State.OPEN:
                logger.warning("Already connected to WebSocket")
                return True
            else:
                # 연결은 끊어졌지만 state가 CONNECTED인 경우 - 상태 초기화
                logger.info("WebSocket was closed, reconnecting...")
                self._state = ConnectionState.DISCONNECTED
                self._websocket = None

        self._state = ConnectionState.CONNECTING
        logger.info(f"Connecting to WebSocket: {self.websocket_url}")

        try:
            # 토큰 갱신 확인
            await self.kiwoom_client._ensure_authenticated()
            token = self.kiwoom_client.access_token

            if not token:
                raise WebSocketAuthError("No access token available")

            # WebSocket 연결
            headers = {
                "authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            }

            self._websocket = await websockets.connect(
                self.websocket_url,
                additional_headers=headers,
                ping_interval=self.heartbeat_interval,
                ping_timeout=10,
                close_timeout=5,
            )

            self._state = ConnectionState.CONNECTED
            self._current_reconnect_delay = self.reconnect_delay
            self._reconnect_attempts = 0
            self._running = True

            logger.info("WebSocket connected successfully")

            # 연결 콜백 호출
            if self.on_connect:
                await self.on_connect()

            return True

        except InvalidStatusCode as e:
            self._state = ConnectionState.ERROR
            if e.status_code == 401:
                raise WebSocketAuthError(
                    f"Authentication failed: {e}", status_code=401
                )
            raise WebSocketConnectionError(
                f"Connection failed with status {e.status_code}: {e}"
            )

        except WebSocketException as e:
            self._state = ConnectionState.ERROR
            raise WebSocketConnectionError(f"WebSocket connection error: {e}")

        except Exception as e:
            self._state = ConnectionState.ERROR
            raise WebSocketConnectionError(f"Unexpected connection error: {e}")

    async def disconnect(self) -> None:
        """WebSocket 연결 해제."""
        self._running = False
        self._state = ConnectionState.DISCONNECTED

        # 내부 태스크 취소
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        # WebSocket 연결 종료
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception as e:
                logger.warning(f"Error closing WebSocket: {e}")
            self._websocket = None

        logger.info("WebSocket disconnected")

        # 연결 해제 콜백 호출
        if self.on_disconnect:
            await self.on_disconnect("Manual disconnect")

    async def subscribe(
        self,
        stock_codes: List[str],
        types: List[str] = None,
        refresh: bool = True,
    ) -> bool:
        """실시간 시세 등록.

        Args:
            stock_codes: 종목코드 목록.
            types: 실시간 타입 목록 (기본: ["0B", "0D"]).
            refresh: 기존 등록 유지 여부 (True=유지, False=해제).

        Returns:
            등록 성공 여부.

        Raises:
            WebSocketSubscriptionError: 등록 실패.
        """
        if not self.is_connected or not self._websocket:
            raise WebSocketSubscriptionError("Not connected to WebSocket")

        if types is None:
            types = [RealTimeType.TRADE.value, RealTimeType.ORDER_BOOK.value]

        # 등록 메시지 생성
        message = {
            "trnm": "REG",
            "grp_no": self._group_number,
            "refresh": "1" if refresh else "0",
            "data": [{"item": stock_codes, "type": types}],
        }

        try:
            await self._websocket.send(json.dumps(message))
            logger.info(
                f"Subscription request sent: {len(stock_codes)} stocks, types={types}"
            )

            # 응답 대기
            response = await asyncio.wait_for(self._websocket.recv(), timeout=5.0)
            response_data = json.loads(response)

            if response_data.get("return_code") == 0:
                # 구독 목록 업데이트
                for real_type in types:
                    if real_type not in self._subscribed_items:
                        self._subscribed_items[real_type] = set()
                    self._subscribed_items[real_type].update(stock_codes)

                logger.info(f"Subscription successful: {response_data}")
                return True
            else:
                error_msg = response_data.get("return_msg", "Unknown error")
                raise WebSocketSubscriptionError(f"Subscription failed: {error_msg}")

        except asyncio.TimeoutError:
            raise WebSocketSubscriptionError("Subscription timeout")
        except json.JSONDecodeError as e:
            raise WebSocketSubscriptionError(f"Invalid response format: {e}")

    async def unsubscribe(
        self,
        stock_codes: List[str],
        types: List[str] = None,
    ) -> bool:
        """실시간 시세 해제.

        Args:
            stock_codes: 종목코드 목록.
            types: 실시간 타입 목록.

        Returns:
            해제 성공 여부.
        """
        if not self.is_connected or not self._websocket:
            return False

        if types is None:
            types = [RealTimeType.TRADE.value, RealTimeType.ORDER_BOOK.value]

        message = {
            "trnm": "REMOVE",
            "grp_no": self._group_number,
            "refresh": "",
            "data": [{"item": stock_codes, "type": types}],
        }

        try:
            await self._websocket.send(json.dumps(message))
            logger.info(f"Unsubscription request sent: {stock_codes}")

            # 구독 목록에서 제거
            for real_type in types:
                if real_type in self._subscribed_items:
                    self._subscribed_items[real_type] -= set(stock_codes)

            return True

        except Exception as e:
            logger.error(f"Unsubscription error: {e}")
            return False

    async def run_forever(self) -> None:
        """메시지 수신 루프 실행.

        연결이 끊기면 자동 재연결을 시도합니다.
        """
        self._running = True

        while self._running:
            try:
                if not self.is_connected:
                    if self.auto_reconnect:
                        await self._reconnect()
                    else:
                        break

                await self._receive_messages()

            except (ConnectionClosed, ConnectionClosedError, ConnectionClosedOK) as e:
                logger.warning(f"WebSocket connection closed: {e}")
                self._state = ConnectionState.DISCONNECTED
                if self.on_disconnect:
                    await self.on_disconnect(str(e))

                if self.auto_reconnect and self._running:
                    await self._reconnect()
                else:
                    break

            except Exception as e:
                logger.error(f"Unexpected error in receive loop: {e}")
                if self.on_error:
                    await self.on_error(e)

                if self.auto_reconnect and self._running:
                    await asyncio.sleep(self._current_reconnect_delay)
                else:
                    break

    async def _receive_messages(self) -> None:
        """메시지 수신 및 처리."""
        if not self._websocket:
            return

        async for message in self._websocket:
            if not self._running:
                break

            try:
                await self._handle_message(message)
            except Exception as e:
                logger.error(f"Error handling message: {e}")
                if self.on_error:
                    await self.on_error(e)

    async def _handle_message(self, raw_message: str) -> None:
        """수신 메시지 처리.

        Args:
            raw_message: 수신된 JSON 메시지.
        """
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError as e:
            raise WebSocketMessageError(f"Invalid JSON message: {e}")

        trnm = data.get("trnm", "")

        # 등록/해제 응답
        if trnm in ("REG", "REMOVE"):
            logger.debug(f"Subscription response: {data}")
            return

        # 실시간 데이터
        if trnm == "REAL":
            await self._handle_realtime_data(data)
            return

        logger.debug(f"Unknown message type: {trnm}")

    async def _handle_realtime_data(self, data: Dict[str, Any]) -> None:
        """실시간 데이터 처리.

        Args:
            data: 실시간 데이터 메시지.
        """
        data_list = data.get("data", [])

        for item_data in data_list:
            real_type = item_data.get("type", "")
            item = item_data.get("item", "")
            values = item_data.get("values", {})

            try:
                if real_type == RealTimeType.TRADE.value:
                    # 0B: 주식체결
                    trade_data = self._transformer.parse_trade_data(item, values)
                    if self.on_trade_data:
                        await self.on_trade_data(trade_data)

                elif real_type == RealTimeType.ORDER_BOOK.value:
                    # 0D: 주식호가잔량
                    order_book_data = self._transformer.parse_order_book_data(
                        item, values
                    )
                    if self.on_order_book:
                        await self.on_order_book(order_book_data)

                elif real_type == RealTimeType.ORDER_EXECUTION.value:
                    # 00: 주문체결
                    execution_data = self._transformer.parse_order_execution_data(
                        item, values
                    )
                    if self.on_order_execution:
                        await self.on_order_execution(execution_data)

                elif real_type == RealTimeType.BALANCE.value:
                    # 04: 잔고
                    balance_data = self._transformer.parse_balance_update_data(
                        item, values
                    )
                    if self.on_balance_update:
                        await self.on_balance_update(balance_data)

                else:
                    logger.debug(f"Unknown realtime type: {real_type}")

            except Exception as e:
                logger.error(f"Error processing {real_type} data for {item}: {e}")

    async def _reconnect(self) -> None:
        """재연결 시도."""
        self._state = ConnectionState.RECONNECTING
        self._reconnect_attempts += 1

        if (
            self.max_reconnect_attempts > 0
            and self._reconnect_attempts > self.max_reconnect_attempts
        ):
            logger.error(
                f"Max reconnection attempts ({self.max_reconnect_attempts}) exceeded"
            )
            raise WebSocketReconnectError("Max reconnection attempts exceeded")

        logger.info(
            f"Reconnecting in {self._current_reconnect_delay:.1f}s "
            f"(attempt {self._reconnect_attempts})"
        )

        await asyncio.sleep(self._current_reconnect_delay)

        # Exponential backoff
        self._current_reconnect_delay = min(
            self._current_reconnect_delay * 2, self.max_reconnect_delay
        )

        try:
            # 토큰 갱신
            await self.kiwoom_client._refresh_token()

            # 재연결
            await self.connect()

            # 기존 구독 복원
            await self._restore_subscriptions()

            logger.info("Reconnection successful")

        except Exception as e:
            logger.error(f"Reconnection failed: {e}")
            self._state = ConnectionState.ERROR
            if self.on_error:
                await self.on_error(e)

    async def _restore_subscriptions(self) -> None:
        """기존 구독 복원."""
        if not self._subscribed_items:
            return

        logger.info("Restoring subscriptions...")

        for real_type, stock_codes in self._subscribed_items.items():
            if stock_codes:
                try:
                    await self.subscribe(
                        list(stock_codes), types=[real_type], refresh=True
                    )
                except WebSocketSubscriptionError as e:
                    logger.error(f"Failed to restore subscription for {real_type}: {e}")

    def get_subscribed_items(self, real_type: str = None) -> Set[str]:
        """구독 중인 종목 조회.

        Args:
            real_type: 실시간 타입 (None이면 전체).

        Returns:
            구독 중인 종목코드 집합.
        """
        if real_type:
            return self._subscribed_items.get(real_type, set()).copy()

        all_items: Set[str] = set()
        for items in self._subscribed_items.values():
            all_items.update(items)
        return all_items

    def set_transformer(self, transformer: WebSocketDataTransformer) -> None:
        """데이터 변환기 설정.

        Args:
            transformer: 변환기 인스턴스.
        """
        self._transformer = transformer

    async def __aenter__(self):
        """비동기 컨텍스트 매니저 진입."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """비동기 컨텍스트 매니저 종료."""
        await self.disconnect()
