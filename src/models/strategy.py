"""BaseStrategy 추상 클래스 정의."""

from abc import ABC, abstractmethod
from typing import Optional
from .stock import Stock
from .position import Position
from ..api.rate_limiter import RequestPriority


class BaseStrategy(ABC):
    """전략 기본 추상 클래스.

    모든 전략은 이 클래스를 상속하여 구현해야 합니다.

    Attributes:
        strategy_name: 전략 이름.
        priority: 차트 데이터 로딩 우선순위 (RequestPriority).
    """

    def __init__(self, strategy_name: str, priority: RequestPriority = RequestPriority.MEDIUM):
        """전략 초기화.

        Args:
            strategy_name: 전략 고유 이름.
            priority: 차트 데이터 로딩 우선순위 (기본값: MEDIUM).
        """
        self.strategy_name = strategy_name
        self.priority = priority

    @abstractmethod
    async def evaluate_buy_signal(self, stock: Stock) -> bool:
        """매수 시그널 평가.

        종목이 매수 조건을 충족하는지 평가합니다.

        Args:
            stock: 평가할 종목.

        Returns:
            매수 시그널 감지 시 True, 아니면 False.

        Example:
            >>> strategy = MyStrategy("Example")
            >>> stock = Stock(...)
            >>> if await strategy.evaluate_buy_signal(stock):
            ...     print("Buy signal detected")
        """
        pass

    @abstractmethod
    async def evaluate_sell_signal(self, position: Position, stock: Stock) -> bool:
        """매도 시그널 평가.

        포지션이 매도 조건을 충족하는지 평가합니다.

        Args:
            position: 평가할 포지션.
            stock: 종목 시장 데이터.

        Returns:
            매도 시그널 감지 시 True, 아니면 False.

        Example:
            >>> strategy = MyStrategy("Example")
            >>> position = Position(...)
            >>> stock = Stock(...)
            >>> if await strategy.evaluate_sell_signal(position, stock):
            ...     print("Sell signal detected")
        """
        pass

    @abstractmethod
    async def calculate_position_size(
        self, stock: Stock, available_balance: float
    ) -> Optional[int]:
        """포지션 크기 계산 (비동기).

        매수할 수량을 계산합니다.
        향후 외부 API 호출(예: 재무제표 조회, 뉴스 분석 등)을 지원하기 위해 비동기로 구현합니다.

        Args:
            stock: 매수할 종목.
            available_balance: 사용 가능한 잔고.

        Returns:
            매수 수량 (주). None이면 매수하지 않음.

        Example:
            >>> strategy = MyStrategy("Example")
            >>> stock = Stock(...)
            >>> quantity = await strategy.calculate_position_size(stock, 1000000)
            >>> print(f"Buy {quantity} shares")
        """
        pass

    def get_strategy_name(self) -> str:
        """전략 이름 반환.

        Returns:
            전략 이름.
        """
        return self.strategy_name
