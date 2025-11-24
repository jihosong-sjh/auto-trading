"""호가창(Order Book) 모델 정의."""

from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field
from typing import List
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


class OrderBookLevel(BaseModel):
    """호가 단계 정보.
    
    Attributes:
        price: 호가 가격.
        quantity: 호가 수량.
    """
    
    price: Decimal = Field(..., gt=0, description="호가 가격")
    quantity: int = Field(..., ge=0, description="호가 수량")
    
    class Config:
        """Pydantic 설정."""
        frozen = True
        json_encoders = {Decimal: str}


class OrderBook(BaseModel):
    """호가창 데이터.
    
    실시간 매도/매수 호가 정보를 저장합니다.
    
    Attributes:
        stock_code: 종목코드 (6자리).
        ask_levels: 매도 호가 목록 (가격 낮은 순).
        bid_levels: 매수 호가 목록 (가격 높은 순).
        total_ask_quantity: 총 매도 잔량.
        total_bid_quantity: 총 매수 잔량.
        timestamp: 호가 데이터 시점 (KST).
    """
    
    stock_code: str = Field(..., pattern=r"^\d{6}$", description="종목코드")
    ask_levels: List[OrderBookLevel] = Field(default_factory=list, description="매도 호가 목록")
    bid_levels: List[OrderBookLevel] = Field(default_factory=list, description="매수 호가 목록")
    total_ask_quantity: int = Field(default=0, ge=0, description="총 매도 잔량")
    total_bid_quantity: int = Field(default=0, ge=0, description="총 매수 잔량")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(KST), description="호가 데이터 시점")
    
    def get_imbalance_ratio(self) -> Decimal:
        """호가 불균형 비율 계산.
        
        매수 압력이 강하면 양수, 매도 압력이 강하면 음수를 반환합니다.
        
        Returns:
            불균형 비율 = (총매수잔량 - 총매도잔량) / (총매수잔량 + 총매도잔량)
            범위: -1.0 ~ 1.0
            - 1.0: 매수 우세 (매도 잔량 0)
            - 0.0: 균형
            - -1.0: 매도 우세 (매수 잔량 0)
        
        Example:
            >>> order_book = OrderBook(
            ...     stock_code="005930",
            ...     total_bid_quantity=1000,
            ...     total_ask_quantity=500
            ... )
            >>> order_book.get_imbalance_ratio()
            Decimal('0.333...')  # 매수 우세
        """
        total = self.total_bid_quantity + self.total_ask_quantity
        if total == 0:
            return Decimal("0")
        
        imbalance = self.total_bid_quantity - self.total_ask_quantity
        return Decimal(str(imbalance)) / Decimal(str(total))
    
    def get_best_bid(self) -> Decimal:
        """최우선 매수 호가 가격 반환.
        
        Returns:
            최우선 매수 호가 가격. 호가가 없으면 0 반환.
        """
        if not self.bid_levels:
            return Decimal("0")
        return self.bid_levels[0].price
    
    def get_best_ask(self) -> Decimal:
        """최우선 매도 호가 가격 반환.
        
        Returns:
            최우선 매도 호가 가격. 호가가 없으면 0 반환.
        """
        if not self.ask_levels:
            return Decimal("0")
        return self.ask_levels[0].price
    
    def get_spread(self) -> Decimal:
        """매수-매도 스프레드 계산.
        
        Returns:
            스프레드 = 최우선 매도호가 - 최우선 매수호가.
            호가가 없으면 0 반환.
        """
        best_ask = self.get_best_ask()
        best_bid = self.get_best_bid()
        
        if best_ask == 0 or best_bid == 0:
            return Decimal("0")
        
        return best_ask - best_bid
    
    class Config:
        """Pydantic 설정."""
        frozen = False
        json_encoders = {Decimal: str, datetime: lambda v: v.isoformat()}
