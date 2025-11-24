"""Time-Series 데이터 모델.

TimescaleDB에 저장되는 시계열 데이터 구조 정의
"""

from dataclasses import dataclass, asdict, field
from typing import Dict, Any, Optional, List
from datetime import datetime
from decimal import Decimal
from enum import Enum
import json


class OrderType(Enum):
    """주문 유형."""
    BUY = "BUY"
    SELL = "SELL"


class PriceType(Enum):
    """가격 유형."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(Enum):
    """주문 상태."""
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class MarketData:
    """시장 데이터 모델."""

    time: datetime
    symbol: str
    price: Decimal
    volume: int
    bid_price: Optional[Decimal] = None
    ask_price: Optional[Decimal] = None
    bid_volume: Optional[int] = None
    ask_volume: Optional[int] = None
    high: Optional[Decimal] = None
    low: Optional[Decimal] = None
    open: Optional[Decimal] = None
    close: Optional[Decimal] = None
    vwap: Optional[Decimal] = None  # Volume Weighted Average Price
    market_cap: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환."""
        data = asdict(self)
        # Decimal을 float로 변환
        for key, value in data.items():
            if isinstance(value, Decimal):
                data[key] = float(value)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MarketData":
        """딕셔너리에서 생성."""
        # float을 Decimal로 변환
        for key in ["price", "bid_price", "ask_price", "high", "low", "open", "close", "vwap"]:
            if key in data and data[key] is not None:
                data[key] = Decimal(str(data[key]))
        return cls(**data)


@dataclass
class OHLCV:
    """OHLCV (Open, High, Low, Close, Volume) 데이터."""

    time: datetime
    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    interval: str  # "1m", "5m", "1h", "1d" 등

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환."""
        return {
            "time": self.time.isoformat(),
            "symbol": self.symbol,
            "open": float(self.open),
            "high": float(self.high),
            "low": float(self.low),
            "close": float(self.close),
            "volume": self.volume,
            "interval": self.interval
        }


@dataclass
class OrderHistory:
    """주문 이력 모델."""

    time: datetime
    order_id: str
    symbol: str
    order_type: OrderType
    price_type: PriceType
    quantity: int
    price: Optional[Decimal] = None
    executed_price: Optional[Decimal] = None
    executed_quantity: Optional[int] = None
    status: OrderStatus = OrderStatus.PENDING
    strategy: Optional[str] = None
    signal_reason: Optional[str] = None
    commission: Optional[Decimal] = None
    slippage: Optional[Decimal] = None

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환."""
        data = asdict(self)
        # Enum을 문자열로 변환
        data["order_type"] = self.order_type.value
        data["price_type"] = self.price_type.value
        data["status"] = self.status.value
        # Decimal을 float로 변환
        for key in ["price", "executed_price", "commission", "slippage"]:
            if data.get(key) is not None:
                data[key] = float(data[key])
        return data


@dataclass
class Position:
    """포지션 정보."""

    symbol: str
    quantity: int
    avg_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    market_value: Decimal = Decimal("0")

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환."""
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "avg_price": float(self.avg_price),
            "current_price": float(self.current_price),
            "unrealized_pnl": float(self.unrealized_pnl),
            "realized_pnl": float(self.realized_pnl),
            "total_cost": float(self.total_cost),
            "market_value": float(self.market_value)
        }


@dataclass
class BalanceHistory:
    """잔고 이력 모델."""

    time: datetime
    account_id: str
    cash: Decimal
    total_value: Decimal
    positions: List[Position] = field(default_factory=list)
    daily_pnl: Optional[Decimal] = None
    total_pnl: Optional[Decimal] = None

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환."""
        return {
            "time": self.time,
            "account_id": self.account_id,
            "cash": float(self.cash),
            "total_value": float(self.total_value),
            "positions": json.dumps([p.to_dict() for p in self.positions]),
            "daily_pnl": float(self.daily_pnl) if self.daily_pnl else None,
            "total_pnl": float(self.total_pnl) if self.total_pnl else None
        }


@dataclass
class PerformanceMetrics:
    """성능 지표 모델."""

    time: datetime
    strategy: str
    metric_name: str
    metric_value: float
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환."""
        return {
            "time": self.time,
            "strategy": self.strategy,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "metadata": json.dumps(self.metadata) if self.metadata else None
        }


@dataclass
class BacktestResult:
    """백테스트 결과 모델."""

    strategy: str
    start_date: datetime
    end_date: datetime
    initial_capital: Decimal
    final_capital: Decimal
    total_return: float  # 퍼센트
    sharpe_ratio: float
    max_drawdown: float  # 퍼센트
    win_rate: float  # 퍼센트
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win: Decimal
    avg_loss: Decimal
    largest_win: Decimal
    largest_loss: Decimal
    parameters: Dict[str, Any]
    detailed_metrics: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환."""
        return {
            "strategy": self.strategy,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "initial_capital": float(self.initial_capital),
            "final_capital": float(self.final_capital),
            "total_return": self.total_return,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "win_rate": self.win_rate,
            "total_trades": self.total_trades,
            "parameters": json.dumps(self.parameters),
            "detailed_metrics": json.dumps(self.detailed_metrics)
        }

    def get_summary(self) -> str:
        """요약 문자열 반환."""
        return f"""
백테스트 결과 요약 - {self.strategy}
=====================================
기간: {self.start_date.date()} ~ {self.end_date.date()}
초기 자본: {self.initial_capital:,.0f}원
최종 자본: {self.final_capital:,.0f}원
총 수익률: {self.total_return:.2f}%
샤프 비율: {self.sharpe_ratio:.2f}
최대 낙폭: {self.max_drawdown:.2f}%
승률: {self.win_rate:.2f}%
총 거래: {self.total_trades}회
평균 이익: {self.avg_win:,.0f}원
평균 손실: {self.avg_loss:,.0f}원
        """


@dataclass
class TechnicalIndicator:
    """기술적 지표 모델."""

    time: datetime
    symbol: str
    indicator_name: str  # "RSI", "MACD", "BB", etc.
    value: float
    parameters: Dict[str, Any]  # {"period": 14} for RSI
    signal: Optional[str] = None  # "BUY", "SELL", "HOLD"

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환."""
        return {
            "time": self.time,
            "symbol": self.symbol,
            "indicator_name": self.indicator_name,
            "value": self.value,
            "parameters": self.parameters,
            "signal": self.signal
        }