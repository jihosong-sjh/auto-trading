"""VWAP Deviation 스캘핑 전략.

VWAP(Volume Weighted Average Price) 괴리율을 이용한 평균 회귀 전략입니다.
"""

from decimal import Decimal
from typing import List, Optional

from ..models import Stock, Position
from ..models.strategy import BaseStrategy
from ..models.chart_data import ChartData
from ..api.rate_limiter import RequestPriority


class VWAPDeviationStrategy(BaseStrategy):
    """VWAP 괴리율 스캘핑 전략.

    현재가와 VWAP의 괴리를 감지하여 평균 회귀 기회를 포착합니다.

    매수 조건:
    - 현재가 < VWAP
    - 괴리율 <= -buy_threshold (과매도)

    매도 조건:
    - 괴리율 >= sell_threshold (평균 회귀 또는 과매수)
    - 또는 목표 수익률/손절 도달

    Attributes:
        buy_threshold: 매수 신호 임계값 (기본값: 0.015 = 1.5% 하락).
        sell_threshold: 매도 신호 임계값 (기본값: 0.005 = 0.5% 상승).
        vwap_period: VWAP 계산 기간 (기본값: 20분봉).
        target_profit_pct: 목표 수익률 (기본값: 0.01 = 1%).
        stop_loss_pct: 손절 비율 (기본값: 0.008 = 0.8%).
        position_size_pct: 가용 자금 대비 투자 비율 (기본값: 0.5 = 50%).
        chart_data_cache: 종목별 차트 데이터 캐시.
    """

    def __init__(
        self,
        buy_threshold: float = 0.015,
        sell_threshold: float = 0.005,
        vwap_period: int = 20,
        target_profit_pct: float = 0.01,
        stop_loss_pct: float = 0.008,
        position_size_pct: float = 0.5,
    ):
        """VWAP 괴리율 전략 초기화.

        Args:
            buy_threshold: 매수 신호 임계값 (양수, 하락 괴리율).
            sell_threshold: 매도 신호 임계값 (양수, 상승 괴리율).
            vwap_period: VWAP 계산 기간.
            target_profit_pct: 목표 수익률.
            stop_loss_pct: 손절 비율.
            position_size_pct: 가용 자금 대비 투자 비율 (0 ~ 1).

        Raises:
            ValueError: 파라미터 값이 유효하지 않은 경우.
        """
        # 부모 클래스 초기화 (MEDIUM priority)
        super().__init__("VWAPDeviation", priority=RequestPriority.MEDIUM)

        if buy_threshold <= 0:
            raise ValueError("buy_threshold must be > 0")
        if sell_threshold <= 0:
            raise ValueError("sell_threshold must be > 0")
        if vwap_period < 2:
            raise ValueError("vwap_period must be >= 2")
        if not 0 < position_size_pct <= 1:
            raise ValueError("position_size_pct must be between 0 and 1")

        self.buy_threshold = Decimal(str(buy_threshold))
        self.sell_threshold = Decimal(str(sell_threshold))
        self.vwap_period = vwap_period
        self.target_profit_pct = Decimal(str(target_profit_pct))
        self.stop_loss_pct = Decimal(str(stop_loss_pct))
        self.position_size_pct = Decimal(str(position_size_pct))

        self.chart_data_cache: dict[str, List[ChartData]] = {}

    def set_chart_data(self, stock_code: str, chart_data: List[ChartData]) -> None:
        """종목의 차트 데이터 설정.

        Args:
            stock_code: 종목 코드.
            chart_data: 차트 데이터 리스트 (시간순 정렬).
        """
        sorted_data = sorted(chart_data, key=lambda x: x.timestamp)
        self.chart_data_cache[stock_code] = sorted_data

    def add_chart_data(self, stock_code: str, new_data: ChartData) -> None:
        """종목의 차트 데이터에 새로운 데이터 추가.

        Args:
            stock_code: 종목 코드.
            new_data: 새로운 차트 데이터.
        """
        if stock_code not in self.chart_data_cache:
            self.chart_data_cache[stock_code] = []

        existing_timestamps = {data.timestamp for data in self.chart_data_cache[stock_code]}
        if new_data.timestamp not in existing_timestamps:
            self.chart_data_cache[stock_code].append(new_data)
            self.chart_data_cache[stock_code].sort(key=lambda x: x.timestamp)

    def calculate_vwap(self, chart_data: List[ChartData]) -> Optional[Decimal]:
        """VWAP (Volume Weighted Average Price) 계산.

        VWAP = Σ(전형가격 × 거래량) / Σ(거래량)
        전형가격 = (고가 + 저가 + 종가) / 3

        Args:
            chart_data: 차트 데이터 리스트.

        Returns:
            VWAP 값. 데이터가 부족하거나 거래량이 0이면 None 반환.
        """
        if len(chart_data) < self.vwap_period:
            return None

        recent_data = chart_data[-self.vwap_period:]

        total_volume = sum(data.volume for data in recent_data)
        if total_volume == 0:
            return None

        # 전형가격 × 거래량 합계
        weighted_sum = Decimal("0")
        for data in recent_data:
            typical_price = (data.high_price + data.low_price + data.close_price) / Decimal("3")
            weighted_sum += typical_price * Decimal(str(data.volume))

        vwap = weighted_sum / Decimal(str(total_volume))
        return vwap

    def calculate_deviation(self, current_price: Decimal, vwap: Decimal) -> Decimal:
        """현재가와 VWAP의 괴리율 계산.

        괴리율 = (현재가 - VWAP) / VWAP
        - 양수: 현재가 > VWAP (과매수 가능)
        - 음수: 현재가 < VWAP (과매도 가능)

        Args:
            current_price: 현재 가격.
            vwap: VWAP 값.

        Returns:
            괴리율.
        """
        if vwap == 0:
            return Decimal("0")

        return (current_price - vwap) / vwap

    async def evaluate_buy_signal(self, stock: Stock) -> bool:
        """매수 신호 평가.

        현재가가 VWAP보다 낮고, 괴리율이 임계값 이상일 때 매수 신호 발생.

        Args:
            stock: 종목 정보.

        Returns:
            True: 매수 신호 발생.
            False: 매수 신호 없음.
        """
        chart_data = self.chart_data_cache.get(stock.stock_code, [])
        if len(chart_data) < self.vwap_period:
            return False

        vwap = self.calculate_vwap(chart_data)
        if vwap is None:
            return False

        deviation = self.calculate_deviation(stock.current_price, vwap)

        # 과매도 구간: 현재가 < VWAP, 괴리율 <= -buy_threshold
        if deviation <= -self.buy_threshold:
            return True

        return False

    async def evaluate_sell_signal(self, position: Position, stock: Stock) -> bool:
        """매도 신호 평가.

        괴리율 평균 회귀, 익절, 손절 조건 확인.

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

        # VWAP 괴리율 평균 회귀 확인
        chart_data = self.chart_data_cache.get(stock.stock_code, [])
        if len(chart_data) < self.vwap_period:
            return False

        vwap = self.calculate_vwap(chart_data)
        if vwap is None:
            return False

        deviation = self.calculate_deviation(stock.current_price, vwap)

        # 평균 회귀: 괴리율이 sell_threshold 이상 (VWAP 근처 또는 초과)
        if deviation >= self.sell_threshold:
            return True

        return False

    async def calculate_position_size(
        self,
        stock: Stock,
        available_balance: float
    ) -> Optional[int]:
        """포지션 크기 계산 (비동기).

        전달받은 가용 자금으로 매수 가능한 수량을 계산합니다.
        (position_size_pct는 strategy_engine에서 이미 적용됨)

        Args:
            stock: 종목 정보.
            available_balance: 사용 가능한 잔고 (이미 position_size_pct 적용됨).

        Returns:
            매수 수량 (주). None이면 매수하지 않음.
        """
        if stock.current_price <= 0:
            return None

        available_decimal = Decimal(str(available_balance))
        quantity = int(available_decimal / stock.current_price)

        return quantity if quantity > 0 else None
