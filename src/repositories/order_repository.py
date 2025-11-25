"""OrderRepository 구현."""

from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime
import aiosqlite
import json

from ..models.order import Order


class OrderRepository(ABC):
    """주문 저장소 추상 클래스."""

    @abstractmethod
    async def save(self, order: Order) -> None:
        """주문 저장 또는 업데이트."""
        pass

    @abstractmethod
    async def get_by_id(self, order_id: str) -> Optional[Order]:
        """ID로 주문 조회."""
        pass

    @abstractmethod
    async def get_pending_orders(self, account_number: str) -> List[Order]:
        """계좌의 모든 미체결 주문 조회."""
        pass

    @abstractmethod
    async def get_orders_by_stock(
        self, stock_code: str, start_date: datetime, end_date: datetime
    ) -> List[Order]:
        """종목별 주문 내역 조회 (기간 지정)."""
        pass
    @abstractmethod
    async def get_orders_by_date_range(
        self, account_number: str, start_date: datetime, end_date: datetime
    ) -> List[Order]:
        """계좌의 주문 내역 조회 (기간 지정)."""
        pass



class SQLiteOrderRepository(OrderRepository):
    """SQLite 기반 주문 저장소."""

    def __init__(self, connection: aiosqlite.Connection):
        """저장소 초기화.

        Args:
            connection: SQLite 연결.
        """
        self.connection = connection

    async def save(self, order: Order) -> None:
        """주문 저장 또는 업데이트.

        Args:
            order: 저장할 주문.
        """
        await self.connection.execute(
            """
            INSERT INTO orders (
                order_id, account_number, stock_code, order_type, price_type,
                quantity, limit_price, status, filled_quantity, filled_price,
                strategy_name, created_at, submitted_at, filled_at, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET
                status = excluded.status,
                filled_quantity = excluded.filled_quantity,
                filled_price = excluded.filled_price,
                submitted_at = excluded.submitted_at,
                filled_at = excluded.filled_at,
                error_message = excluded.error_message
            """,
            (
                order.order_id,
                order.account_number,
                order.stock_code,
                order.order_type.value if hasattr(order.order_type, 'value') else order.order_type,
                order.price_type.value if hasattr(order.price_type, 'value') else order.price_type,
                order.quantity,
                str(order.limit_price) if order.limit_price else None,
                order.status.value if hasattr(order.status, 'value') else order.status,
                order.filled_quantity,
                str(order.filled_price) if order.filled_price else None,
                order.strategy_name,
                order.created_at.isoformat(),
                order.submitted_at.isoformat() if order.submitted_at else None,
                order.filled_at.isoformat() if order.filled_at else None,
                order.error_message,
            ),
        )
        await self.connection.commit()

    async def get_by_id(self, order_id: str) -> Optional[Order]:
        """ID로 주문 조회.

        Args:
            order_id: 주문 ID.

        Returns:
            주문 객체 또는 None.
        """
        cursor = await self.connection.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        )
        row = await cursor.fetchone()

        if row is None:
            return None

        return self._row_to_order(row)

    async def get_pending_orders(self, account_number: str) -> List[Order]:
        """계좌의 모든 미체결 주문 조회.

        Args:
            account_number: 계좌번호.

        Returns:
            미체결 주문 목록.
        """
        cursor = await self.connection.execute(
            """
            SELECT * FROM orders
            WHERE account_number = ?
            AND status IN ('PENDING', 'SUBMITTED', 'PARTIALLY_FILLED')
            ORDER BY created_at DESC
            """,
            (account_number,),
        )
        rows = await cursor.fetchall()

        return [self._row_to_order(row) for row in rows]

    async def get_orders_by_stock(
        self, stock_code: str, start_date: datetime, end_date: datetime
    ) -> List[Order]:
        """종목별 주문 내역 조회.

        Args:
            stock_code: 종목코드.
            start_date: 시작 날짜.
            end_date: 종료 날짜.

        Returns:
            주문 목록.
        """
        cursor = await self.connection.execute(
            """
            SELECT * FROM orders
            WHERE stock_code = ?
            AND created_at >= ?
            AND created_at <= ?
            ORDER BY created_at DESC
            """,
            (stock_code, start_date.isoformat(), end_date.isoformat()),
        )
        rows = await cursor.fetchall()

        return [self._row_to_order(row) for row in rows]


    async def get_orders_by_date_range(
        self, account_number: str, start_date: datetime, end_date: datetime
    ) -> List[Order]:
        """계좌의 주문 내역 조회 (기간 지정).

        Args:
            account_number: 계좌번호.
            start_date: 시작 날짜.
            end_date: 종료 날짜.

        Returns:
            주문 목록.
        """
        cursor = await self.connection.execute(
            """
            SELECT * FROM orders
            WHERE account_number = ?
            AND created_at >= ?
            AND created_at <= ?
            ORDER BY created_at DESC
            """,
            (account_number, start_date.isoformat(), end_date.isoformat()),
        )
        rows = await cursor.fetchall()

        return [self._row_to_order(row) for row in rows]

    def _row_to_order(self, row: aiosqlite.Row) -> Order:
        """DB 행을 Order 객체로 변환.

        Args:
            row: DB 행.

        Returns:
            Order 객체.
        """
        return Order(
            order_id=row["order_id"],
            account_number=row["account_number"],
            stock_code=row["stock_code"],
            order_type=row["order_type"],
            price_type=row["price_type"],
            quantity=row["quantity"],
            limit_price=row["limit_price"],
            status=row["status"],
            filled_quantity=row["filled_quantity"] or 0,
            filled_price=row["filled_price"],
            strategy_name=row["strategy_name"],
            created_at=datetime.fromisoformat(row["created_at"]),
            submitted_at=(
                datetime.fromisoformat(row["submitted_at"])
                if row["submitted_at"]
                else None
            ),
            filled_at=(
                datetime.fromisoformat(row["filled_at"]) if row["filled_at"] else None
            ),
            error_message=row["error_message"],
        )
