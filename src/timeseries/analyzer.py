"""Time-Series 데이터 분석기.

시계열 데이터 분석 및 지표 계산
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
import numpy as np
import pandas as pd
from dataclasses import dataclass

from .database import TimeSeriesDB
from .models import TechnicalIndicator


logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """분석 결과."""

    symbol: str
    timestamp: datetime
    indicators: Dict[str, float]
    signals: Dict[str, str]
    confidence: float
    recommendation: str  # "STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"


class TimeSeriesAnalyzer:
    """시계열 데이터 분석기."""

    def __init__(self, db: TimeSeriesDB):
        self.db = db
        self.cache: Dict[str, pd.DataFrame] = {}
        self.cache_ttl = 60  # 캐시 TTL (초)
        self.last_cache_time: Dict[str, datetime] = {}

    async def analyze(
        self,
        symbol: str,
        lookback_periods: int = 100,
        indicators: Optional[List[str]] = None
    ) -> AnalysisResult:
        """종합 분석 수행."""
        # 데이터 로드
        df = await self._load_data(symbol, lookback_periods)

        if df.empty:
            logger.warning(f"No data available for {symbol}")
            return None

        # 지표 계산
        if indicators is None:
            indicators = ["RSI", "MACD", "BB", "EMA", "SMA"]

        indicator_values = {}
        signals = {}

        for indicator in indicators:
            if indicator == "RSI":
                rsi_value = self.calculate_rsi(df)
                indicator_values["RSI"] = rsi_value
                signals["RSI"] = self._interpret_rsi(rsi_value)

            elif indicator == "MACD":
                macd, signal_line, histogram = self.calculate_macd(df)
                indicator_values["MACD"] = macd
                indicator_values["MACD_Signal"] = signal_line
                indicator_values["MACD_Histogram"] = histogram
                signals["MACD"] = self._interpret_macd(macd, signal_line)

            elif indicator == "BB":
                upper, middle, lower = self.calculate_bollinger_bands(df)
                indicator_values["BB_Upper"] = upper
                indicator_values["BB_Middle"] = middle
                indicator_values["BB_Lower"] = lower
                current_price = df["close"].iloc[-1]
                signals["BB"] = self._interpret_bollinger_bands(
                    current_price, upper, middle, lower
                )

            elif indicator == "EMA":
                ema_20 = self.calculate_ema(df, 20)
                ema_50 = self.calculate_ema(df, 50)
                indicator_values["EMA_20"] = ema_20
                indicator_values["EMA_50"] = ema_50
                signals["EMA"] = self._interpret_ema(
                    df["close"].iloc[-1], ema_20, ema_50
                )

            elif indicator == "SMA":
                sma_20 = self.calculate_sma(df, 20)
                sma_50 = self.calculate_sma(df, 50)
                indicator_values["SMA_20"] = sma_20
                indicator_values["SMA_50"] = sma_50
                signals["SMA"] = self._interpret_sma(
                    df["close"].iloc[-1], sma_20, sma_50
                )

        # 종합 판단
        recommendation, confidence = self._generate_recommendation(signals)

        return AnalysisResult(
            symbol=symbol,
            timestamp=datetime.now(),
            indicators=indicator_values,
            signals=signals,
            confidence=confidence,
            recommendation=recommendation
        )

    async def _load_data(
        self,
        symbol: str,
        lookback_periods: int
    ) -> pd.DataFrame:
        """데이터 로드 (캐시 활용)."""
        # 캐시 확인
        if symbol in self.cache:
            cache_age = datetime.now() - self.last_cache_time.get(symbol, datetime.min)
            if cache_age.total_seconds() < self.cache_ttl:
                return self.cache[symbol]

        # DB에서 로드
        end_time = datetime.now()
        start_time = end_time - timedelta(minutes=lookback_periods)

        df = await self.db.get_market_data(
            symbol=symbol,
            start_time=start_time,
            end_time=end_time
        )

        # 캐시 업데이트
        if not df.empty:
            self.cache[symbol] = df
            self.last_cache_time[symbol] = datetime.now()

        return df

    # 기술적 지표 계산 메서드
    def calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> float:
        """RSI (Relative Strength Index) 계산."""
        if len(df) < period:
            return 50.0  # 중립값 반환

        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        return float(rsi.iloc[-1])

    def calculate_macd(
        self,
        df: pd.DataFrame,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> Tuple[float, float, float]:
        """MACD (Moving Average Convergence Divergence) 계산."""
        ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, adjust=False).mean()

        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line

        return (
            float(macd_line.iloc[-1]),
            float(signal_line.iloc[-1]),
            float(histogram.iloc[-1])
        )

    def calculate_bollinger_bands(
        self,
        df: pd.DataFrame,
        period: int = 20,
        std_dev: int = 2
    ) -> Tuple[float, float, float]:
        """볼린저 밴드 계산."""
        sma = df["close"].rolling(window=period).mean()
        std = df["close"].rolling(window=period).std()

        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)

        return (
            float(upper_band.iloc[-1]),
            float(sma.iloc[-1]),
            float(lower_band.iloc[-1])
        )

    def calculate_ema(self, df: pd.DataFrame, period: int) -> float:
        """EMA (Exponential Moving Average) 계산."""
        ema = df["close"].ewm(span=period, adjust=False).mean()
        return float(ema.iloc[-1])

    def calculate_sma(self, df: pd.DataFrame, period: int) -> float:
        """SMA (Simple Moving Average) 계산."""
        sma = df["close"].rolling(window=period).mean()
        return float(sma.iloc[-1])

    def calculate_volume_profile(
        self,
        df: pd.DataFrame,
        bins: int = 20
    ) -> Dict[str, Any]:
        """거래량 프로파일 계산."""
        price_range = np.linspace(df["close"].min(), df["close"].max(), bins)
        volume_profile = {}

        for i in range(len(price_range) - 1):
            mask = (df["close"] >= price_range[i]) & (df["close"] < price_range[i + 1])
            volume_profile[f"{price_range[i]:.2f}-{price_range[i + 1]:.2f}"] = \
                float(df.loc[mask, "volume"].sum())

        # POC (Point of Control) 찾기
        poc_range = max(volume_profile, key=volume_profile.get)
        poc_price = sum(map(float, poc_range.split("-"))) / 2

        return {
            "profile": volume_profile,
            "poc": poc_price,
            "total_volume": float(df["volume"].sum())
        }

    # 지표 해석 메서드
    def _interpret_rsi(self, rsi: float) -> str:
        """RSI 해석."""
        if rsi > 70:
            return "SELL"  # 과매수
        elif rsi < 30:
            return "BUY"  # 과매도
        else:
            return "HOLD"

    def _interpret_macd(self, macd: float, signal: float) -> str:
        """MACD 해석."""
        if macd > signal and macd > 0:
            return "BUY"
        elif macd < signal and macd < 0:
            return "SELL"
        else:
            return "HOLD"

    def _interpret_bollinger_bands(
        self,
        price: float,
        upper: float,
        middle: float,
        lower: float
    ) -> str:
        """볼린저 밴드 해석."""
        if price > upper:
            return "SELL"  # 상단 밴드 돌파
        elif price < lower:
            return "BUY"  # 하단 밴드 돌파
        else:
            return "HOLD"

    def _interpret_ema(
        self,
        price: float,
        ema_short: float,
        ema_long: float
    ) -> str:
        """EMA 해석."""
        if ema_short > ema_long and price > ema_short:
            return "BUY"
        elif ema_short < ema_long and price < ema_short:
            return "SELL"
        else:
            return "HOLD"

    def _interpret_sma(
        self,
        price: float,
        sma_short: float,
        sma_long: float
    ) -> str:
        """SMA 해석."""
        if sma_short > sma_long and price > sma_short:
            return "BUY"
        elif sma_short < sma_long and price < sma_short:
            return "SELL"
        else:
            return "HOLD"

    def _generate_recommendation(
        self,
        signals: Dict[str, str]
    ) -> Tuple[str, float]:
        """종합 추천 생성."""
        # 신호 점수 계산
        score_map = {"BUY": 1, "SELL": -1, "HOLD": 0}
        scores = [score_map.get(signal, 0) for signal in signals.values()]

        if not scores:
            return "HOLD", 0.0

        avg_score = sum(scores) / len(scores)
        confidence = abs(avg_score)

        # 추천 결정
        if avg_score >= 0.6:
            recommendation = "STRONG_BUY"
        elif avg_score >= 0.2:
            recommendation = "BUY"
        elif avg_score <= -0.6:
            recommendation = "STRONG_SELL"
        elif avg_score <= -0.2:
            recommendation = "SELL"
        else:
            recommendation = "HOLD"

        return recommendation, confidence

    # 고급 분석 메서드
    async def detect_patterns(
        self,
        symbol: str,
        patterns: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """차트 패턴 감지."""
        df = await self._load_data(symbol, 200)

        if df.empty:
            return {}

        detected_patterns = {}

        if patterns is None:
            patterns = ["head_shoulders", "double_top", "triangle"]

        for pattern in patterns:
            if pattern == "head_shoulders":
                result = self._detect_head_shoulders(df)
                if result:
                    detected_patterns["head_shoulders"] = result

            elif pattern == "double_top":
                result = self._detect_double_top(df)
                if result:
                    detected_patterns["double_top"] = result

            elif pattern == "triangle":
                result = self._detect_triangle(df)
                if result:
                    detected_patterns["triangle"] = result

        return detected_patterns

    def _detect_head_shoulders(self, df: pd.DataFrame) -> Optional[Dict]:
        """헤드 앤 숄더 패턴 감지."""
        # 간단한 구현 예시
        prices = df["close"].values
        if len(prices) < 5:
            return None

        # 로컬 최대/최소값 찾기
        peaks = []
        valleys = []

        for i in range(1, len(prices) - 1):
            if prices[i] > prices[i - 1] and prices[i] > prices[i + 1]:
                peaks.append((i, prices[i]))
            elif prices[i] < prices[i - 1] and prices[i] < prices[i + 1]:
                valleys.append((i, prices[i]))

        # 헤드 앤 숄더 패턴 확인 (간단한 로직)
        if len(peaks) >= 3:
            left_shoulder = peaks[-3][1]
            head = peaks[-2][1]
            right_shoulder = peaks[-1][1]

            if head > left_shoulder and head > right_shoulder:
                if abs(left_shoulder - right_shoulder) / head < 0.05:  # 5% 오차
                    return {
                        "pattern": "head_and_shoulders",
                        "confidence": 0.7,
                        "signal": "SELL"
                    }

        return None

    def _detect_double_top(self, df: pd.DataFrame) -> Optional[Dict]:
        """더블 탑 패턴 감지."""
        # 구현 생략 (실제로는 더 복잡한 로직 필요)
        return None

    def _detect_triangle(self, df: pd.DataFrame) -> Optional[Dict]:
        """삼각형 패턴 감지."""
        # 구현 생략 (실제로는 더 복잡한 로직 필요)
        return None

    async def calculate_correlation(
        self,
        symbols: List[str],
        period: int = 100
    ) -> pd.DataFrame:
        """종목 간 상관관계 계산."""
        dfs = []

        for symbol in symbols:
            df = await self._load_data(symbol, period)
            if not df.empty:
                dfs.append(df[["close"]].rename(columns={"close": symbol}))

        if len(dfs) < 2:
            return pd.DataFrame()

        combined = pd.concat(dfs, axis=1)
        return combined.corr()