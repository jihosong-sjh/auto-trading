"""종목 정보 캐시 서비스.

종목코드와 종목명 매핑을 캐시하여 대시보드 등에서 종목명을 빠르게 조회할 수 있도록 합니다.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, Protocol
from zoneinfo import ZoneInfo

from ..utils.logger import get_logger

KST = ZoneInfo("Asia/Seoul")
logger = get_logger(__name__)


class StockPriceProvider(Protocol):
    """주식 가격/정보 조회 프로토콜."""

    async def get_stock_price(self, stock_code: str):
        """종목 정보를 조회합니다."""
        ...


class StockInfoCache:
    """종목 정보 캐시.

    종목코드 → 종목명 매핑을 메모리에 캐시합니다.
    캐시 미스 시 API를 호출하여 종목명을 가져옵니다.

    Attributes:
        client: 주식 정보 조회 클라이언트 (KiwoomClient 또는 Simulator)
        cache: 종목코드 → 종목명 캐시 딕셔너리
        cache_ttl: 캐시 만료 시간 (기본 24시간)
    """

    def __init__(
        self,
        client: Optional[StockPriceProvider] = None,
        cache_ttl_hours: int = 24,
    ):
        """StockInfoCache 초기화.

        Args:
            client: 주식 정보 조회 클라이언트 (없으면 캐시만 사용)
            cache_ttl_hours: 캐시 만료 시간 (시간 단위)
        """
        self.client = client
        self.cache_ttl = timedelta(hours=cache_ttl_hours)

        # 종목코드 → (종목명, 캐시 시간) 매핑
        self._cache: Dict[str, tuple[str, datetime]] = {}

        # API 호출 동시 실행 방지를 위한 락
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    def set_client(self, client: StockPriceProvider) -> None:
        """클라이언트를 설정합니다.

        Args:
            client: 주식 정보 조회 클라이언트
        """
        self.client = client
        logger.info("StockInfoCache client updated")

    def get_sync(self, stock_code: str) -> str:
        """동기적으로 종목명을 조회합니다 (캐시에서만).

        API 호출 없이 캐시된 값만 반환합니다.
        캐시에 없으면 빈 문자열을 반환합니다.

        Args:
            stock_code: 종목코드

        Returns:
            종목명 (캐시에 없으면 빈 문자열)
        """
        if stock_code in self._cache:
            name, cached_at = self._cache[stock_code]
            # TTL 확인
            if datetime.now(tz=KST) - cached_at < self.cache_ttl:
                return name

        return ""

    async def get(self, stock_code: str) -> str:
        """종목명을 조회합니다.

        캐시에 있으면 캐시에서 반환하고, 없으면 API를 호출합니다.

        Args:
            stock_code: 종목코드

        Returns:
            종목명 (조회 실패 시 빈 문자열)
        """
        # 1. 캐시 확인
        if stock_code in self._cache:
            name, cached_at = self._cache[stock_code]
            if datetime.now(tz=KST) - cached_at < self.cache_ttl:
                return name

        # 2. API 호출 (클라이언트가 없으면 빈 문자열 반환)
        if self.client is None:
            return ""

        # 3. 락 획득 (동일 종목 동시 호출 방지)
        async with self._global_lock:
            if stock_code not in self._locks:
                self._locks[stock_code] = asyncio.Lock()

        async with self._locks[stock_code]:
            # 락 획득 후 다시 캐시 확인 (다른 코루틴이 이미 조회했을 수 있음)
            if stock_code in self._cache:
                name, cached_at = self._cache[stock_code]
                if datetime.now(tz=KST) - cached_at < self.cache_ttl:
                    return name

            # API 호출
            try:
                stock = await self.client.get_stock_price(stock_code)
                stock_name = stock.stock_name if stock.stock_name else ""

                # 캐시 저장
                self._cache[stock_code] = (stock_name, datetime.now(tz=KST))
                logger.debug(f"Cached stock name: {stock_code} -> {stock_name}")

                return stock_name

            except Exception as e:
                logger.warning(f"Failed to fetch stock name for {stock_code}: {e}")
                return ""

    async def get_many(self, stock_codes: list[str]) -> Dict[str, str]:
        """여러 종목의 종목명을 조회합니다.

        Args:
            stock_codes: 종목코드 리스트

        Returns:
            종목코드 → 종목명 딕셔너리
        """
        result = {}
        tasks = []

        for code in stock_codes:
            # 캐시에서 먼저 확인
            cached_name = self.get_sync(code)
            if cached_name:
                result[code] = cached_name
            else:
                tasks.append((code, self.get(code)))

        # 캐시 미스인 종목들 병렬 조회
        if tasks:
            codes, coroutines = zip(*tasks)
            names = await asyncio.gather(*coroutines, return_exceptions=True)
            for code, name in zip(codes, names):
                if isinstance(name, Exception):
                    result[code] = ""
                else:
                    result[code] = name

        return result

    def set(self, stock_code: str, stock_name: str) -> None:
        """종목명을 캐시에 저장합니다.

        외부에서 종목명을 알고 있을 때 직접 캐시에 저장할 수 있습니다.

        Args:
            stock_code: 종목코드
            stock_name: 종목명
        """
        self._cache[stock_code] = (stock_name, datetime.now(tz=KST))

    def set_many(self, mappings: Dict[str, str]) -> None:
        """여러 종목명을 캐시에 저장합니다.

        Args:
            mappings: 종목코드 → 종목명 딕셔너리
        """
        now = datetime.now(tz=KST)
        for code, name in mappings.items():
            self._cache[code] = (name, now)

        logger.info(f"Cached {len(mappings)} stock names")

    def clear(self) -> None:
        """캐시를 초기화합니다."""
        self._cache.clear()
        logger.info("Stock info cache cleared")

    def get_cached_count(self) -> int:
        """캐시된 종목 수를 반환합니다."""
        return len(self._cache)

    def get_all_cached(self) -> Dict[str, str]:
        """캐시된 모든 종목명을 반환합니다.

        Returns:
            종목코드 → 종목명 딕셔너리 (만료된 항목 제외)
        """
        now = datetime.now(tz=KST)
        return {
            code: name
            for code, (name, cached_at) in self._cache.items()
            if now - cached_at < self.cache_ttl
        }
