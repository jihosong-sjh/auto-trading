"""WebSocket 데이터 브로드캐스터.

실시간 데이터를 여러 클라이언트에게 효율적으로 전송
"""

import json
import asyncio
import logging
from typing import Dict, Set, Any, Optional, List
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
import websockets
from websockets.server import WebSocketServerProtocol


logger = logging.getLogger(__name__)


class MessageType(Enum):
    """메시지 타입."""

    MARKET_DATA = "market_data"      # 시장 데이터
    ORDER_UPDATE = "order_update"    # 주문 업데이트
    BALANCE = "balance"              # 잔고 정보
    ERROR = "error"                  # 에러
    HEARTBEAT = "heartbeat"          # 하트비트
    SUBSCRIBE = "subscribe"          # 구독
    UNSUBSCRIBE = "unsubscribe"      # 구독 해제
    SNAPSHOT = "snapshot"            # 스냅샷
    INCREMENTAL = "incremental"      # 증분 업데이트


@dataclass
class BroadcastMessage:
    """브로드캐스트 메시지."""

    type: MessageType
    channel: str
    data: Any
    timestamp: datetime = None
    sequence: int = 0

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def to_json(self) -> str:
        """JSON 문자열로 변환."""
        return json.dumps({
            "type": self.type.value,
            "channel": self.channel,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "sequence": self.sequence
        })


class ChannelManager:
    """채널 구독 관리."""

    def __init__(self):
        self.subscriptions: Dict[str, Set[WebSocketServerProtocol]] = {}
        self.client_channels: Dict[WebSocketServerProtocol, Set[str]] = {}
        self.lock = asyncio.Lock()

    async def subscribe(
        self,
        client: WebSocketServerProtocol,
        channels: List[str]
    ) -> None:
        """채널 구독."""
        async with self.lock:
            # 클라이언트별 채널 목록 초기화
            if client not in self.client_channels:
                self.client_channels[client] = set()

            for channel in channels:
                # 채널별 구독자 목록에 추가
                if channel not in self.subscriptions:
                    self.subscriptions[channel] = set()
                self.subscriptions[channel].add(client)

                # 클라이언트의 구독 채널 목록에 추가
                self.client_channels[client].add(channel)

                logger.debug(f"Client {id(client)} subscribed to {channel}")

    async def unsubscribe(
        self,
        client: WebSocketServerProtocol,
        channels: Optional[List[str]] = None
    ) -> None:
        """채널 구독 해제."""
        async with self.lock:
            if client not in self.client_channels:
                return

            # 구독 해제할 채널 결정
            channels_to_remove = (
                set(channels) if channels
                else self.client_channels[client].copy()
            )

            for channel in channels_to_remove:
                # 채널별 구독자 목록에서 제거
                if channel in self.subscriptions:
                    self.subscriptions[channel].discard(client)
                    if not self.subscriptions[channel]:
                        del self.subscriptions[channel]

                # 클라이언트의 구독 채널 목록에서 제거
                self.client_channels[client].discard(channel)

                logger.debug(f"Client {id(client)} unsubscribed from {channel}")

            # 클라이언트가 모든 채널에서 구독 해제된 경우
            if not self.client_channels[client]:
                del self.client_channels[client]

    async def remove_client(self, client: WebSocketServerProtocol) -> None:
        """클라이언트 완전 제거."""
        await self.unsubscribe(client)

    def get_subscribers(self, channel: str) -> Set[WebSocketServerProtocol]:
        """채널 구독자 목록 반환."""
        return self.subscriptions.get(channel, set()).copy()

    def get_client_channels(
        self,
        client: WebSocketServerProtocol
    ) -> Set[str]:
        """클라이언트가 구독한 채널 목록 반환."""
        return self.client_channels.get(client, set()).copy()


