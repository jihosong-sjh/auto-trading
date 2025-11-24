"""데이터 집계 및 분석 유틸리티.

Phase 3: Enhanced Data Pipeline
- 분봉 데이터를 다양한 시간 프레임으로 집계
- 기술 지표 계산
- 통계 분석
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np
from ..models import ChartInterval
from ..models.chart_data import ChartData
from ..services.minute_bar_collector import MinuteBar
from ..utils.logger import get_logger

KST = ZoneInfo("Asia/Seoul")
logger = get_logger(__name__)


@dataclass
class AggregatedData:
    """집계된 데이터.

    Attributes:
        stock_code: 종목코드
        interval: 집계 주기
        start_time: 시작 시간
        end_time: 종료 시간
        open_price: 시가
        high_price: 고가
        low_price: 저가
        close_price: 종가
        volume: 거래량
        vwap: 거래량 가중 평균가
        typical_price: 대표가 ((고가+저가+종가)/3)
        bar_count: 집계된 바 개수
    """

    stock_code: str
    interval: ChartInterval
    start_time: datetime
    end_time: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    vwap: Optional[Decimal] = None
    typical_price: Optional[Decimal] = None
    bar_count: int = 1

    def to_chart_data(self) -> ChartData:
        """ChartData 모델로 변환.

        Returns:
            ChartData 인스턴스
        """
        return ChartData(
            stock_code=self.stock_code,
            interval=self.interval,
            timestamp=self.start_time,
            open_price=self.open_price,
            high_price=self.high_price,
            low_price=self.low_price,
            close_price=self.close_price,
            volume=self.volume
        )


class DataAggregator:
    """데이터 집계 클래스.

    분봉 데이터를 상위 시간 프레임으로 집계하고
    다양한 기술 지표를 계산합니다.
    """

    @staticmethod
    def aggregate_bars(
        bars: List[MinuteBar],
        target_interval: ChartInterval
    ) -> List[AggregatedData]:
        """분봉 데이터를 목표 주기로 집계.

        Args:
            bars: 분봉 데이터 리스트 (시간순 정렬 필요)
            target_interval: 목표 집계 주기

        Returns:
            집계된 데이터 리스트
        """
        if not bars:
            return []

        # 집계 간격 (분 단위)
        interval_minutes = DataAggregator._get_interval_minutes(target_interval)
        if interval_minutes == 0:
            logger.warning(f"Cannot aggregate to {target_interval}")
            return []

        aggregated = []
        current_group = []
        current_window_start = None

        for bar in sorted(bars, key=lambda x: x.start_time):
            # 현재 바가 속하는 시간 윈도우 계산
            window_start = DataAggregator._get_window_start(
                bar.start_time, interval_minutes
            )

            # 새 윈도우 시작
            if current_window_start is None:
                current_window_start = window_start
                current_group = [bar]

            # 같은 윈도우
            elif window_start == current_window_start:
                current_group.append(bar)

            # 다음 윈도우
            else:
                # 현재 그룹 집계
                if current_group:
                    agg_data = DataAggregator._aggregate_group(
                        current_group, target_interval
                    )
                    aggregated.append(agg_data)

                # 새 그룹 시작
                current_window_start = window_start
                current_group = [bar]

        # 마지막 그룹 처리
        if current_group:
            agg_data = DataAggregator._aggregate_group(
                current_group, target_interval
            )
            aggregated.append(agg_data)

        return aggregated

    @staticmethod
    def _get_interval_minutes(interval: ChartInterval) -> int:
        """ChartInterval을 분 단위로 변환.

        Args:
            interval: 차트 주기

        Returns:
            분 단위 간격
        """
        interval_map = {
            ChartInterval.MINUTE_1: 1,
            ChartInterval.MINUTE_5: 5,
            ChartInterval.MINUTE_10: 10,
            ChartInterval.MINUTE_30: 30,
            ChartInterval.MINUTE_60: 60,
            ChartInterval.DAY: 1440,  # 24 * 60
        }
        return interval_map.get(interval, 0)

    @staticmethod
    def _get_window_start(timestamp: datetime, interval_minutes: int) -> datetime:
        """해당 시점이 속하는 윈도우의 시작 시간.

        Args:
            timestamp: 기준 시점
            interval_minutes: 간격 (분)

        Returns:
            윈도우 시작 시간
        """
        if interval_minutes >= 1440:  # 일 단위
            # 당일 시작 (00:00)
            return timestamp.replace(hour=0, minute=0, second=0, microsecond=0)

        # 분 단위 정렬
        minute = timestamp.minute
        aligned_minute = (minute // interval_minutes) * interval_minutes

        return timestamp.replace(
            minute=aligned_minute,
            second=0,
            microsecond=0
        )

    @staticmethod
    def _aggregate_group(
        bars: List[MinuteBar],
        interval: ChartInterval
    ) -> AggregatedData:
        """바 그룹을 하나의 집계 데이터로 변환.

        Args:
            bars: 분봉 리스트
            interval: 목표 주기

        Returns:
            집계된 데이터
        """
        if not bars:
            raise ValueError("Cannot aggregate empty bar list")

        # 시간순 정렬
        bars = sorted(bars, key=lambda x: x.start_time)

        first_bar = bars[0]
        last_bar = bars[-1]

        # OHLCV 집계
        open_price = first_bar.open_price
        close_price = last_bar.close_price
        high_price = max(bar.high_price for bar in bars)
        low_price = min(bar.low_price for bar in bars)
        total_volume = sum(bar.volume for bar in bars)

        # VWAP 계산 (Volume Weighted Average Price)
        vwap = None
        if total_volume > 0:
            weighted_sum = sum(
                bar.close_price * bar.volume
                for bar in bars
            )
            vwap = weighted_sum / total_volume

        # 대표가 계산
        typical_price = (high_price + low_price + close_price) / 3

        return AggregatedData(
            stock_code=first_bar.stock_code,
            interval=interval,
            start_time=first_bar.start_time,
            end_time=last_bar.end_time,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            close_price=close_price,
            volume=total_volume,
            vwap=vwap,
            typical_price=typical_price,
            bar_count=len(bars)
        )

    @staticmethod
    def calculate_moving_average(
        data: List[ChartData],
        period: int,
        price_type: str = "close"
    ) -> List[Optional[Decimal]]:
        """이동평균 계산.

        Args:
            data: 차트 데이터 리스트
            period: 이동평균 기간
            price_type: 가격 유형 (close, open, high, low)

        Returns:
            이동평균 리스트
        """
        if len(data) < period:
            return [None] * len(data)

        # 가격 추출
        prices = []
        for item in data:
            if price_type == "close":
                prices.append(float(item.close_price))
            elif price_type == "open":
                prices.append(float(item.open_price))
            elif price_type == "high":
                prices.append(float(item.high_price))
            elif price_type == "low":
                prices.append(float(item.low_price))
            else:
                prices.append(float(item.close_price))

        # 이동평균 계산
        ma_values = []
        for i in range(len(prices)):
            if i < period - 1:
                ma_values.append(None)
            else:
                window = prices[i - period + 1:i + 1]
                ma = sum(window) / period
                ma_values.append(Decimal(str(ma)))

        return ma_values

    @staticmethod
    def calculate_ema(
        data: List[ChartData],
        period: int,
        price_type: str = "close"
    ) -> List[Optional[Decimal]]:
        """지수이동평균 (EMA) 계산.

        Args:
            data: 차트 데이터 리스트
            period: EMA 기간
            price_type: 가격 유형

        Returns:
            EMA 리스트
        """
        if len(data) < period:
            return [None] * len(data)

        # 가격 추출
        prices = []
        for item in data:
            if price_type == "close":
                prices.append(float(item.close_price))
            elif price_type == "open":
                prices.append(float(item.open_price))
            elif price_type == "high":
                prices.append(float(item.high_price))
            elif price_type == "low":
                prices.append(float(item.low_price))
            else:
                prices.append(float(item.close_price))

        # EMA 계산
        multiplier = 2 / (period + 1)
        ema_values = []

        # 첫 EMA는 단순 이동평균
        sma = sum(prices[:period]) / period
        ema_values.extend([None] * (period - 1))
        ema_values.append(Decimal(str(sma)))

        # 이후 EMA 계산
        for i in range(period, len(prices)):
            ema = (prices[i] * multiplier) + (float(ema_values[-1]) * (1 - multiplier))
            ema_values.append(Decimal(str(ema)))

        return ema_values

    @staticmethod
    def calculate_bollinger_bands(
        data: List[ChartData],
        period: int = 20,
        num_std: float = 2.0
    ) -> Tuple[List[Optional[Decimal]], List[Optional[Decimal]], List[Optional[Decimal]]]:
        """볼린저 밴드 계산.

        Args:
            data: 차트 데이터 리스트
            period: 이동평균 기간
            num_std: 표준편차 배수

        Returns:
            (상단밴드, 중간밴드, 하단밴드) 튜플
        """
        if len(data) < period:
            none_list = [None] * len(data)
            return none_list, none_list, none_list

        # 종가 추출
        prices = [float(item.close_price) for item in data]

        upper_band = []
        middle_band = []
        lower_band = []

        for i in range(len(prices)):
            if i < period - 1:
                upper_band.append(None)
                middle_band.append(None)
                lower_band.append(None)
            else:
                window = prices[i - period + 1:i + 1]
                mean = np.mean(window)
                std = np.std(window)

                middle_band.append(Decimal(str(mean)))
                upper_band.append(Decimal(str(mean + num_std * std)))
                lower_band.append(Decimal(str(mean - num_std * std)))

        return upper_band, middle_band, lower_band

    @staticmethod
    def calculate_rsi(
        data: List[ChartData],
        period: int = 14
    ) -> List[Optional[Decimal]]:
        """RSI (Relative Strength Index) 계산.

        Args:
            data: 차트 데이터 리스트
            period: RSI 기간

        Returns:
            RSI 리스트 (0-100)
        """
        if len(data) < period + 1:
            return [None] * len(data)

        # 가격 변화 계산
        prices = [float(item.close_price) for item in data]
        gains = []
        losses = []

        for i in range(1, len(prices)):
            change = prices[i] - prices[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        # RSI 계산
        rsi_values = [None]  # 첫 값은 None

        # 첫 평균
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period):
            rsi_values.append(None)

        # RSI 계산
        for i in range(period, len(gains)):
            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))

            rsi_values.append(Decimal(str(rsi)))

            # 평균 업데이트 (Smoothed MA)
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        return rsi_values

    @staticmethod
    def calculate_macd(
        data: List[ChartData],
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9
    ) -> Tuple[List[Optional[Decimal]], List[Optional[Decimal]], List[Optional[Decimal]]]:
        """MACD 계산.

        Args:
            data: 차트 데이터 리스트
            fast_period: 빠른 EMA 기간
            slow_period: 느린 EMA 기간
            signal_period: 시그널 EMA 기간

        Returns:
            (MACD선, 시그널선, 히스토그램) 튜플
        """
        if len(data) < slow_period:
            none_list = [None] * len(data)
            return none_list, none_list, none_list

        # EMA 계산
        fast_ema = DataAggregator.calculate_ema(data, fast_period)
        slow_ema = DataAggregator.calculate_ema(data, slow_period)

        # MACD 라인 = 빠른 EMA - 느린 EMA
        macd_line = []
        for i in range(len(data)):
            if fast_ema[i] is None or slow_ema[i] is None:
                macd_line.append(None)
            else:
                macd_line.append(fast_ema[i] - slow_ema[i])

        # 시그널 라인 = MACD의 EMA
        signal_line = []
        macd_values = [float(m) if m is not None else 0 for m in macd_line]

        # 유효한 MACD 값만 사용
        valid_start = slow_period - 1
        if valid_start + signal_period > len(macd_values):
            signal_line = [None] * len(data)
        else:
            signal_line = [None] * valid_start

            # 첫 시그널은 단순평균
            first_signal = sum(macd_values[valid_start:valid_start + signal_period]) / signal_period
            signal_line.extend([None] * (signal_period - 1))
            signal_line.append(Decimal(str(first_signal)))

            # 이후 시그널 EMA
            multiplier = 2 / (signal_period + 1)
            for i in range(valid_start + signal_period, len(macd_values)):
                if macd_line[i] is not None:
                    signal = (float(macd_line[i]) * multiplier) + (float(signal_line[-1]) * (1 - multiplier))
                    signal_line.append(Decimal(str(signal)))
                else:
                    signal_line.append(None)

        # 히스토그램 = MACD - 시그널
        histogram = []
        for i in range(len(data)):
            if macd_line[i] is None or signal_line[i] is None:
                histogram.append(None)
            else:
                histogram.append(macd_line[i] - signal_line[i])

        return macd_line, signal_line, histogram

    @staticmethod
    def calculate_volume_profile(
        data: List[ChartData],
        num_levels: int = 20
    ) -> Dict[Decimal, int]:
        """거래량 프로파일 계산.

        Args:
            data: 차트 데이터 리스트
            num_levels: 가격대 개수

        Returns:
            가격대별 거래량 딕셔너리
        """
        if not data:
            return {}

        # 가격 범위 계산
        all_prices = []
        for item in data:
            all_prices.extend([item.high_price, item.low_price])

        min_price = min(all_prices)
        max_price = max(all_prices)

        if min_price == max_price:
            return {min_price: sum(item.volume for item in data)}

        # 가격대 설정
        price_range = max_price - min_price
        level_size = price_range / num_levels

        # 거래량 누적
        volume_profile = {}

        for level in range(num_levels):
            level_price = min_price + Decimal(str(level + 0.5)) * level_size
            level_volume = 0

            for item in data:
                # 해당 가격대에 포함되는 거래량 계산
                if item.low_price <= level_price <= item.high_price:
                    # 단순화: 전체 거래량을 해당 레벨에 할당
                    level_volume += item.volume

            volume_profile[level_price] = level_volume

        return volume_profile

    @staticmethod
    def calculate_statistics(
        data: List[ChartData]
    ) -> Dict[str, Decimal]:
        """기본 통계 계산.

        Args:
            data: 차트 데이터 리스트

        Returns:
            통계 정보 딕셔너리
        """
        if not data:
            return {}

        prices = [float(item.close_price) for item in data]
        volumes = [item.volume for item in data]

        # 수익률 계산
        returns = []
        for i in range(1, len(prices)):
            ret = (prices[i] - prices[i - 1]) / prices[i - 1]
            returns.append(ret)

        stats = {
            "count": Decimal(str(len(data))),
            "mean_price": Decimal(str(np.mean(prices))),
            "std_price": Decimal(str(np.std(prices))),
            "min_price": Decimal(str(min(prices))),
            "max_price": Decimal(str(max(prices))),
            "total_volume": Decimal(str(sum(volumes))),
            "mean_volume": Decimal(str(np.mean(volumes))),
        }

        if returns:
            stats.update({
                "mean_return": Decimal(str(np.mean(returns))),
                "std_return": Decimal(str(np.std(returns))),
                "sharpe_ratio": Decimal(str(np.mean(returns) / np.std(returns))) if np.std(returns) > 0 else Decimal("0"),
            })

        return stats