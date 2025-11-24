"""WebSocket Proxy Server 메인 구현.

중앙화된 API 폴링 서비스와 WebSocket 브로드캐스트 통합
"""

import asyncio
import json
import logging
from typing import Dict, Set, Optional, Any, List
from datetime import datetime, timedelta
import websockets
from websockets.server import WebSocketServerProtocol
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from .rate_limiter import RateLimiter, RateLimitConfig
from .data_broadcaster import DataBroadcaster, MessageType
# from ..api.kiwoom_api import KiwoomAPI  # TODO: API 통합 시 활성화
# from ..api.kis_api import KISApi  # TODO: API 통합 시 활성화
# from ..config import Config  # TODO: Config 통합 시 활성화


logger = logging.getLogger(__name__)


class APIPoller:
    """API 폴링 관리자."""

    def __init__(
        self,
        api_client: Any,
        rate_limiter: RateLimiter,
        broadcaster: DataBroadcaster
    ):
        self.api_client = api_client
        self.rate_limiter = rate_limiter
        self.broadcaster = broadcaster
        self.polling_tasks: Dict[str, asyncio.Task] = {}
        self.polling_intervals: Dict[str, float] = {}
        self.last_data: Dict[str, Any] = {}

    async def start_polling(
        self,
        symbol: str,
        interval: float = 1.0,
        api_key: str = "default"
    ) -> None:
        """특정 종목 폴링 시작."""
        if symbol in self.polling_tasks:
            logger.warning(f"Already polling {symbol}")
            return

        self.polling_intervals[symbol] = interval
        task = asyncio.create_task(
            self._poll_loop(symbol, interval, api_key)
        )
        self.polling_tasks[symbol] = task
        logger.info(f"Started polling {symbol} every {interval}s")

    async def stop_polling(self, symbol: str) -> None:
        """특정 종목 폴링 중지."""
        if symbol in self.polling_tasks:
            self.polling_tasks[symbol].cancel()
            try:
                await self.polling_tasks[symbol]
            except asyncio.CancelledError:
                pass
            del self.polling_tasks[symbol]
            del self.polling_intervals[symbol]
            logger.info(f"Stopped polling {symbol}")

    async def _poll_loop(
        self,
        symbol: str,
        interval: float,
        api_key: str
    ) -> None:
        """폴링 루프."""
        while True:
            try:
                # Rate Limit 확인 및 대기
                if await self.rate_limiter.wait_and_acquire(api_key):
                    # API 호출
                    data = await self._fetch_data(symbol)

                    if data:
                        # 데이터 변경 확인
                        if self._is_data_changed(symbol, data):
                            self.last_data[symbol] = data

                            # 브로드캐스트
                            await self.broadcaster.publish(
                                channel=f"market:{symbol}",
                                data=data,
                                message_type=MessageType.MARKET_DATA
                            )

                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error polling {symbol}: {e}")
                await asyncio.sleep(interval * 2)  # 에러 시 대기 시간 증가

    async def _fetch_data(self, symbol: str) -> Optional[Dict]:
        """실제 API 데이터 조회."""
        try:
            # 여기서는 예시로 간단한 데이터 반환
            # 실제로는 API 클라이언트 호출
            return {
                "symbol": symbol,
                "price": 50000,
                "volume": 1000000,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Failed to fetch data for {symbol}: {e}")
            return None

    def _is_data_changed(self, symbol: str, new_data: Dict) -> bool:
        """데이터 변경 여부 확인."""
        if symbol not in self.last_data:
            return True

        old_data = self.last_data[symbol]
        # 가격이나 거래량 변경 확인
        return (
            old_data.get("price") != new_data.get("price") or
            old_data.get("volume") != new_data.get("volume")
        )

    def get_status(self) -> Dict[str, Any]:
        """폴링 상태 반환."""
        return {
            "active_symbols": list(self.polling_tasks.keys()),
            "intervals": self.polling_intervals.copy(),
            "last_update": {
                symbol: data.get("timestamp")
                for symbol, data in self.last_data.items()
            }
        }


class WebSocketProxyServer:
    """WebSocket Proxy Server."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8765,
        http_port: int = 8766
    ):
        self.host = host
        self.port = port
        self.http_port = http_port

        # 컴포넌트 초기화 - 기본값을 키움증권 기준으로 설정
        self.rate_limiter = RateLimiter(RateLimitConfig(
            requests_per_second=1.0,  # 키움증권 기준: 초당 1회
            requests_per_minute=60,    # 분당 60회 (초당 1회 기준)
            requests_per_hour=3600     # 시간당 3600회 (초당 1회 기준)
        ))

        self.broadcaster = DataBroadcaster()
        self.api_poller = APIPoller(
            api_client=None,  # 실제 API 클라이언트
            rate_limiter=self.rate_limiter,
            broadcaster=self.broadcaster
        )

        # WebSocket 연결 관리
        self.connected_clients: Set[WebSocketServerProtocol] = set()

        # FastAPI 앱 설정
        self.app = FastAPI(title="WebSocket Proxy Server")
        self._setup_routes()

        # 서버 태스크
        self.ws_server = None
        self.http_server = None

        # Rate Limit 설정 (API별)
        self._setup_rate_limits()

    def _setup_rate_limits(self) -> None:
        """API별 Rate Limit 설정."""
        # 키움증권 REST API - 매우 제한적
        self.rate_limiter.register_api(
            api_key="kiwoom",
            requests_per_second=1.0,   # 초당 1회 제한
            burst_size=2               # 최소 버스트만 허용
        )

        # 한국투자증권(KIS) API - 상대적으로 여유있음
        self.rate_limiter.register_api(
            api_key="kis",
            requests_per_second=20.0,  # 초당 20회
            burst_size=50              # 버스트 50개 허용
        )

        logger.info("Rate limits configured for APIs")

    def _setup_routes(self) -> None:
        """HTTP API 라우트 설정."""
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @self.app.get("/status")
        async def get_status():
            """서버 상태 확인."""
            return {
                "status": "running",
                "connections": len(self.connected_clients),
                "broadcaster": self.broadcaster.get_stats(),
                "rate_limiter": self.rate_limiter.get_remaining_capacity(),
                "poller": self.api_poller.get_status(),
                "timestamp": datetime.now().isoformat()
            }

        @self.app.post("/polling/start")
        async def start_polling(symbol: str, interval: float = 1.0):
            """폴링 시작."""
            await self.api_poller.start_polling(
                symbol=symbol,
                interval=interval,
                api_key="kiwoom"  # 기본 API
            )
            return {"message": f"Started polling {symbol}"}

        @self.app.post("/polling/stop")
        async def stop_polling(symbol: str):
            """폴링 중지."""
            await self.api_poller.stop_polling(symbol)
            return {"message": f"Stopped polling {symbol}"}

        @self.app.post("/broadcast")
        async def broadcast_message(
            channel: str,
            data: Dict[str, Any]
        ):
            """수동 브로드캐스트."""
            await self.broadcaster.publish(
                channel=channel,
                data=data,
                message_type=MessageType.MARKET_DATA
            )
            return {"message": "Broadcasted"}

        @self.app.get("/rate-limit/stats")
        async def get_rate_limit_stats(api_key: Optional[str] = None):
            """Rate Limit 통계."""
            return self.rate_limiter.get_stats(api_key)

        @self.app.post("/rate-limit/reset")
        async def reset_rate_limit(api_key: Optional[str] = None):
            """Rate Limit 초기화."""
            await self.rate_limiter.reset_limits(api_key)
            return {"message": f"Reset rate limits for {api_key or 'all'}"}

    async def handle_websocket(
        self,
        websocket: WebSocketServerProtocol
    ) -> None:
        """WebSocket 연결 처리."""
        self.connected_clients.add(websocket)
        client_id = id(websocket)
        logger.info(f"Client {client_id} connected from {websocket.remote_address}")

        try:
            # 환영 메시지
            await websocket.send(json.dumps({
                "type": "connected",
                "client_id": client_id,
                "timestamp": datetime.now().isoformat()
            }))

            # 메시지 처리 루프
            async for message in websocket:
                await self.broadcaster.handle_client_message(
                    websocket,
                    message
                )

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Client {client_id} disconnected")
        except Exception as e:
            logger.error(f"Error handling client {client_id}: {e}")
        finally:
            # 연결 정리
            self.connected_clients.discard(websocket)
            await self.broadcaster.channel_manager.remove_client(websocket)

    async def start(self) -> None:
        """서버 시작."""
        # 브로드캐스터 시작
        await self.broadcaster.start()

        # WebSocket 서버 시작
        self.ws_server = await websockets.serve(
            self.handle_websocket,
            self.host,
            self.port
        )
        logger.info(f"WebSocket server started on ws://{self.host}:{self.port}")

        # HTTP 서버 시작 (별도 태스크)
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.http_port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        self.http_server = asyncio.create_task(server.serve())
        logger.info(f"HTTP API started on http://{self.host}:{self.http_port}")

        # 기본 폴링 시작 (예시)
        await self.api_poller.start_polling("005930", interval=1.0)  # 삼성전자
        await self.api_poller.start_polling("000660", interval=2.0)  # SK하이닉스

    async def stop(self) -> None:
        """서버 중지."""
        # 폴링 중지
        for symbol in list(self.api_poller.polling_tasks.keys()):
            await self.api_poller.stop_polling(symbol)

        # 브로드캐스터 중지
        await self.broadcaster.stop()

        # WebSocket 서버 중지
        if self.ws_server:
            self.ws_server.close()
            await self.ws_server.wait_closed()

        # HTTP 서버 중지
        if self.http_server:
            self.http_server.cancel()
            try:
                await self.http_server
            except asyncio.CancelledError:
                pass

        logger.info("WebSocket Proxy Server stopped")


async def main():
    """메인 함수."""
    server = WebSocketProxyServer()

    try:
        await server.start()
        # 서버 유지
        await asyncio.Future()  # 영원히 대기
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await server.stop()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    asyncio.run(main())