class DataBroadcaster:
    """WebSocket 데이터 브로드캐스터."""

    def __init__(self):
        self.channel_manager = ChannelManager()
        self.sequence_counter = 0
        self.message_queue: asyncio.Queue = asyncio.Queue()
        self.broadcast_task: Optional[asyncio.Task] = None
        self.stats = {
            "messages_sent": 0,
            "messages_failed": 0,
            "active_connections": 0,
            "total_channels": 0,
        }

    async def start(self) -> None:
        """브로드캐스터 시작."""
        if self.broadcast_task is None:
            self.broadcast_task = asyncio.create_task(self._broadcast_loop())
            logger.info("DataBroadcaster started")

    async def stop(self) -> None:
        """브로드캐스터 중지."""
        if self.broadcast_task:
            self.broadcast_task.cancel()
            try:
                await self.broadcast_task
            except asyncio.CancelledError:
                pass
            self.broadcast_task = None
            logger.info("DataBroadcaster stopped")

    async def _broadcast_loop(self) -> None:
        """브로드캐스트 루프."""
        while True:
            try:
                # 메시지 대기
                message = await self.message_queue.get()

                # 해당 채널 구독자에게 전송
                subscribers = self.channel_manager.get_subscribers(
                    message.channel
                )

                if subscribers:
                    # 메시지 직렬화 (한 번만 수행)
                    json_message = message.to_json()

                    # 병렬로 모든 구독자에게 전송
                    tasks = [
                        self._send_to_client(client, json_message)
                        for client in subscribers
                    ]
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    # 실패한 연결 처리
                    for client, result in zip(subscribers, results):
                        if isinstance(result, Exception):
                            logger.warning(
                                f"Failed to send to client {id(client)}: {result}"
                            )
                            await self.channel_manager.remove_client(client)
                            self.stats["messages_failed"] += 1
                        else:
                            self.stats["messages_sent"] += 1

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error in broadcast loop: {e}")
                await asyncio.sleep(0.1)

    async def _send_to_client(
        self,
        client: WebSocketServerProtocol,
        message: str
    ) -> None:
        """클라이언트에게 메시지 전송."""
        try:
            await client.send(message)
        except websockets.exceptions.ConnectionClosed:
            raise
        except Exception as e:
            logger.error(f"Error sending message to client: {e}")
            raise

    async def publish(
        self,
        channel: str,
        data: Any,
        message_type: MessageType = MessageType.MARKET_DATA
    ) -> None:
        """채널에 데이터 발행."""
        self.sequence_counter += 1
        message = BroadcastMessage(
            type=message_type,
            channel=channel,
            data=data,
            sequence=self.sequence_counter
        )
        await self.message_queue.put(message)

    async def publish_snapshot(
        self,
        channel: str,
        data: Any,
        client: Optional[WebSocketServerProtocol] = None
    ) -> None:
        """스냅샷 데이터 전송."""
        message = BroadcastMessage(
            type=MessageType.SNAPSHOT,
            channel=channel,
            data=data,
            sequence=self.sequence_counter
        )

        if client:
            # 특정 클라이언트에게만 전송
            try:
                await client.send(message.to_json())
                self.stats["messages_sent"] += 1
            except Exception as e:
                logger.error(f"Failed to send snapshot: {e}")
                self.stats["messages_failed"] += 1
        else:
            # 채널 구독자 모두에게 전송
            await self.message_queue.put(message)

    async def handle_client_message(
        self,
        client: WebSocketServerProtocol,
        message: str
    ) -> None:
        """클라이언트 메시지 처리."""
        try:
            data = json.loads(message)
            msg_type = MessageType(data.get("type"))

            if msg_type == MessageType.SUBSCRIBE:
                channels = data.get("channels", [])
                await self.channel_manager.subscribe(client, channels)

                # 구독 확인 메시지 전송
                await client.send(json.dumps({
                    "type": "subscribe_ack",
                    "channels": channels,
                    "timestamp": datetime.now().isoformat()
                }))

            elif msg_type == MessageType.UNSUBSCRIBE:
                channels = data.get("channels", [])
                await self.channel_manager.unsubscribe(client, channels)

                # 구독 해제 확인 메시지 전송
                await client.send(json.dumps({
                    "type": "unsubscribe_ack",
                    "channels": channels,
                    "timestamp": datetime.now().isoformat()
                }))

            elif msg_type == MessageType.HEARTBEAT:
                # 하트비트 응답
                await client.send(json.dumps({
                    "type": "heartbeat_ack",
                    "timestamp": datetime.now().isoformat()
                }))

        except json.JSONDecodeError:
            logger.error(f"Invalid JSON from client: {message}")
            await client.send(json.dumps({
                "type": "error",
                "message": "Invalid JSON format",
                "timestamp": datetime.now().isoformat()
            }))
        except Exception as e:
            logger.error(f"Error handling client message: {e}")
            await client.send(json.dumps({
                "type": "error",
                "message": str(e),
                "timestamp": datetime.now().isoformat()
            }))

    def get_stats(self) -> Dict[str, Any]:
        """통계 정보 반환."""
        return {
            **self.stats,
            "active_connections": sum(
                len(clients) for clients in
                self.channel_manager.subscriptions.values()
            ),
            "total_channels": len(self.channel_manager.subscriptions),
            "sequence": self.sequence_counter
        }