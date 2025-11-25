"""Redis 기반 가격 캐시 with 적응형 TTL.

변동성 기반 TTL 자동 조정:
- 고변동성: 짧은 TTL (1초)
- 중변동성: 기본 TTL (2초)
- 저변동성: 긴 TTL (10초)

Write-through 캐싱 전략 구현.
"""

import json
import time
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
from decimal import Decimal

from ..utils.logger import get_logger
from .redis_manager import RedisManager

logger = get_logger(__name__)


class RedisPriceCache:
    """Redis 기반 가격 캐시 with 적응형 TTL.

    변동성에 따라 TTL을 자동으로 조정하여 캐시 효율성을 극대화합니다.
    Write-through 캐싱으로 데이터 일관성을 보장합니다.

    Attributes:
        redis: Redis 매니저
        base_ttl: 기본 TTL (초)
        min_ttl: 최소 TTL (초)
        max_ttl: 최대 TTL (초)
        volatility_window: 변동성 계산 윈도우 (초)
        volatility_threshold: 변동성 임계값 (%)
    """

    def __init__(
        self,
        redis_manager: RedisManager,
        base_ttl: int = 2,
        min_ttl: int = 1,
        max_ttl: int = 10,
        volatility_window: int = 60,
        volatility_threshold: float = 1.0
    ):
        """RedisPriceCache 초기화.

        Args:
            redis_manager: Redis 매니저 인스턴스
            base_ttl: 기본 TTL (기본값: 2초)
            min_ttl: 최소 TTL (기본값: 1초)
            max_ttl: 최대 TTL (기본값: 10초)
            volatility_window: 변동성 계산 윈도우 (기본값: 60초)
            volatility_threshold: 변동성 임계값 % (기본값: 1.0)
        """
        self.redis = redis_manager
        self.base_ttl = base_ttl
        self.min_ttl = min_ttl
        self.max_ttl = max_ttl
        self.volatility_window = volatility_window
        self.volatility_threshold = volatility_threshold

        # 캐시 키 프리픽스
        self.price_prefix = "price:"
        self.history_prefix = "price_history:"
        self.volatility_prefix = "volatility:"
        self.stats_prefix = "price_stats:"

    async def get(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """가격 데이터 조회 (캐시 우선).

        Args:
            stock_code: 종목코드

        Returns:
            가격 데이터 딕셔너리 또는 None
            {
                "code": "005930",
                "price": 70000,
                "timestamp": 1234567890.123,
                "volume": 1000000,
                "change": 1000,
                "change_rate": 1.45
            }
        """
        key = f"{self.price_prefix}{stock_code}"
        data = await self.redis.get(key)

        if data:
            # 캐시 히트 통계 업데이트
            await self._increment_stats(stock_code, "hits")
            logger.debug(f"[CACHE HIT] {stock_code}: price={data.get('price')}")
            return data
        else:
            # 캐시 미스 통계 업데이트
            await self._increment_stats(stock_code, "misses")
            logger.debug(f"[CACHE MISS] {stock_code}")
            return None

    async def set(
        self,
        stock_code: str,
        price_data: Dict[str, Any],
        write_through: bool = True
    ) -> bool:
        """가격 데이터 저장 with 적응형 TTL.

        Args:
            stock_code: 종목코드
            price_data: 가격 데이터 딕셔너리
            write_through: Write-through 캐싱 활성화 여부

        Returns:
            저장 성공 시 True
        """
        try:
            # 타임스탬프 추가
            if "timestamp" not in price_data:
                price_data["timestamp"] = time.time()

            # 변동성 계산 및 TTL 결정
            ttl = await self._calculate_adaptive_ttl(stock_code, price_data["price"])

            # 가격 캐시 저장
            key = f"{self.price_prefix}{stock_code}"
            success = await self.redis.set(key, price_data, ttl=ttl)

            if success:
                # 가격 히스토리 업데이트 (최근 N개 유지)
                await self._update_price_history(stock_code, price_data)

                # 변동성 업데이트
                await self._update_volatility(stock_code)

                # 통계 업데이트
                await self._increment_stats(stock_code, "writes")

                logger.debug(
                    f"[CACHE SET] {stock_code}: price={price_data.get('price')}, "
                    f"TTL={ttl}s, write_through={write_through}"
                )

                # Write-through: 다른 캐시나 영구 저장소에도 기록
                if write_through:
                    await self._write_through(stock_code, price_data)

            return success

        except Exception as e:
            logger.error(f"Failed to set price cache for {stock_code}: {e}")
            return False

    async def mget(self, stock_codes: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """여러 종목 가격 일괄 조회.

        Args:
            stock_codes: 종목코드 리스트

        Returns:
            종목코드별 가격 데이터 딕셔너리
        """
        keys = [f"{self.price_prefix}{code}" for code in stock_codes]
        values = await self.redis.mget(keys)

        result = {}
        for code, value in zip(stock_codes, values):
            result[code] = value
            if value:
                await self._increment_stats(code, "hits")
            else:
                await self._increment_stats(code, "misses")

        return result

    async def mset(
        self,
        price_data_map: Dict[str, Dict[str, Any]],
        write_through: bool = True
    ) -> bool:
        """여러 종목 가격 일괄 저장.

        Args:
            price_data_map: 종목코드별 가격 데이터 매핑
            write_through: Write-through 캐싱 활성화 여부

        Returns:
            저장 성공 시 True
        """
        try:
            # 각 종목별로 적응형 TTL 계산하고 저장
            for stock_code, price_data in price_data_map.items():
                await self.set(stock_code, price_data, write_through)

            return True

        except Exception as e:
            logger.error(f"Failed to mset price cache: {e}")
            return False

    async def _calculate_adaptive_ttl(self, stock_code: str, current_price: float) -> int:
        """변동성 기반 적응형 TTL 계산.

        Args:
            stock_code: 종목코드
            current_price: 현재 가격

        Returns:
            적응형 TTL (초)
        """
        try:
            # 이전 가격 조회
            key = f"{self.price_prefix}{stock_code}"
            prev_data = await self.redis.get(key)

            if not prev_data or "price" not in prev_data:
                # 첫 번째 데이터면 기본 TTL
                return self.base_ttl

            prev_price = prev_data["price"]

            # 가격을 float로 변환 (문자열, Decimal 등 처리)
            if isinstance(prev_price, str):
                prev_price = float(prev_price)
            elif isinstance(prev_price, Decimal):
                prev_price = float(prev_price)

            # 가격 변화율 계산
            if prev_price > 0:
                change_rate = abs((current_price - prev_price) / prev_price * 100)
            else:
                change_rate = 0

            # 변동성에 따른 TTL 조정
            if change_rate > self.volatility_threshold * 2:
                # 고변동성: 최소 TTL (빠른 업데이트 필요)
                ttl = self.min_ttl
                logger.debug(f"{stock_code}: High volatility ({change_rate:.2f}%), TTL={ttl}s")
            elif change_rate > self.volatility_threshold:
                # 중변동성: 기본 TTL
                ttl = self.base_ttl
                logger.debug(f"{stock_code}: Medium volatility ({change_rate:.2f}%), TTL={ttl}s")
            else:
                # 저변동성: 최대 TTL (API 부하 최소화)
                ttl = self.max_ttl
                logger.debug(f"{stock_code}: Low volatility ({change_rate:.2f}%), TTL={ttl}s")

            # 변동성 정보 저장 (최근 변화율 - 별도 키 사용)
            volatility_recent_key = f"{self.volatility_prefix}recent:{stock_code}"
            await self.redis.set(
                volatility_recent_key,
                {
                    "change_rate": change_rate,
                    "ttl": ttl,
                    "timestamp": time.time()
                },
                ttl=self.volatility_window
            )

            return ttl

        except Exception as e:
            logger.error(f"Failed to calculate adaptive TTL for {stock_code}: {e}")
            return self.base_ttl

    async def _update_price_history(self, stock_code: str, price_data: Dict[str, Any]) -> None:
        """가격 히스토리 업데이트 (최근 100개 유지).

        Args:
            stock_code: 종목코드
            price_data: 가격 데이터
        """
        try:
            history_key = f"{self.history_prefix}{stock_code}"

            # 새 데이터를 리스트 앞에 추가
            await self.redis.lpush(history_key, price_data)

            # 최대 100개만 유지
            await self.redis.client.ltrim(history_key, 0, 99)

            # 히스토리 TTL 설정 (1시간)
            await self.redis.expire(history_key, 3600)

        except Exception as e:
            logger.error(f"Failed to update price history for {stock_code}: {e}")

    async def _update_volatility(self, stock_code: str) -> None:
        """변동성 통계 업데이트.

        Args:
            stock_code: 종목코드
        """
        try:
            # 최근 가격 히스토리 조회
            history_key = f"{self.history_prefix}{stock_code}"
            history = await self.redis.lrange(history_key, 0, 19)  # 최근 20개

            if len(history) < 2:
                return

            # 가격 변동성 계산 (문자열 -> 숫자 변환)
            prices = []
            for item in history:
                if "price" in item:
                    price = item["price"]
                    # 문자열이면 숫자로 변환
                    if isinstance(price, str):
                        price = float(price)
                    prices.append(price)

            if len(prices) < 2:
                return

            # 표준편차 계산
            mean = sum(prices) / len(prices)
            variance = sum((p - mean) ** 2 for p in prices) / len(prices)
            std_dev = variance ** 0.5

            # 변동계수 (Coefficient of Variation)
            cv = (std_dev / mean * 100) if mean > 0 else 0

            # 변동성 통계 업데이트 (해시 타입 - 별도 키 사용)
            volatility_stats_key = f"{self.volatility_prefix}stats:{stock_code}"
            await self.redis.hset(volatility_stats_key, "cv", cv)
            await self.redis.hset(volatility_stats_key, "std_dev", std_dev)
            await self.redis.hset(volatility_stats_key, "mean", mean)

        except Exception as e:
            logger.error(f"Failed to update volatility for {stock_code}: {e}")

    async def _write_through(self, stock_code: str, price_data: Dict[str, Any]) -> None:
        """Write-through 캐싱: 다른 저장소에도 기록.

        Args:
            stock_code: 종목코드
            price_data: 가격 데이터
        """
        # 현재는 로깅만 수행
        # 실제 구현 시 데이터베이스나 다른 영구 저장소에 기록
        logger.debug(f"[WRITE-THROUGH] {stock_code}: {price_data}")

    async def _increment_stats(self, stock_code: str, stat_type: str) -> None:
        """캐시 통계 업데이트.

        Args:
            stock_code: 종목코드
            stat_type: 통계 타입 (hits, misses, writes)
        """
        try:
            stats_key = f"{self.stats_prefix}{stock_code}"
            await self.redis.incr(f"{stats_key}:{stat_type}")

            # 통계 TTL 설정 (24시간)
            await self.redis.expire(f"{stats_key}:{stat_type}", 86400)

        except Exception as e:
            logger.debug(f"Failed to update stats for {stock_code}: {e}")

    async def get_stats(self, stock_code: Optional[str] = None) -> Dict[str, Any]:
        """캐시 통계 조회.

        Args:
            stock_code: 특정 종목 코드 (None이면 전체)

        Returns:
            캐시 통계 딕셔너리
        """
        try:
            if stock_code:
                # 특정 종목 통계
                stats_key = f"{self.stats_prefix}{stock_code}"
                hits = await self.redis.get(f"{stats_key}:hits") or 0
                misses = await self.redis.get(f"{stats_key}:misses") or 0
                writes = await self.redis.get(f"{stats_key}:writes") or 0

                hit_rate = (hits / (hits + misses) * 100) if (hits + misses) > 0 else 0

                # 변동성 통계 정보
                volatility_stats_key = f"{self.volatility_prefix}stats:{stock_code}"
                volatility = await self.redis.hgetall(volatility_stats_key)

                return {
                    "stock_code": stock_code,
                    "hits": hits,
                    "misses": misses,
                    "writes": writes,
                    "hit_rate": f"{hit_rate:.2f}%",
                    "volatility": volatility
                }
            else:
                # 전체 통계 (간단 버전)
                return {
                    "message": "Use stock_code parameter for detailed stats"
                }

        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {}

    async def invalidate(self, stock_code: str) -> bool:
        """특정 종목 캐시 무효화.

        Args:
            stock_code: 종목코드

        Returns:
            성공 시 True
        """
        try:
            keys = [
                f"{self.price_prefix}{stock_code}",
                f"{self.history_prefix}{stock_code}",
                f"{self.volatility_prefix}recent:{stock_code}",
                f"{self.volatility_prefix}stats:{stock_code}"
            ]

            deleted = await self.redis.delete(*keys)
            logger.info(f"Invalidated cache for {stock_code}, deleted {deleted} keys")
            return deleted > 0

        except Exception as e:
            logger.error(f"Failed to invalidate cache for {stock_code}: {e}")
            return False

    async def invalidate_all(self) -> bool:
        """모든 가격 캐시 무효화.

        Returns:
            성공 시 True
        """
        try:
            # 패턴 매칭으로 모든 가격 관련 키 삭제
            # 주의: 프로덕션에서는 신중히 사용
            pattern_keys = [
                f"{self.price_prefix}*",
                f"{self.history_prefix}*",
                f"{self.volatility_prefix}*",
                f"{self.stats_prefix}*"
            ]

            total_deleted = 0
            for pattern in pattern_keys:
                # Redis SCAN으로 패턴 매칭 키 찾기
                cursor = 0
                while True:
                    cursor, keys = await self.redis.client.scan(cursor, match=pattern, count=100)
                    if keys:
                        deleted = await self.redis.delete(*keys)
                        total_deleted += deleted
                    if cursor == 0:
                        break

            logger.warning(f"Invalidated all price cache, deleted {total_deleted} keys")
            return True

        except Exception as e:
            logger.error(f"Failed to invalidate all cache: {e}")
            return False

    async def get_hot_stocks(self, top_n: int = 10) -> List[Tuple[str, int]]:
        """가장 많이 조회된 종목 목록.

        Args:
            top_n: 상위 N개

        Returns:
            (종목코드, 조회수) 튜플 리스트
        """
        try:
            # 모든 종목의 hits 조회
            pattern = f"{self.stats_prefix}*:hits"
            cursor = 0
            stock_hits = []

            while True:
                cursor, keys = await self.redis.client.scan(cursor, match=pattern, count=100)

                for key in keys:
                    # 키를 한 번만 디코드
                    key_str = key.decode() if isinstance(key, bytes) else key
                    hits = await self.redis.get(key_str)
                    if hits:
                        # 키에서 종목코드 추출 (이미 디코드된 key_str 사용)
                        stock_code = key_str.split(":")[2]
                        stock_hits.append((stock_code, int(hits)))

                if cursor == 0:
                    break

            # 조회수 기준 정렬
            stock_hits.sort(key=lambda x: x[1], reverse=True)

            return stock_hits[:top_n]

        except Exception as e:
            logger.error(f"Failed to get hot stocks: {e}")
            return []