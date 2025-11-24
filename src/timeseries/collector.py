"""Time-Series 데이터 수집기.

실시간 데이터를 수집하여 TimescaleDB에 저장
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List, Set
from datetime import datetime, timedelta
from decimal import Decimal
import json
import pandas as pd
import numpy as np

from .database import TimeSeriesDB
from .models import (
    MarketData,
    OrderHistory,
    BalanceHistory,
    PerformanceMetrics,
    Position
)
from ..websocket_proxy.client import MarketDataClient


logger = logging.getLogger(__name__)


class DataCollector:
    """실시간 데이터 수집기."""

    def __init__(
        self,
        db: TimeSeriesDB,
        ws_client: Optional[MarketDataClient] = None
    ):
        self.db = db
        self.ws_client = ws_client or MarketDataClient()

        # 수집 설정
        self.collecting_symbols: Set[str] = set()
        self.collection_interval = 1.0  # 초
        self.batch_size = 100  # 배치 크기
        self.buffer_timeout = 5.0  # 버퍼 타임아웃 (초)

        # 데이터 버퍼
        self.market_data_buffer: List[Dict[str, Any]] = []
        self.order_buffer: List[Dict[str, Any]] = []
        self.balance_buffer: List[Dict[str, Any]] = []
        self.metrics_buffer: List[Dict[str, Any]] = []

        # 태스크 관리
        self.collection_tasks: Dict[str, asyncio.Task] = {}
        self.flush_task: Optional[asyncio.Task] = None

        # 통계
        self.stats = {
            "market_data_collected": 0,
            "orders_collected": 0,
            "balances_collected": 0,
            "metrics_collected": 0,
            "db_writes": 0,
            "errors": 0,
        }

    async def start(self) -> None:
        """데이터 수집 시작."""
        # 데이터베이스 연결
        await self.db.connect()

        # WebSocket 클라이언트 연결
        if self.ws_client:
            await self.ws_client.connect()

            # 마켓 데이터 핸들러 등록
            self.ws_client.add_handler("*", self._handle_market_data)

        # 버퍼 플러시 태스크 시작
        self.flush_task = asyncio.create_task(self._flush_loop())

        logger.info("DataCollector started")

    async def stop(self) -> None:
        """데이터 수집 중지."""
        # 모든 수집 중지
        for symbol in list(self.collecting_symbols):
            await self.stop_collecting(symbol)

        # 버퍼 플러시 태스크 중지
        if self.flush_task:
            self.flush_task.cancel()
            try:
                await self.flush_task
            except asyncio.CancelledError:
                pass

        # 남은 버퍼 플러시
        await self._flush_all_buffers()

        # WebSocket 클라이언트 연결 해제
        if self.ws_client:
            await self.ws_client.disconnect()

        # 데이터베이스 연결 해제
        await self.db.disconnect()

        logger.info("DataCollector stopped")

    async def start_collecting(
        self,
        symbol: str,
        collect_orderbook: bool = False
    ) -> None:
        """특정 종목 데이터 수집 시작."""
        if symbol in self.collecting_symbols:
            logger.warning(f"Already collecting {symbol}")
            return

        self.collecting_symbols.add(symbol)

        # WebSocket 구독
        if self.ws_client:
            channels = [f"market:{symbol}"]
            if collect_orderbook:
                channels.append(f"orderbook:{symbol}")
            await self.ws_client.subscribe(channels)

        # HTTP 폴링 시작 (WebSocket 백업)
        if self.ws_client.http_url:
            await self.ws_client.start_polling(symbol, self.collection_interval)

        logger.info(f"Started collecting data for {symbol}")

    async def stop_collecting(self, symbol: str) -> None:
        """특정 종목 데이터 수집 중지."""
        if symbol not in self.collecting_symbols:
            return

        self.collecting_symbols.discard(symbol)

        # WebSocket 구독 해제
        if self.ws_client:
            await self.ws_client.unsubscribe([f"market:{symbol}"])
            await self.ws_client.stop_polling(symbol)

        logger.info(f"Stopped collecting data for {symbol}")

    async def _handle_market_data(self, message: Dict[str, Any]) -> None:
        """마켓 데이터 메시지 처리."""
        try:
            msg_type = message.get("type")
            channel = message.get("channel", "")
            data = message.get("data", {})

            if msg_type in ["market_data", "incremental"] and channel.startswith("market:"):
                # 마켓 데이터 버퍼에 추가
                market_data = {
                    "time": datetime.fromisoformat(
                        data.get("timestamp", datetime.now().isoformat())
                    ),
                    "symbol": data.get("symbol"),
                    "price": data.get("price"),
                    "volume": data.get("volume"),
                    "bid_price": data.get("bid_price"),
                    "ask_price": data.get("ask_price"),
                    "bid_volume": data.get("bid_volume"),
                    "ask_volume": data.get("ask_volume"),
                    "high": data.get("high"),
                    "low": data.get("low"),
                    "open": data.get("open"),
                    "close": data.get("close"),
                    "vwap": data.get("vwap"),
                }

                self.market_data_buffer.append(market_data)
                self.stats["market_data_collected"] += 1

                # 버퍼 크기 확인
                if len(self.market_data_buffer) >= self.batch_size:
                    await self._flush_market_data()

        except Exception as e:
            logger.error(f"Error handling market data: {e}")
            self.stats["errors"] += 1

    async def collect_order(self, order: OrderHistory) -> None:
        """주문 데이터 수집."""
        self.order_buffer.append(order.to_dict())
        self.stats["orders_collected"] += 1

        if len(self.order_buffer) >= self.batch_size:
            await self._flush_orders()

    async def collect_balance(self, balance: BalanceHistory) -> None:
        """잔고 데이터 수집."""
        self.balance_buffer.append(balance.to_dict())
        self.stats["balances_collected"] += 1

        if len(self.balance_buffer) >= self.batch_size:
            await self._flush_balances()

    async def collect_metric(
        self,
        strategy: str,
        metric_name: str,
        metric_value: float,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """성능 지표 수집."""
        metric = PerformanceMetrics(
            time=datetime.now(),
            strategy=strategy,
            metric_name=metric_name,
            metric_value=metric_value,
            metadata=metadata
        )
        self.metrics_buffer.append(metric.to_dict())
        self.stats["metrics_collected"] += 1

        if len(self.metrics_buffer) >= self.batch_size:
            await self._flush_metrics()

    async def _flush_loop(self) -> None:
        """주기적 버퍼 플러시."""
        while True:
            try:
                await asyncio.sleep(self.buffer_timeout)
                await self._flush_all_buffers()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error in flush loop: {e}")
                self.stats["errors"] += 1

    async def _flush_all_buffers(self) -> None:
        """모든 버퍼 플러시."""
        await self._flush_market_data()
        await self._flush_orders()
        await self._flush_balances()
        await self._flush_metrics()

    async def _flush_market_data(self) -> None:
        """마켓 데이터 버퍼 플러시."""
        if not self.market_data_buffer:
            return

        try:
            data = self.market_data_buffer.copy()
            self.market_data_buffer.clear()

            await self.db.insert_market_data(data)
            self.stats["db_writes"] += 1
            logger.debug(f"Flushed {len(data)} market data records")

        except Exception as e:
            logger.error(f"Error flushing market data: {e}")
            self.stats["errors"] += 1
            # 실패한 데이터 다시 버퍼에 추가
            self.market_data_buffer.extend(data)

    async def _flush_orders(self) -> None:
        """주문 버퍼 플러시."""
        if not self.order_buffer:
            return

        try:
            for order in self.order_buffer:
                await self.db.insert_order(order)
            self.stats["db_writes"] += 1
            logger.debug(f"Flushed {len(self.order_buffer)} orders")
            self.order_buffer.clear()

        except Exception as e:
            logger.error(f"Error flushing orders: {e}")
            self.stats["errors"] += 1

    async def _flush_balances(self) -> None:
        """잔고 버퍼 플러시."""
        if not self.balance_buffer:
            return

        try:
            for balance in self.balance_buffer:
                await self.db.insert_balance(balance)
            self.stats["db_writes"] += 1
            logger.debug(f"Flushed {len(self.balance_buffer)} balances")
            self.balance_buffer.clear()

        except Exception as e:
            logger.error(f"Error flushing balances: {e}")
            self.stats["errors"] += 1

    async def _flush_metrics(self) -> None:
        """성능 지표 버퍼 플러시."""
        if not self.metrics_buffer:
            return

        try:
            async with self.db.pool.acquire() as conn:
                await conn.executemany(
                    """
                    INSERT INTO performance_metrics (
                        time, strategy, metric_name, metric_value, metadata
                    ) VALUES ($1, $2, $3, $4, $5)
                    """,
                    [
                        (
                            m["time"], m["strategy"], m["metric_name"],
                            m["metric_value"], m.get("metadata")
                        )
                        for m in self.metrics_buffer
                    ]
                )
            self.stats["db_writes"] += 1
            logger.debug(f"Flushed {len(self.metrics_buffer)} metrics")
            self.metrics_buffer.clear()

        except Exception as e:
            logger.error(f"Error flushing metrics: {e}")
            self.stats["errors"] += 1

    def get_stats(self) -> Dict[str, Any]:
        """통계 정보 반환."""
        return {
            **self.stats,
            "collecting_symbols": list(self.collecting_symbols),
            "buffer_sizes": {
                "market_data": len(self.market_data_buffer),
                "orders": len(self.order_buffer),
                "balances": len(self.balance_buffer),
                "metrics": len(self.metrics_buffer),
            }
        }


class BacktestDataCollector(DataCollector):
    """백테스트용 데이터 수집기."""

    def __init__(self, db: TimeSeriesDB):
        super().__init__(db, ws_client=None)
        self.historical_data: Dict[str, pd.DataFrame] = {}
        self.data_source = "historical"  # "historical" or "simulated"

    async def load_historical_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1m"
    ) -> pd.DataFrame:
        """과거 데이터 로드."""
        df = await self.db.get_market_data(
            symbol=symbol,
            start_time=start_date,
            end_time=end_date,
            interval=interval
        )

        if df.empty:
            logger.warning(f"No historical data for {symbol}")
        else:
            self.historical_data[symbol] = df
            logger.info(f"Loaded {len(df)} records for {symbol}")

        return df

    async def simulate_market_data(
        self,
        symbol: str,
        base_price: float,
        volatility: float,
        duration_hours: int = 24
    ) -> pd.DataFrame:
        """시뮬레이션 데이터 생성."""
        import numpy as np
        import pandas as pd

        # 시간 인덱스 생성
        times = pd.date_range(
            start=datetime.now() - timedelta(hours=duration_hours),
            end=datetime.now(),
            freq="1min"
        )

        # 랜덤 워크로 가격 시뮬레이션
        returns = np.random.normal(0, volatility / 100, len(times))
        prices = base_price * np.exp(np.cumsum(returns))

        # 거래량 시뮬레이션
        volumes = np.random.poisson(1000000, len(times))

        df = pd.DataFrame({
            "time": times,
            "symbol": symbol,
            "open": prices * (1 + np.random.uniform(-0.001, 0.001, len(times))),
            "high": prices * (1 + np.random.uniform(0, 0.002, len(times))),
            "low": prices * (1 - np.random.uniform(0, 0.002, len(times))),
            "close": prices,
            "volume": volumes
        })

        df.set_index("time", inplace=True)
        self.historical_data[symbol] = df

        # DB에 저장
        data = []
        for idx, row in df.iterrows():
            data.append({
                "time": idx,
                "symbol": symbol,
                "price": row["close"],
                "volume": row["volume"],
                "high": row["high"],
                "low": row["low"],
                "open": row["open"],
                "close": row["close"]
            })

        await self.db.insert_market_data(data)
        logger.info(f"Generated {len(df)} simulated records for {symbol}")

        return df