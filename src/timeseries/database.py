"""TimescaleDB 데이터베이스 관리.

시계열 데이터 저장 및 조회를 위한 데이터베이스 인터페이스
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
import asyncpg
from asyncpg import Pool, Connection
import pandas as pd


logger = logging.getLogger(__name__)


class TimeSeriesDB:
    """TimescaleDB 인터페이스."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "trading",
        user: str = "postgres",
        password: str = "postgres",
        min_size: int = 10,
        max_size: int = 20
    ):
        self.config = {
            "host": host,
            "port": port,
            "database": database,
            "user": user,
            "password": password,
            "min_size": min_size,
            "max_size": max_size,
        }
        self.pool: Optional[Pool] = None
        self.initialized = False

    async def connect(self) -> None:
        """데이터베이스 연결."""
        if self.pool:
            logger.warning("Already connected to database")
            return

        try:
            self.pool = await asyncpg.create_pool(**self.config)
            logger.info(f"Connected to TimescaleDB at {self.config['host']}:{self.config['port']}")

            # 스키마 초기화
            if not self.initialized:
                await self.initialize_schema()
                self.initialized = True

        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise

    async def disconnect(self) -> None:
        """데이터베이스 연결 해제."""
        if self.pool:
            await self.pool.close()
            self.pool = None
            logger.info("Disconnected from TimescaleDB")

    async def initialize_schema(self) -> None:
        """스키마 초기화."""
        async with self.pool.acquire() as conn:
            # TimescaleDB 확장 활성화
            await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")

            # 시장 데이터 테이블
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS market_data (
                    time TIMESTAMPTZ NOT NULL,
                    symbol VARCHAR(20) NOT NULL,
                    price DECIMAL(20, 4) NOT NULL,
                    volume BIGINT NOT NULL,
                    bid_price DECIMAL(20, 4),
                    ask_price DECIMAL(20, 4),
                    bid_volume BIGINT,
                    ask_volume BIGINT,
                    high DECIMAL(20, 4),
                    low DECIMAL(20, 4),
                    open DECIMAL(20, 4),
                    close DECIMAL(20, 4),
                    vwap DECIMAL(20, 4),  -- Volume Weighted Average Price
                    market_cap BIGINT,
                    PRIMARY KEY (time, symbol)
                );
            """)

            # Hypertable 생성 (없으면)
            try:
                await conn.execute("""
                    SELECT create_hypertable(
                        'market_data',
                        'time',
                        if_not_exists => TRUE,
                        chunk_time_interval => INTERVAL '1 day'
                    );
                """)
            except Exception:
                pass  # 이미 hypertable인 경우

            # 주문 이력 테이블
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS order_history (
                    time TIMESTAMPTZ NOT NULL,
                    order_id VARCHAR(50) NOT NULL,
                    symbol VARCHAR(20) NOT NULL,
                    order_type VARCHAR(20) NOT NULL,  -- BUY, SELL
                    price_type VARCHAR(20) NOT NULL,  -- MARKET, LIMIT
                    quantity INTEGER NOT NULL,
                    price DECIMAL(20, 4),
                    executed_price DECIMAL(20, 4),
                    executed_quantity INTEGER,
                    status VARCHAR(20) NOT NULL,  -- PENDING, FILLED, CANCELLED
                    strategy VARCHAR(50),
                    signal_reason TEXT,
                    commission DECIMAL(10, 4),
                    slippage DECIMAL(10, 4),
                    PRIMARY KEY (time, order_id)
                );
            """)

            # Hypertable 생성
            try:
                await conn.execute("""
                    SELECT create_hypertable(
                        'order_history',
                        'time',
                        if_not_exists => TRUE,
                        chunk_time_interval => INTERVAL '1 week'
                    );
                """)
            except Exception:
                pass

            # 잔고 이력 테이블
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS balance_history (
                    time TIMESTAMPTZ NOT NULL,
                    account_id VARCHAR(50) NOT NULL,
                    cash DECIMAL(20, 4) NOT NULL,
                    total_value DECIMAL(20, 4) NOT NULL,
                    positions JSONB,  -- 포지션 상세 정보
                    daily_pnl DECIMAL(20, 4),
                    total_pnl DECIMAL(20, 4),
                    PRIMARY KEY (time, account_id)
                );
            """)

            # Hypertable 생성
            try:
                await conn.execute("""
                    SELECT create_hypertable(
                        'balance_history',
                        'time',
                        if_not_exists => TRUE,
                        chunk_time_interval => INTERVAL '1 week'
                    );
                """)
            except Exception:
                pass

            # 성능 지표 테이블
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS performance_metrics (
                    time TIMESTAMPTZ NOT NULL,
                    strategy VARCHAR(50) NOT NULL,
                    metric_name VARCHAR(50) NOT NULL,
                    metric_value DECIMAL(20, 8),
                    metadata JSONB,
                    PRIMARY KEY (time, strategy, metric_name)
                );
            """)

            # Hypertable 생성
            try:
                await conn.execute("""
                    SELECT create_hypertable(
                        'performance_metrics',
                        'time',
                        if_not_exists => TRUE,
                        chunk_time_interval => INTERVAL '1 week'
                    );
                """)
            except Exception:
                pass

            # 백테스트 결과 테이블
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS backtest_results (
                    id SERIAL PRIMARY KEY,
                    strategy VARCHAR(50) NOT NULL,
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    initial_capital DECIMAL(20, 4),
                    final_capital DECIMAL(20, 4),
                    total_return DECIMAL(10, 4),
                    sharpe_ratio DECIMAL(10, 4),
                    max_drawdown DECIMAL(10, 4),
                    win_rate DECIMAL(5, 4),
                    total_trades INTEGER,
                    parameters JSONB,
                    detailed_metrics JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)

            # 인덱스 생성
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_market_data_symbol_time
                ON market_data (symbol, time DESC);
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_order_history_symbol_time
                ON order_history (symbol, time DESC);
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_order_history_status
                ON order_history (status);
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_performance_metrics_strategy
                ON performance_metrics (strategy, time DESC);
            """)

            # Continuous Aggregates (실시간 집계 뷰)
            # 1분봉 OHLCV 집계
            await conn.execute("""
                CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_1min
                WITH (timescaledb.continuous) AS
                SELECT
                    time_bucket('1 minute', time) AS bucket,
                    symbol,
                    FIRST(price, time) AS open,
                    MAX(price) AS high,
                    MIN(price) AS low,
                    LAST(price, time) AS close,
                    SUM(volume) AS volume,
                    AVG(price) AS vwap
                FROM market_data
                GROUP BY bucket, symbol
                WITH NO DATA;
            """)

            # Continuous Aggregate 정책 설정 (있으면 skip)
            try:
                await conn.execute("""
                    SELECT add_continuous_aggregate_policy(
                        'ohlcv_1min',
                        start_offset => INTERVAL '1 hour',
                        end_offset => INTERVAL '1 minute',
                        schedule_interval => INTERVAL '1 minute',
                        if_not_exists => TRUE
                    );
                """)
            except Exception:
                pass

            # 데이터 보존 정책 (오래된 데이터 자동 삭제)
            try:
                await conn.execute("""
                    SELECT add_retention_policy(
                        'market_data',
                        INTERVAL '3 months',
                        if_not_exists => TRUE
                    );
                """)
            except Exception:
                pass

            logger.info("Schema initialized successfully")

    # 데이터 쓰기 메서드
    async def insert_market_data(self, data: List[Dict[str, Any]]) -> None:
        """시장 데이터 삽입."""
        async with self.pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO market_data (
                    time, symbol, price, volume, bid_price, ask_price,
                    bid_volume, ask_volume, high, low, open, close, vwap
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                ON CONFLICT (time, symbol) DO UPDATE
                SET
                    price = EXCLUDED.price,
                    volume = EXCLUDED.volume,
                    bid_price = EXCLUDED.bid_price,
                    ask_price = EXCLUDED.ask_price,
                    bid_volume = EXCLUDED.bid_volume,
                    ask_volume = EXCLUDED.ask_volume,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    open = EXCLUDED.open,
                    close = EXCLUDED.close,
                    vwap = EXCLUDED.vwap;
                """,
                [
                    (
                        d["time"], d["symbol"], d["price"], d["volume"],
                        d.get("bid_price"), d.get("ask_price"),
                        d.get("bid_volume"), d.get("ask_volume"),
                        d.get("high"), d.get("low"),
                        d.get("open"), d.get("close"), d.get("vwap")
                    )
                    for d in data
                ]
            )

    async def insert_order(self, order: Dict[str, Any]) -> None:
        """주문 이력 삽입."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO order_history (
                    time, order_id, symbol, order_type, price_type,
                    quantity, price, executed_price, executed_quantity,
                    status, strategy, signal_reason, commission, slippage
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                """,
                order["time"], order["order_id"], order["symbol"],
                order["order_type"], order["price_type"],
                order["quantity"], order.get("price"),
                order.get("executed_price"), order.get("executed_quantity"),
                order["status"], order.get("strategy"),
                order.get("signal_reason"), order.get("commission"),
                order.get("slippage")
            )

    async def insert_balance(self, balance: Dict[str, Any]) -> None:
        """잔고 이력 삽입."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO balance_history (
                    time, account_id, cash, total_value,
                    positions, daily_pnl, total_pnl
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (time, account_id) DO UPDATE
                SET
                    cash = EXCLUDED.cash,
                    total_value = EXCLUDED.total_value,
                    positions = EXCLUDED.positions,
                    daily_pnl = EXCLUDED.daily_pnl,
                    total_pnl = EXCLUDED.total_pnl;
                """,
                balance["time"], balance["account_id"],
                balance["cash"], balance["total_value"],
                balance.get("positions"), balance.get("daily_pnl"),
                balance.get("total_pnl")
            )

    # 데이터 조회 메서드
    async def get_market_data(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
        interval: Optional[str] = None
    ) -> pd.DataFrame:
        """시장 데이터 조회."""
        async with self.pool.acquire() as conn:
            if interval:
                # 집계된 데이터 조회
                query = """
                    SELECT
                        time_bucket($1::interval, time) AS bucket,
                        symbol,
                        FIRST(price, time) AS open,
                        MAX(price) AS high,
                        MIN(price) AS low,
                        LAST(price, time) AS close,
                        SUM(volume) AS volume,
                        AVG(price) AS vwap
                    FROM market_data
                    WHERE symbol = $2 AND time >= $3 AND time <= $4
                    GROUP BY bucket, symbol
                    ORDER BY bucket;
                """
                rows = await conn.fetch(query, interval, symbol, start_time, end_time)
            else:
                # 원본 데이터 조회
                query = """
                    SELECT * FROM market_data
                    WHERE symbol = $1 AND time >= $2 AND time <= $3
                    ORDER BY time;
                """
                rows = await conn.fetch(query, symbol, start_time, end_time)

            # DataFrame으로 변환
            if rows:
                df = pd.DataFrame([dict(row) for row in rows])
                if "bucket" in df.columns:
                    df.rename(columns={"bucket": "time"}, inplace=True)
                df.set_index("time", inplace=True)
                return df
            return pd.DataFrame()

    async def get_latest_price(self, symbol: str) -> Optional[float]:
        """최신 가격 조회."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT price FROM market_data
                WHERE symbol = $1
                ORDER BY time DESC
                LIMIT 1;
                """,
                symbol
            )
            return float(row["price"]) if row else None

    async def get_order_history(
        self,
        symbol: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        strategy: Optional[str] = None
    ) -> pd.DataFrame:
        """주문 이력 조회."""
        async with self.pool.acquire() as conn:
            query = "SELECT * FROM order_history WHERE 1=1"
            params = []
            param_count = 0

            if symbol:
                param_count += 1
                query += f" AND symbol = ${param_count}"
                params.append(symbol)

            if start_time:
                param_count += 1
                query += f" AND time >= ${param_count}"
                params.append(start_time)

            if end_time:
                param_count += 1
                query += f" AND time <= ${param_count}"
                params.append(end_time)

            if strategy:
                param_count += 1
                query += f" AND strategy = ${param_count}"
                params.append(strategy)

            query += " ORDER BY time DESC"

            rows = await conn.fetch(query, *params)
            if rows:
                return pd.DataFrame([dict(row) for row in rows])
            return pd.DataFrame()

    async def get_performance_metrics(
        self,
        strategy: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> pd.DataFrame:
        """성능 지표 조회."""
        async with self.pool.acquire() as conn:
            query = """
                SELECT * FROM performance_metrics
                WHERE strategy = $1
            """
            params = [strategy]

            if start_time:
                query += " AND time >= $2"
                params.append(start_time)

            if end_time:
                query += f" AND time <= ${len(params) + 1}"
                params.append(end_time)

            query += " ORDER BY time"

            rows = await conn.fetch(query, *params)
            if rows:
                df = pd.DataFrame([dict(row) for row in rows])
                df.set_index("time", inplace=True)
                return df
            return pd.DataFrame()

    async def save_backtest_result(self, result: Dict[str, Any]) -> int:
        """백테스트 결과 저장."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO backtest_results (
                    strategy, start_date, end_date,
                    initial_capital, final_capital,
                    total_return, sharpe_ratio, max_drawdown,
                    win_rate, total_trades,
                    parameters, detailed_metrics
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                RETURNING id;
                """,
                result["strategy"], result["start_date"], result["end_date"],
                result.get("initial_capital"), result.get("final_capital"),
                result.get("total_return"), result.get("sharpe_ratio"),
                result.get("max_drawdown"), result.get("win_rate"),
                result.get("total_trades"), result.get("parameters"),
                result.get("detailed_metrics")
            )
            return row["id"]

    async def cleanup_old_data(self, days: int = 90) -> None:
        """오래된 데이터 정리."""
        cutoff_date = datetime.now() - timedelta(days=days)
        async with self.pool.acquire() as conn:
            # 시장 데이터 정리
            await conn.execute(
                "DELETE FROM market_data WHERE time < $1",
                cutoff_date
            )

            # 주문 이력 정리 (더 오래 보관)
            await conn.execute(
                "DELETE FROM order_history WHERE time < $1",
                cutoff_date - timedelta(days=90)
            )

            logger.info(f"Cleaned up data older than {days} days")