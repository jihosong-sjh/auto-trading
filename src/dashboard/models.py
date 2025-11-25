"""Dashboard Pydantic models for API responses and WebSocket messages."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, computed_field


class WSMessageType(str, Enum):
    """WebSocket message types."""

    FULL_SNAPSHOT = "full_snapshot"
    POSITION_UPDATE = "position_update"
    PORTFOLIO_UPDATE = "portfolio_update"
    TRADE_EXECUTED = "trade_executed"
    PRICE_UPDATE = "price_update"
    CONNECTION_STATUS = "connection_status"


class DashboardPosition(BaseModel):
    """Position summary for dashboard display."""

    stock_code: str = Field(..., description="Stock code (6 digits)")
    stock_name: str = Field(default="", description="Stock name")
    quantity: int = Field(..., gt=0, description="Quantity held")
    average_buy_price: Decimal = Field(..., gt=0, description="Average buy price")
    current_price: Decimal = Field(..., gt=0, description="Current market price")
    strategy_name: Optional[str] = Field(None, description="Strategy that opened this position")
    updated_at: datetime = Field(..., description="Last update time")

    @computed_field
    @property
    def evaluation_amount(self) -> Decimal:
        """Total evaluation amount (current_price * quantity)."""
        return self.current_price * self.quantity

    @computed_field
    @property
    def unrealized_pnl(self) -> Decimal:
        """Unrealized P&L ((current - avg) * qty)."""
        return (self.current_price - self.average_buy_price) * self.quantity

    @computed_field
    @property
    def unrealized_pnl_pct(self) -> Decimal:
        """Unrealized P&L percentage ((current - avg) / avg * 100)."""
        if self.average_buy_price == 0:
            return Decimal("0")
        return ((self.current_price - self.average_buy_price) / self.average_buy_price) * 100

    class Config:
        json_encoders = {Decimal: str, datetime: lambda v: v.isoformat()}


class DashboardPortfolio(BaseModel):
    """Portfolio summary for dashboard display."""

    total_evaluation: Decimal = Field(..., description="Sum of all position values")
    total_unrealized_pnl: Decimal = Field(..., description="Sum of unrealized P&L")
    daily_realized_pnl: Decimal = Field(default=Decimal("0"), description="Daily realized P&L")
    cash_balance: Decimal = Field(..., ge=0, description="Available cash")
    total_asset_value: Decimal = Field(..., description="Cash + evaluation")
    position_count: int = Field(..., ge=0, description="Number of positions")
    updated_at: datetime = Field(..., description="Last update time")

    @computed_field
    @property
    def total_return_pct(self) -> Decimal:
        """Total return percentage."""
        # Avoid division by zero
        if self.total_asset_value == 0:
            return Decimal("0")
        return (self.total_unrealized_pnl / self.total_asset_value) * 100

    class Config:
        json_encoders = {Decimal: str, datetime: lambda v: v.isoformat()}


class DashboardTrade(BaseModel):
    """Trade history entry for dashboard display."""

    order_id: str = Field(..., description="Order ID")
    stock_code: str = Field(..., description="Stock code")
    stock_name: str = Field(default="", description="Stock name")
    order_type: str = Field(..., description="BUY or SELL")
    quantity: int = Field(..., gt=0, description="Filled quantity")
    filled_price: Decimal = Field(..., gt=0, description="Filled price")
    filled_at: datetime = Field(..., description="Fill time")
    strategy_name: Optional[str] = Field(None, description="Strategy name")
    realized_pnl: Optional[Decimal] = Field(None, description="Realized P&L (for SELL orders)")

    class Config:
        json_encoders = {Decimal: str, datetime: lambda v: v.isoformat()}


class WSMessage(BaseModel):
    """WebSocket message wrapper."""

    type: WSMessageType = Field(..., description="Message type")
    data: dict = Field(..., description="Message payload")
    timestamp: datetime = Field(..., description="Message timestamp")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class DashboardSnapshot(BaseModel):
    """Full dashboard snapshot sent on WebSocket connection."""

    positions: List[DashboardPosition] = Field(default_factory=list)
    portfolio: DashboardPortfolio
    trades_today: List[DashboardTrade] = Field(default_factory=list)

    class Config:
        json_encoders = {Decimal: str, datetime: lambda v: v.isoformat()}


class PositionUpdateData(BaseModel):
    """Data for position update message."""

    stock_code: str
    current_price: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_pct: Decimal
    evaluation_amount: Decimal

    class Config:
        json_encoders = {Decimal: str}


class TradeExecutedData(BaseModel):
    """Data for trade executed message."""

    order_id: str
    stock_code: str
    stock_name: str
    order_type: str
    quantity: int
    filled_price: Decimal
    filled_at: datetime
    strategy_name: Optional[str] = None
    realized_pnl: Optional[Decimal] = None

    class Config:
        json_encoders = {Decimal: str, datetime: lambda v: v.isoformat()}
