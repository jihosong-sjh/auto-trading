"""PositionRepository 구현."""

from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime
from decimal import Decimal
import aiosqlite

from ..models.position import Position


class PositionRepository(ABC):
    """포지션 저장소 추상 클래스."""

    @abstractmethod
    async def save_history(
        self,
        account_number: str,
        stock_code: str,
        quantity: int,
        average_buy_price: Decimal,
        sell_price: Decimal,
        realized_pnl: Decimal,
        return_rate: Decimal,
        strategy_name: Optional[str],
        opened_at: datetime,
        closed_at: datetime,
    ) -> None:
        """종료된 포지션을 히스토리에 저장."""
        pass

    @abstractmethod
    async def get_history_by_account(
        self, account_number: str, start_date: datetime, end_date: datetime
    ) -> List[dict]:
        """계좌의 포지션 히스토리 조회."""
        pass

    @abstractmethod
    async def get_history_by_stock(
        self, stock_code: str, start_date: datetime, end_date: datetime
    ) -> List[dict]:
        """종목별 포지션 히스토리 조회."""
        pass


class SQLitePositionRepository(PositionRepository):
    """SQLite 기반 포지션 저장소."""

    def __init__(self, connection: aiosqlite.Connection):
        """저장소 초기화.

        Args:
            connection: SQLite 연결.
        """
        self.connection = connection

    async def save_history(
        self,
        account_number: str,
        stock_code: str,
        quantity: int,
        average_buy_price: Decimal,
        sell_price: Decimal,
        realized_pnl: Decimal,
        return_rate: Decimal,
        strategy_name: Optional[str],
        opened_at: datetime,
        closed_at: datetime,
    ) -> None:
        """종료된 포지션을 히스토리에 저장.

        Args:
            account_number: 계좌번호.
            stock_code: 종목코드.
            quantity: 수량.
            average_buy_price: 평균 매수가.
            sell_price: 매도가.
            realized_pnl: 실현 손익.
            return_rate: 수익률.
            strategy_name: 전략 이름.
            opened_at: 포지션 개설 시간.
            closed_at: 포지션 종료 시간.
        """
        await self.connection.execute(
            """
            INSERT INTO position_history (
                account_number, stock_code, quantity, average_buy_price,
                sell_price, realized_pnl, return_rate, strategy_name,
                opened_at, closed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_number,
                stock_code,
                quantity,
                str(average_buy_price),
                str(sell_price),
                str(realized_pnl),
                str(return_rate),
                strategy_name,
                opened_at.isoformat(),
                closed_at.isoformat(),
            ),
        )
        await self.connection.commit()

    async def get_history_by_account(
        self, account_number: str, start_date: datetime, end_date: datetime
    ) -> List[dict]:
        """계좌의 포지션 히스토리 조회.

        Args:
            account_number: 계좌번호.
            start_date: 시작 날짜.
            end_date: 종료 날짜.

        Returns:
            포지션 히스토리 목록.
        """
        cursor = await self.connection.execute(
            """
            SELECT * FROM position_history
            WHERE account_number = ?
            AND closed_at >= ?
            AND closed_at <= ?
            ORDER BY closed_at DESC
            """,
            (account_number, start_date.isoformat(), end_date.isoformat()),
        )
        rows = await cursor.fetchall()

        return [self._row_to_dict(row) for row in rows]

    async def get_history_by_stock(
        self, stock_code: str, start_date: datetime, end_date: datetime
    ) -> List[dict]:
        """종목별 포지션 히스토리 조회.

        Args:
            stock_code: 종목코드.
            start_date: 시작 날짜.
            end_date: 종료 날짜.

        Returns:
            포지션 히스토리 목록.
        """
        cursor = await self.connection.execute(
            """
            SELECT * FROM position_history
            WHERE stock_code = ?
            AND closed_at >= ?
            AND closed_at <= ?
            ORDER BY closed_at DESC
            """,
            (stock_code, start_date.isoformat(), end_date.isoformat()),
        )
        rows = await cursor.fetchall()

        return [self._row_to_dict(row) for row in rows]

    def _row_to_dict(self, row: aiosqlite.Row) -> dict:
        """DB 행을 딕셔너리로 변환.

        Args:
            row: DB 행.

        Returns:
            포지션 히스토리 딕셔너리.
        """
        return {
            "id": row["id"],
            "account_number": row["account_number"],
            "stock_code": row["stock_code"],
            "quantity": row["quantity"],
            "average_buy_price": Decimal(row["average_buy_price"]),
            "sell_price": Decimal(row["sell_price"]),
            "realized_pnl": Decimal(row["realized_pnl"]),
            "return_rate": Decimal(row["return_rate"]),
            "strategy_name": row["strategy_name"],
            "opened_at": datetime.fromisoformat(row["opened_at"]),
            "closed_at": datetime.fromisoformat(row["closed_at"]),
        }
