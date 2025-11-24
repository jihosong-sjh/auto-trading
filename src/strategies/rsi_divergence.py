"""RSI Divergence 스캘핑 전략.

1분봉 RSI와 가격의 다이버전스를 이용한 단기 매매 전략입니다.
"""

from decimal import Decimal
from typing import List, Optional, Tuple

from ..models import Stock, Position
from ..models.strategy import BaseStrategy
from ..models.chart_data import ChartData


class RSIDivergenceStrategy(BaseStrategy):
    """RSI 다이버전스 스캘핑 전략.

    1분봉 데이터에서 가격과 RSI의 괴리를 감지하여 반전 기회를 포착합니다.

    매수 조건 (Bullish Divergence):
    - 가격: 저점이 낮아지는 추세 (Lower Low)
    - RSI: 저점이 높아지는 추세 (Higher Low)
    - RSI < oversold_threshold

    매도 조건 (Bearish Divergence):
    - 가격: 고점이 높아지는 추세 (Higher High)
    - RSI: 고점이 낮아지는 추세 (Lower High)
    - RSI > overbought_threshold

    또는 목표 수익률/손절 도달

    Attributes:
        rsi_period: RSI 계산 기간 (기본값: 14).
        oversold_threshold: 과매도 임계값 (기본값: 30).
        overbought_threshold: 과매수 임계값 (기본값: 70).
        lookback_periods: 다이버전스 확인 기간 (기본값: 5).
        target_profit_pct: 목표 수익률 (기본값: 0.015 = 1.5%).
        stop_loss_pct: 손절 비율 (기본값: 0.008 = 0.8%).
        position_size_pct: 가용 자금 대비 투자 비율 (기본값: 0.5 = 50%).
        chart_data_cache: 종목별 1분봉 차트 데이터 캐시.
    """

    def __init__(
        self,
        rsi_period: int = 14,
        oversold_threshold: float = 30,
        overbought_threshold: float = 70,
        lookback_periods: int = 5,
        target_profit_pct: float = 0.015,
        stop_loss_pct: float = 0.008,
        position_size_pct: float = 0.5,
    ):
        """RSI 다이버전스 전략 초기화.

        Args:
            rsi_period: RSI 계산 기간.
            oversold_threshold: 과매도 임계값 (0 ~ 100).
            overbought_threshold: 과매수 임계값 (0 ~ 100).
            lookback_periods: 다이버전스 확인 기간.
            target_profit_pct: 목표 수익률.
            stop_loss_pct: 손절 비율.
            position_size_pct: 가용 자금 대비 투자 비율 (0 ~ 1).

        Raises:
            ValueError: 파라미터 값이 유효하지 않은 경우.
        """
        super().__init__("RSIDivergence")

        if rsi_period < 2:
            raise ValueError("rsi_period must be >= 2")
        if not 0 <= oversold_threshold < overbought_threshold <= 100:
            raise ValueError("Invalid threshold values")
        if lookback_periods < 2:
            raise ValueError("lookback_periods must be >= 2")
        if not 0 < position_size_pct <= 1:
            raise ValueError("position_size_pct must be between 0 and 1")

        self.rsi_period = rsi_period
        self.oversold_threshold = Decimal(str(oversold_threshold))
        self.overbought_threshold = Decimal(str(overbought_threshold))
        self.lookback_periods = lookback_periods
        self.target_profit_pct = Decimal(str(target_profit_pct))
        self.stop_loss_pct = Decimal(str(stop_loss_pct))
        self.position_size_pct = Decimal(str(position_size_pct))

        self.chart_data_cache: dict[str, List[ChartData]] = {}

    def set_chart_data(self, stock_code: str, chart_data: List[ChartData]) -> None:
        """종목의 1분봉 차트 데이터 설정.

        Args:
            stock_code: 종목 코드.
            chart_data: 1분봉 차트 데이터 리스트 (시간순 정렬).
        """
        sorted_data = sorted(chart_data, key=lambda x: x.timestamp)
        self.chart_data_cache[stock_code] = sorted_data

    def add_chart_data(self, stock_code: str, new_data: ChartData) -> None:
        """종목의 차트 데이터에 새로운 데이터 추가.

        Args:
            stock_code: 종목 코드.
            new_data: 새로운 1분봉 데이터.
        """
        if stock_code not in self.chart_data_cache:
            self.chart_data_cache[stock_code] = []

        existing_timestamps = {data.timestamp for data in self.chart_data_cache[stock_code]}
        if new_data.timestamp not in existing_timestamps:
            self.chart_data_cache[stock_code].append(new_data)
            self.chart_data_cache[stock_code].sort(key=lambda x: x.timestamp)

    def calculate_rsi(self, prices: List[Decimal]) -> Optional[Decimal]:
        """RSI (Relative Strength Index) 계산.

        Args:
            prices: 종가 리스트 (시간순).

        Returns:
            RSI 값 (0 ~ 100). 데이터가 부족하면 None 반환.
        """
        if len(prices) < self.rsi_period + 1:
            return None

        # 가격 변화 계산
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]

        # 상승/하락 분리
        gains = [max(change, Decimal("0")) for change in changes]
        losses = [max(-change, Decimal("0")) for change in changes]

        # 평균 상승/하락 계산
        recent_gains = gains[-self.rsi_period:]
        recent_losses = losses[-self.rsi_period:]

        avg_gain = sum(recent_gains) / Decimal(str(self.rsi_period))
        avg_loss = sum(recent_losses) / Decimal(str(self.rsi_period))

        if avg_loss == 0:
            return Decimal("100")

        rs = avg_gain / avg_loss
        rsi = Decimal("100") - (Decimal("100") / (Decimal("1") + rs))

        return rsi

    def detect_bullish_divergence(
        self,
        prices: List[Decimal],
        rsi_values: List[Decimal]
    ) -> bool:
        """강세 다이버전스 감지.

        가격은 하락(Lower Low), RSI는 상승(Higher Low) 패턴 확인.

        Args:
            prices: 최근 종가 리스트.
            rsi_values: 최근 RSI 값 리스트.

        Returns:
            True: 강세 다이버전스 감지.
            False: 다이버전스 없음.
        """
        if len(prices) < 2 or len(rsi_values) < 2:
            return False

        # 가격: 현재 저점 < 이전 저점 (Lower Low)
        price_lower_low = prices[-1] < prices[0]

        # RSI: 현재 저점 > 이전 저점 (Higher Low)
        rsi_higher_low = rsi_values[-1] > rsi_values[0]

        return price_lower_low and rsi_higher_low

    def detect_bearish_divergence(
        self,
        prices: List[Decimal],
        rsi_values: List[Decimal]
    ) -> bool:
        """약세 다이버전스 감지.

        가격은 상승(Higher High), RSI는 하락(Lower High) 패턴 확인.

        Args:
            prices: 최근 종가 리스트.
            rsi_values: 최근 RSI 값 리스트.

        Returns:
            True: 약세 다이버전스 감지.
            False: 다이버전스 없음.
        """
        if len(prices) < 2 or len(rsi_values) < 2:
            return False

        # 가격: 현재 고점 > 이전 고점 (Higher High)
        price_higher_high = prices[-1] > prices[0]

        # RSI: 현재 고점 < 이전 고점 (Lower High)
        rsi_lower_high = rsi_values[-1] < rsi_values[0]

        return price_higher_high and rsi_lower_high

    async def evaluate_buy_signal(self, stock: Stock) -> bool:
        """매수 신호 평가.

        강세 다이버전스 감지 및 과매도 구간 확인.

        Args:
            stock: 종목 정보.

        Returns:
            True: 매수 신호 발생.
            False: 매수 신호 없음.
        """
        chart_data = self.chart_data_cache.get(stock.stock_code, [])
        if len(chart_data) < self.rsi_period + self.lookback_periods:
            return False

        # 종가 데이터 추출
        close_prices = [data.close_price for data in chart_data]

        # 현재 RSI 계산
        current_rsi = self.calculate_rsi(close_prices)
        if current_rsi is None or current_rsi >= self.oversold_threshold:
            return False

        # 최근 lookback_periods 동안의 가격과 RSI 추출
        recent_prices = close_prices[-self.lookback_periods:]
        recent_rsi_values = []

        for i in range(self.lookback_periods):
            lookback_prices = close_prices[:-(self.lookback_periods - i)]
            rsi = self.calculate_rsi(lookback_prices)
            if rsi is None:
                return False
            recent_rsi_values.append(rsi)

        # 강세 다이버전스 확인
        return self.detect_bullish_divergence(recent_prices, recent_rsi_values)

    async def evaluate_sell_signal(self, position: Position, stock: Stock) -> bool:
        """매도 신호 평가.

        약세 다이버전스, 익절, 손절 조건 확인.

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

        # 약세 다이버전스 확인
        chart_data = self.chart_data_cache.get(stock.stock_code, [])
        if len(chart_data) < self.rsi_period + self.lookback_periods:
            return False

        close_prices = [data.close_price for data in chart_data]

        current_rsi = self.calculate_rsi(close_prices)
        if current_rsi is None or current_rsi <= self.overbought_threshold:
            return False

        recent_prices = close_prices[-self.lookback_periods:]
        recent_rsi_values = []

        for i in range(self.lookback_periods):
            lookback_prices = close_prices[:-(self.lookback_periods - i)]
            rsi = self.calculate_rsi(lookback_prices)
            if rsi is None:
                return False
            recent_rsi_values.append(rsi)

        return self.detect_bearish_divergence(recent_prices, recent_rsi_values)

    def calculate_position_size(
        self,
        stock: Stock,
        available_balance: float
    ) -> Optional[int]:
        """포지션 크기 계산.

        가용 자금의 일부(position_size_pct)를 투자합니다.

        Args:
            stock: 종목 정보.
            available_balance: 사용 가능한 잔고.

        Returns:
            매수 수량 (주). None이면 매수하지 않음.
        """
        if stock.current_price <= 0:
            return None

        available_decimal = Decimal(str(available_balance))
        capital_to_use = available_decimal * self.position_size_pct

        quantity = int(capital_to_use / stock.current_price)

        return quantity if quantity > 0 else None
