"""WebSocket Client 어댑터.

WebSocket Proxy Server와 통신하는 클라이언트
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, List, Callable, Set
from datetime import datetime
from enum import Enum
import websockets
from websockets.client import WebSocketClientProtocol
import aiohttp


logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """연결 상태."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class WebSocketClient:
    """WebSocket 클라이언트 어댑터."""

    def __init__(
        self,
        url: str = "ws://localhost:8765",
        http_url: str = "http://localhost:8766",
        auto_reconnect: bool = True,
        heartbeat_interval: float = 30.0
    ):
        self.url = url
        self.http_url = http_url
        self.auto_reconnect = auto_reconnect
        self.heartbeat_interval = heartbeat_interval

        # 연결 관리
        self.websocket: Optional[WebSocketClientProtocol] = None
        self.state = ConnectionState.DISCONNECTED
        self.reconnect_delay = 1.0
        self.max_reconnect_delay = 60.0

        # 구독 관리
        self.subscribed_channels: Set[str] = set()
        self.channel_handlers: Dict[str, List[Callable]] = {}

        # 태스크 관리
        self.receive_task: Optional[asyncio.Task] = None
        self.heartbeat_task: Optional[asyncio.Task] = None

        # 콜백
        self.on_connect: Optional[Callable] = None
        self.on_disconnect: Optional[Callable] = None
        self.on_error: Optional[Callable] = None

        # 통계
        self.stats = {
            "messages_received": 0,
            "connection_attempts": 0,
            "last_message_time": None,
            "uptime": 0,
        }

        # HTTP 세션
        self.http_session: Optional[aiohttp.ClientSession] = None

    async def connect(self) -> bool:
        """서버 연결."""
        if self.state in [ConnectionState.CONNECTED, ConnectionState.CONNECTING]:
            logger.warning(f"Already {self.state.value}")
            return False

        self.state = ConnectionState.CONNECTING
        self.stats["connection_attempts"] += 1

        try:
            # WebSocket 연결
            self.websocket = await websockets.connect(self.url)
            self.state = ConnectionState.CONNECTED
            self.reconnect_delay = 1.0  # 재연결 지연 초기화

            # HTTP 세션 생성
            if not self.http_session:
                self.http_session = aiohttp.ClientSession()

            # 수신 및 하트비트 태스크 시작
            self.receive_task = asyncio.create_task(self._receive_loop())
            self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            # 기존 구독 복원
            if self.subscribed_channels:
                await self._resubscribe()

            # 연결 콜백
            if self.on_connect:
                await self.on_connect()

            logger.info(f"Connected to {self.url}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            self.state = ConnectionState.ERROR

            if self.auto_reconnect:
                asyncio.create_task(self._auto_reconnect())

            return False

    async def disconnect(self) -> None:
        """서버 연결 해제."""
        self.auto_reconnect = False  # 자동 재연결 비활성화
        await self._cleanup()

    async def _cleanup(self) -> None:
        """연결 정리."""
        self.state = ConnectionState.DISCONNECTED

        # 태스크 취소
        for task in [self.receive_task, self.heartbeat_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # WebSocket 연결 종료
        if self.websocket:
            await self.websocket.close()
            self.websocket = None

        # HTTP 세션 종료
        if self.http_session:
            await self.http_session.close()
            self.http_session = None

        # 연결 해제 콜백
        if self.on_disconnect:
            await self.on_disconnect()

        logger.info("Disconnected from server")

    async def _auto_reconnect(self) -> None:
        """자동 재연결."""
        while self.auto_reconnect:
            self.state = ConnectionState.RECONNECTING
            logger.info(f"Reconnecting in {self.reconnect_delay} seconds...")

            await asyncio.sleep(self.reconnect_delay)

            if await self.connect():
                break

            # 재연결 지연 증가 (지수 백오프)
            self.reconnect_delay = min(
                self.reconnect_delay * 2,
                self.max_reconnect_delay
            )

    async def _receive_loop(self) -> None:
        """메시지 수신 루프."""
        try:
            async for message in self.websocket:
                self.stats["messages_received"] += 1
                self.stats["last_message_time"] = datetime.now()

                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON: {message}")
                except Exception as e:
                    logger.error(f"Error handling message: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.warning("Connection closed by server")
        except Exception as e:
            logger.error(f"Receive loop error: {e}")
            if self.on_error:
                await self.on_error(e)
        finally:
            if self.auto_reconnect:
                await self._auto_reconnect()

    async def _heartbeat_loop(self) -> None:
        """하트비트 전송 루프."""
        while self.state == ConnectionState.CONNECTED:
            try:
                await asyncio.sleep(self.heartbeat_interval)

                if self.websocket:
                    await self.send({
                        "type": "heartbeat",
                        "timestamp": datetime.now().isoformat()
                    })

            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                break

    async def _handle_message(self, data: Dict[str, Any]) -> None:
        """메시지 처리."""
        msg_type = data.get("type")
        channel = data.get("channel")

        # 채널 핸들러 실행
        if channel in self.channel_handlers:
            for handler in self.channel_handlers[channel]:
                try:
                    await handler(data)
                except Exception as e:
                    logger.error(f"Handler error for {channel}: {e}")

        # 전역 핸들러 (모든 메시지)
        if "*" in self.channel_handlers:
            for handler in self.channel_handlers["*"]:
                try:
                    await handler(data)
                except Exception as e:
                    logger.error(f"Global handler error: {e}")

    async def subscribe(
        self,
        channels: List[str],
        handler: Optional[Callable] = None
    ) -> bool:
        """채널 구독."""
        if self.state != ConnectionState.CONNECTED:
            logger.error("Not connected")
            return False

        # 핸들러 등록
        for channel in channels:
            if channel not in self.channel_handlers:
                self.channel_handlers[channel] = []
            if handler:
                self.channel_handlers[channel].append(handler)
            self.subscribed_channels.add(channel)

        # 구독 메시지 전송
        return await self.send({
            "type": "subscribe",
            "channels": channels
        })

    async def unsubscribe(self, channels: List[str]) -> bool:
        """채널 구독 해제."""
        if self.state != ConnectionState.CONNECTED:
            logger.error("Not connected")
            return False

        # 구독 목록에서 제거
        for channel in channels:
            self.subscribed_channels.discard(channel)
            if channel in self.channel_handlers:
                del self.channel_handlers[channel]

        # 구독 해제 메시지 전송
        return await self.send({
            "type": "unsubscribe",
            "channels": channels
        })

    async def _resubscribe(self) -> None:
        """재연결 시 구독 복원."""
        if self.subscribed_channels:
            await self.send({
                "type": "subscribe",
                "channels": list(self.subscribed_channels)
            })
            logger.info(f"Resubscribed to {len(self.subscribed_channels)} channels")

    async def send(self, data: Dict[str, Any]) -> bool:
        """메시지 전송."""
        if self.state != ConnectionState.CONNECTED or not self.websocket:
            logger.error("Not connected")
            return False

        try:
            await self.websocket.send(json.dumps(data))
            return True
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False

    def add_handler(self, channel: str, handler: Callable) -> None:
        """채널 핸들러 추가."""
        if channel not in self.channel_handlers:
            self.channel_handlers[channel] = []
        self.channel_handlers[channel].append(handler)

    def remove_handler(self, channel: str, handler: Callable) -> None:
        """채널 핸들러 제거."""
        if channel in self.channel_handlers:
            self.channel_handlers[channel].remove(handler)
            if not self.channel_handlers[channel]:
                del self.channel_handlers[channel]

    # HTTP API 메서드
    async def start_polling(self, symbol: str, interval: float = 1.0) -> bool:
        """HTTP API: 폴링 시작."""
        if not self.http_session:
            logger.error("HTTP session not initialized")
            return False

        try:
            async with self.http_session.post(
                f"{self.http_url}/polling/start",
                params={"symbol": symbol, "interval": interval}
            ) as response:
                if response.status == 200:
                    logger.info(f"Started polling {symbol}")
                    return True
                else:
                    logger.error(f"Failed to start polling: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"HTTP request error: {e}")
            return False

    async def stop_polling(self, symbol: str) -> bool:
        """HTTP API: 폴링 중지."""
        if not self.http_session:
            logger.error("HTTP session not initialized")
            return False

        try:
            async with self.http_session.post(
                f"{self.http_url}/polling/stop",
                params={"symbol": symbol}
            ) as response:
                if response.status == 200:
                    logger.info(f"Stopped polling {symbol}")
                    return True
                else:
                    logger.error(f"Failed to stop polling: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"HTTP request error: {e}")
            return False

    async def get_server_status(self) -> Optional[Dict[str, Any]]:
        """HTTP API: 서버 상태 조회."""
        if not self.http_session:
            logger.error("HTTP session not initialized")
            return None

        try:
            async with self.http_session.get(
                f"{self.http_url}/status"
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"Failed to get status: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"HTTP request error: {e}")
            return None

    def get_stats(self) -> Dict[str, Any]:
        """클라이언트 통계."""
        return {
            **self.stats,
            "state": self.state.value,
            "subscribed_channels": list(self.subscribed_channels),
            "active_handlers": len(self.channel_handlers)
        }


class MarketDataClient(WebSocketClient):
    """시장 데이터 전문 클라이언트."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.market_data_cache: Dict[str, Any] = {}

    async def subscribe_market_data(
        self,
        symbols: List[str],
        handler: Optional[Callable] = None
    ) -> bool:
        """시장 데이터 구독."""
        channels = [f"market:{symbol}" for symbol in symbols]

        # 캐시 업데이트 핸들러 추가
        async def cache_handler(data):
            symbol = data.get("data", {}).get("symbol")
            if symbol:
                self.market_data_cache[symbol] = data.get("data")
            if handler:
                await handler(data)

        return await self.subscribe(channels, cache_handler)

    def get_cached_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """캐시된 시장 데이터 조회."""
        return self.market_data_cache.get(symbol)