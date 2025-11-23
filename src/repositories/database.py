"""SQLite 데이터베이스 스키마 및 초기화."""

import aiosqlite
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class Database:
    """SQLite 데이터베이스 관리 클래스.

    Attributes:
        db_path: 데이터베이스 파일 경로.
        connection: 데이터베이스 연결.
    """

    def __init__(self, db_path: Path):
        """데이터베이스 초기화.

        Args:
            db_path: 데이터베이스 파일 경로.
        """
        self.db_path = db_path
        self.connection: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """데이터베이스 연결."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(self.db_path)
        self.connection.row_factory = aiosqlite.Row
        logger.info(f"Database connected: {self.db_path}")

    async def disconnect(self) -> None:
        """데이터베이스 연결 해제."""
        if self.connection:
            await self.connection.close()
            logger.info("Database disconnected")

    async def init_schema(self) -> None:
        """데이터베이스 스키마 초기화.

        테이블이 존재하지 않으면 생성합니다.
        """
        if not self.connection:
            raise RuntimeError("Database not connected. Call connect() first.")

        await self._create_orders_table()
        await self._create_position_history_table()
        await self._create_chart_data_table()
        await self._create_notifications_table()

        await self.connection.commit()
        logger.info("Database schema initialized")

    async def _create_orders_table(self) -> None:
        """주문 내역 테이블 생성."""
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                account_number TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                order_type TEXT NOT NULL,
                price_type TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                limit_price TEXT,
                status TEXT NOT NULL,
                filled_quantity INTEGER DEFAULT 0,
                filled_price TEXT,
                strategy_name TEXT,
                created_at TEXT NOT NULL,
                submitted_at TEXT,
                filled_at TEXT,
                error_message TEXT
            )
        """)

        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_account ON orders(account_number)"
        )
        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_stock ON orders(stock_code)"
        )
        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)"
        )
        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at)"
        )

    async def _create_position_history_table(self) -> None:
        """포지션 히스토리 테이블 생성."""
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS position_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_number TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                average_buy_price TEXT NOT NULL,
                sell_price TEXT NOT NULL,
                realized_pnl TEXT NOT NULL,
                return_rate TEXT NOT NULL,
                strategy_name TEXT,
                opened_at TEXT NOT NULL,
                closed_at TEXT NOT NULL
            )
        """)

        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_position_history_account ON position_history(account_number)"
        )
        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_position_history_closed_at ON position_history(closed_at)"
        )

    async def _create_chart_data_table(self) -> None:
        """차트 데이터 테이블 생성."""
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS chart_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL,
                interval TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                open_price TEXT NOT NULL,
                high_price TEXT NOT NULL,
                low_price TEXT NOT NULL,
                close_price TEXT NOT NULL,
                volume INTEGER NOT NULL,
                UNIQUE(stock_code, interval, timestamp)
            )
        """)

        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_chart_data_stock_interval ON chart_data(stock_code, interval)"
        )
        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_chart_data_timestamp ON chart_data(timestamp)"
        )

    async def _create_notifications_table(self) -> None:
        """알림 로그 테이블 생성."""
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                notification_id TEXT PRIMARY KEY,
                notification_type TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                metadata TEXT,
                sent BOOLEAN NOT NULL,
                created_at TEXT NOT NULL,
                sent_at TEXT
            )
        """)

        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(notification_type)"
        )
        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at)"
        )


# 싱글톤 인스턴스
_database: Optional[Database] = None


async def get_database(db_path: Optional[Path] = None) -> Database:
    """데이터베이스 싱글톤 인스턴스 반환.

    Args:
        db_path: 데이터베이스 파일 경로 (기본값: data/trading.db).

    Returns:
        데이터베이스 인스턴스.

    Example:
        >>> db = await get_database()
        >>> await db.connect()
        >>> await db.init_schema()
    """
    global _database

    if _database is None:
        if db_path is None:
            db_path = Path("data/trading.db")
        _database = Database(db_path)

    return _database
