"""골든크로스 전략 구현 모듈.

이 모듈은 이동평균선 교차(Golden Cross/Dead Cross)를 기반으로 매매 신호를 생성하는 전략을 구현합니다.
"""

from decimal import Decimal
from typing import List, Optional
from datetime import datetime

from ..models import Stock, Position
from ..models.strategy import BaseStrategy
from ..models.chart_data import ChartData
from ..api.rate_limiter import RequestPriority
from ..utils.logger import get_logger

logger = get_logger(__name__)


class GoldenCrossStrategy(BaseStrategy):
    """골든크로스 전략 구현.

    단기 이동평균선이 장기 이동평균선을 상향 돌파하면 매수 신호,
    하향 돌파하면 매도 신호를 생성합니다.

    Attributes:
        short_period: 단기 이동평균 기간 (기본값: 5)
        long_period: 장기 이동평균 기간 (기본값: 20)
        min_volume: 최소 거래량 조건 (기본값: 0)
        stop_loss_pct: 손절 비율 (기본값: 0.03 = 3%)
        take_profit_pct: 익절 비율 (기본값: 0.05 = 5%)
        chart_data_cache: 종목별 차트 데이터 캐시
    """

    def __init__(
        self,
        short_period: int = 5,
        long_period: int = 20,
        min_volume: int = 0,
        stop_loss_pct: float = 0.03,
        take_profit_pct: float = 0.05,
    ):
        """골든크로스 전략 초기화.

        Args:
            short_period: 단기 이동평균 기간 (기본값: 5)
            long_period: 장기 이동평균 기간 (기본값: 20)
            min_volume: 최소 거래량 조건 (기본값: 0)
            stop_loss_pct: 손절 비율 (기본값: 0.03)
            take_profit_pct: 익절 비율 (기본값: 0.05)

        Raises:
            ValueError: short_period >= long_period인 경우
        """
        # 부모 클래스 초기화 (HIGH priority - 중요한 장기 전략)
        super().__init__("GoldenCross", priority=RequestPriority.HIGH)

        if short_period >= long_period:
            raise ValueError("short_period must be less than long_period")

        self.short_period = short_period
        self.long_period = long_period
        self.min_volume = min_volume
        self.stop_loss_pct = Decimal(str(stop_loss_pct))
        self.take_profit_pct = Decimal(str(take_profit_pct))
        self.chart_data_cache: dict[str, List[ChartData]] = {}

    def calculate_sma(self, prices: List[Decimal], period: int) -> Optional[Decimal]:
        """단순 이동평균(SMA) 계산.

        Args:
            prices: 가격 데이터 리스트 (최신 데이터가 마지막)
            period: 이동평균 기간

        Returns:
            SMA 값. 데이터가 부족하면 None 반환.

        Example:
            >>> prices = [Decimal("100"), Decimal("110"), Decimal("120")]
            >>> strategy.calculate_sma(prices, 3)
            Decimal('110.00')
        """
        if len(prices) < period:
            return None

        recent_prices = prices[-period:]
        return sum(recent_prices) / Decimal(str(period))

    def set_chart_data(self, stock_code: str, chart_data: List[ChartData]) -> None:
        """종목의 차트 데이터를 캐시에 저장.

        Args:
            stock_code: 종목 코드
            chart_data: 차트 데이터 리스트 (시간순 정렬)
        """
        # 시간순 정렬 확인
        sorted_data = sorted(chart_data, key=lambda x: x.timestamp)
        self.chart_data_cache[stock_code] = sorted_data

    def add_chart_data(self, stock_code: str, new_data: ChartData) -> None:
        """종목의 차트 데이터에 새로운 데이터 추가.

        Args:
            stock_code: 종목 코드
            new_data: 새로운 차트 데이터
        """
        if stock_code not in self.chart_data_cache:
            self.chart_data_cache[stock_code] = []

        # 중복 방지 (같은 시간대 데이터)
        existing_timestamps = {data.timestamp for data in self.chart_data_cache[stock_code]}
        if new_data.timestamp not in existing_timestamps:
            self.chart_data_cache[stock_code].append(new_data)
            # 시간순 정렬 유지
            self.chart_data_cache[stock_code].sort(key=lambda x: x.timestamp)

    def get_close_prices(self, stock_code: str) -> List[Decimal]:
        """종목의 종가 데이터 추출.

        Args:
            stock_code: 종목 코드

        Returns:
            종가 리스트 (시간순)
        """
        if stock_code not in self.chart_data_cache:
            return []

        return [data.close_price for data in self.chart_data_cache[stock_code]]

    async def evaluate_buy_signal(self, stock: Stock) -> bool:
        """매수 신호 평가.

        골든크로스 발생 조건:
        1. 현재: 단기 SMA > 장기 SMA
        2. 이전: 단기 SMA <= 장기 SMA
        3. 거래량이 최소 거래량 이상

        Args:
            stock: 종목 정보

        Returns:
            True: 매수 신호 발생
            False: 매수 신호 없음
        """
        # 거래량 조건 확인
        if stock.volume < self.min_volume:
            logger.debug(
                f"[{stock.stock_code}] Volume too low: {stock.volume} < {self.min_volume}"
            )
            return False

        # 차트 데이터 확인
        close_prices = self.get_close_prices(stock.stock_code)
        if len(close_prices) < self.long_period:
            logger.debug(
                f"[{stock.stock_code}] Insufficient data: {len(close_prices)} candles "
                f"(need {self.long_period})"
            )
            return False

        # 현재 시점 SMA 계산
        current_short_sma = self.calculate_sma(close_prices, self.short_period)
        current_long_sma = self.calculate_sma(close_prices, self.long_period)

        if current_short_sma is None or current_long_sma is None:
            return False

        # 이전 시점 SMA 계산 (마지막 데이터 제외)
        previous_close_prices = close_prices[:-1]
        if len(previous_close_prices) < self.long_period:
            return False

        previous_short_sma = self.calculate_sma(previous_close_prices, self.short_period)
        previous_long_sma = self.calculate_sma(previous_close_prices, self.long_period)

        if previous_short_sma is None or previous_long_sma is None:
            return False

        # 골든크로스 확인: 이전에는 단기 <= 장기, 현재는 단기 > 장기
        golden_cross = (
            previous_short_sma <= previous_long_sma
            and current_short_sma > current_long_sma
        )

        if golden_cross:
            logger.info(
                f"[{stock.stock_code}] GOLDEN CROSS detected! "
                f"Short SMA({self.short_period}): {previous_short_sma:.2f} -> {current_short_sma:.2f}, "
                f"Long SMA({self.long_period}): {previous_long_sma:.2f} -> {current_long_sma:.2f}"
            )
        else:
            logger.debug(
                f"[{stock.stock_code}] No signal. "
                f"Short SMA: {current_short_sma:.2f}, Long SMA: {current_long_sma:.2f}"
            )

        return golden_cross

    async def evaluate_sell_signal(self, position: Position, stock: Stock) -> bool:
        """매도 신호 평가.

        매도 조건:
        1. 데드크로스 발생 (단기 SMA < 장기 SMA)
        2. 손절: 수익률 <= -stop_loss_pct
        3. 익절: 수익률 >= take_profit_pct

        Args:
            position: 현재 포지션
            stock: 종목 정보

        Returns:
            True: 매도 신호 발생
            False: 매도 신호 없음
        """
        # 손절 조건 확인
        if position.return_rate <= -self.stop_loss_pct:
            return True

        # 익절 조건 확인
        if position.return_rate >= self.take_profit_pct:
            return True

        # 데드크로스 확인
        close_prices = self.get_close_prices(stock.stock_code)
        if len(close_prices) < self.long_period:
            return False

        # 현재 시점 SMA 계산
        current_short_sma = self.calculate_sma(close_prices, self.short_period)
        current_long_sma = self.calculate_sma(close_prices, self.long_period)

        if current_short_sma is None or current_long_sma is None:
            return False

        # 이전 시점 SMA 계산
        previous_close_prices = close_prices[:-1]
        if len(previous_close_prices) < self.long_period:
            return False

        previous_short_sma = self.calculate_sma(previous_close_prices, self.short_period)
        previous_long_sma = self.calculate_sma(previous_close_prices, self.long_period)

        if previous_short_sma is None or previous_long_sma is None:
            return False

        # 데드크로스 확인: 이전에는 단기 >= 장기, 현재는 단기 < 장기
        dead_cross = (
            previous_short_sma >= previous_long_sma
            and current_short_sma < current_long_sma
        )

        return dead_cross

    async def calculate_position_size(
        self,
        stock: Stock,
        available_balance: float
    ) -> Optional[int]:
        """포지션 크기 계산 (비동기).

        가용 자금의 100%를 투자하되, 주식 단위로 반올림합니다.

        Args:
            stock: 종목 정보
            available_balance: 사용 가능한 잔고

        Returns:
            매수 수량 (주). None이면 매수하지 않음.

        Example:
            >>> stock = Stock(stock_code="005930", current_price=Decimal("70000"))
            >>> available_balance = 1000000.0
            >>> await strategy.calculate_position_size(stock, available_balance)
            14  # 1,000,000 / 70,000 = 14.28... -> 14주
        """
        if stock.current_price <= 0:
            return 0

        available_capital = Decimal(str(available_balance))
        quantity = int(available_capital / stock.current_price)
        return max(0, quantity)
