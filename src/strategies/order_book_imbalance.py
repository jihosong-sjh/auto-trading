"""호가 불균형(Order Book Imbalance) 스캘핑 전략.

호가창의 매수/매도 잔량 불균형을 이용한 단기 매매 전략입니다.
"""

from decimal import Decimal
from typing import Optional

from ..models import Stock, Position
from ..models.strategy import BaseStrategy
from ..models.order_book import OrderBook
from ..api.rate_limiter import RequestPriority


class OrderBookImbalanceStrategy(BaseStrategy):
    """호가 불균형 스캘핑 전략.
    
    매수/매도 호가 잔량의 불균형을 감지하여 단기 매매 기회를 포착합니다.
    
    매수 조건:
    - 호가 불균형 비율 >= buy_threshold (매수 우세)
    - 스프레드가 max_spread_pct 이내
    
    매도 조건:
    - 호가 불균형 비율 <= sell_threshold (매도 우세)
    - 또는 목표 수익률/손절 도달
    
    Attributes:
        buy_threshold: 매수 신호 임계값 (기본값: 0.3 = 30% 매수 우세).
        sell_threshold: 매도 신호 임계값 (기본값: -0.2 = 20% 매도 우세).
        max_spread_pct: 최대 허용 스프레드 비율 (기본값: 0.005 = 0.5%).
        target_profit_pct: 목표 수익률 (기본값: 0.01 = 1%).
        stop_loss_pct: 손절 비율 (기본값: 0.005 = 0.5%).
        position_size_pct: 가용 자금 대비 투자 비율 (기본값: 0.5 = 50%).
        order_book_cache: 종목별 호가창 데이터 캐시.
    """
    
    def __init__(
        self,
        buy_threshold: float = 0.3,
        sell_threshold: float = -0.2,
        max_spread_pct: float = 0.005,
        target_profit_pct: float = 0.01,
        stop_loss_pct: float = 0.005,
        position_size_pct: float = 0.5,
    ):
        """호가 불균형 전략 초기화.
        
        Args:
            buy_threshold: 매수 신호 임계값 (0 ~ 1).
            sell_threshold: 매도 신호 임계값 (-1 ~ 0).
            max_spread_pct: 최대 허용 스프레드 비율.
            target_profit_pct: 목표 수익률.
            stop_loss_pct: 손절 비율.
            position_size_pct: 가용 자금 대비 투자 비율 (0 ~ 1).
        
        Raises:
            ValueError: 파라미터 값이 유효하지 않은 경우.
        """
        # 부모 클래스 초기화 (MEDIUM priority)
        super().__init__("OrderBookImbalance", priority=RequestPriority.MEDIUM)
        
        if not 0 <= buy_threshold <= 1:
            raise ValueError("buy_threshold must be between 0 and 1")
        if not -1 <= sell_threshold <= 0:
            raise ValueError("sell_threshold must be between -1 and 0")
        if not 0 < position_size_pct <= 1:
            raise ValueError("position_size_pct must be between 0 and 1")
        
        self.buy_threshold = Decimal(str(buy_threshold))
        self.sell_threshold = Decimal(str(sell_threshold))
        self.max_spread_pct = Decimal(str(max_spread_pct))
        self.target_profit_pct = Decimal(str(target_profit_pct))
        self.stop_loss_pct = Decimal(str(stop_loss_pct))
        self.position_size_pct = Decimal(str(position_size_pct))
        
        self.order_book_cache: dict[str, OrderBook] = {}
    
    def set_order_book(self, stock_code: str, order_book: OrderBook) -> None:
        """종목의 호가창 데이터 설정.
        
        Args:
            stock_code: 종목 코드.
            order_book: 호가창 데이터.
        """
        self.order_book_cache[stock_code] = order_book
    
    def get_order_book(self, stock_code: str) -> Optional[OrderBook]:
        """종목의 호가창 데이터 조회.
        
        Args:
            stock_code: 종목 코드.
        
        Returns:
            호가창 데이터. 캐시에 없으면 None 반환.
        """
        return self.order_book_cache.get(stock_code)
    
    async def evaluate_buy_signal(self, stock: Stock) -> bool:
        """매수 신호 평가.
        
        호가 불균형이 buy_threshold 이상이고,
        스프레드가 허용 범위 내일 때 매수 신호 발생.
        
        Args:
            stock: 종목 정보.
        
        Returns:
            True: 매수 신호 발생.
            False: 매수 신호 없음.
        """
        order_book = self.get_order_book(stock.stock_code)
        if order_book is None:
            return False
        
        # 호가 불균형 비율 확인
        imbalance = order_book.get_imbalance_ratio()
        if imbalance < self.buy_threshold:
            return False
        
        # 스프레드 확인 (스프레드가 너무 크면 진입하지 않음)
        spread = order_book.get_spread()
        best_ask = order_book.get_best_ask()
        
        if best_ask == 0:
            return False
        
        spread_pct = spread / best_ask
        if spread_pct > self.max_spread_pct:
            return False
        
        return True
    
    async def evaluate_sell_signal(self, position: Position, stock: Stock) -> bool:
        """매도 신호 평가.
        
        다음 조건 중 하나라도 만족하면 매도:
        1. 호가 불균형이 sell_threshold 이하 (매도 우세)
        2. 수익률이 target_profit_pct 이상 (익절)
        3. 수익률이 -stop_loss_pct 이하 (손절)
        
        Args:
            position: 현재 포지션.
            stock: 종목 정보.
        
        Returns:
            True: 매도 신호 발생.
            False: 매도 신호 없음.
        """
        # 손절 조건
        if position.return_rate <= -self.stop_loss_pct:
            return True
        
        # 익절 조건
        if position.return_rate >= self.target_profit_pct:
            return True
        
        # 호가 불균형 반전 확인
        order_book = self.get_order_book(stock.stock_code)
        if order_book is None:
            return False
        
        imbalance = order_book.get_imbalance_ratio()
        if imbalance <= self.sell_threshold:
            return True
        
        return False
    
    async def calculate_position_size(
        self,
        stock: Stock,
        available_balance: float
    ) -> Optional[int]:
        """포지션 크기 계산 (비동기).

        가용 자금의 일부(position_size_pct)를 투자합니다.
        스캘핑 전략이므로 보수적으로 포지션 크기를 조절합니다.

        Args:
            stock: 종목 정보.
            available_balance: 사용 가능한 잔고.

        Returns:
            매수 수량 (주). None이면 매수하지 않음.
        """
        if stock.current_price <= 0:
            return None
        
        # 호가창 확인
        order_book = self.get_order_book(stock.stock_code)
        if order_book is None:
            return None
        
        best_ask = order_book.get_best_ask()
        if best_ask <= 0:
            return None
        
        # 가용 자금의 일부만 투자
        available_decimal = Decimal(str(available_balance))
        capital_to_use = available_decimal * self.position_size_pct
        
        # 최우선 매도호가로 매수 수량 계산
        quantity = int(capital_to_use / best_ask)
        
        return quantity if quantity > 0 else None
