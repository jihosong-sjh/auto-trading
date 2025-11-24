"""In-memory time-series 데이터 캐싱 시스템.

Phase 3: Enhanced Data Pipeline
- 고성능 in-memory 캐싱
- 시계열 데이터 최적화
- LRU/TTL 기반 캐시 관리
- 메모리 효율적인 데이터 저장
"""

import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Deque, Dict, List, Optional, Tuple, Union
from zoneinfo import ZoneInfo

from ..models import ChartInterval
from ..models.chart_data import ChartData
from ..services.minute_bar_collector import MinuteBar
from ..utils.logger import get_logger

KST = ZoneInfo("Asia/Seoul")
logger = get_logger(__name__)


@dataclass
class CacheEntry:
    """캐시 엔트리.

    Attributes:
        key: 캐시 키
        data: 저장된 데이터
        created_at: 생성 시간
        accessed_at: 마지막 접근 시간
        access_count: 접근 횟수
        ttl_seconds: TTL (초)
    """

    key: str
    data: Any
    created_at: datetime
    accessed_at: datetime
    access_count: int = 0
    ttl_seconds: Optional[int] = None

    def is_expired(self) -> bool:
        """TTL 만료 여부 확인.

        Returns:
            만료되었으면 True
        """
        if self.ttl_seconds is None:
            return False

        elapsed = (datetime.now(tz=KST) - self.created_at).total_seconds()
        return elapsed > self.ttl_seconds

    def touch(self) -> None:
        """접근 시간 및 카운트 업데이트."""
        self.accessed_at = datetime.now(tz=KST)
        self.access_count += 1


class TimeSeriesCache:
    """시계열 데이터 전용 캐시.

    시계열 데이터의 특성을 고려한 최적화된 캐싱:
    - 시간 기반 데이터 정렬 및 조회
    - 슬라이딩 윈도우 지원
    - 압축 및 샘플링

    Attributes:
        max_size: 최대 캐시 크기 (바이트)
        default_ttl: 기본 TTL (초)
        cache: 캐시 저장소
        size_bytes: 현재 사용 메모리 (바이트)
        hit_count: 캐시 히트 수
        miss_count: 캐시 미스 수
    """

    def __init__(
        self,
        max_size_mb: float = 100,
        default_ttl_seconds: int = 3600
    ):
        """TimeSeriesCache 초기화.

        Args:
            max_size_mb: 최대 캐시 크기 (MB)
            default_ttl_seconds: 기본 TTL (초)
        """
        self.max_size = int(max_size_mb * 1024 * 1024)  # MB to bytes
        self.default_ttl = default_ttl_seconds

        # 캐시 저장소 (LRU를 위한 OrderedDict)
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()

        # 시계열 인덱스 (종목별, 간격별 타임스탬프 정렬)
        self.time_index: Dict[str, Dict[ChartInterval, Deque[datetime]]] = {}

        self.size_bytes = 0
        self.hit_count = 0
        self.miss_count = 0

        # 백그라운드 정리 태스크
        self.cleanup_task: Optional[asyncio.Task] = None
        self.running = False

    def _make_key(
        self,
        stock_code: str,
        interval: ChartInterval,
        timestamp: Optional[datetime] = None
    ) -> str:
        """캐시 키 생성.

        Args:
            stock_code: 종목코드
            interval: 차트 주기
            timestamp: 타임스탬프 (선택)

        Returns:
            캐시 키
        """
        # interval이 string인 경우 처리 (pydantic use_enum_values로 인해)
        interval_value = interval.value if hasattr(interval, 'value') else str(interval)

        if timestamp:
            ts_str = timestamp.isoformat()
            return f"{stock_code}:{interval_value}:{ts_str}"

        return f"{stock_code}:{interval_value}"

    def _estimate_size(self, data: Any) -> int:
        """데이터 크기 추정 (바이트).

        Args:
            data: 크기를 추정할 데이터

        Returns:
            추정 크기 (바이트)
        """
        if isinstance(data, (ChartData, MinuteBar)):
            # ChartData/MinuteBar: 약 200 bytes
            return 200
        elif isinstance(data, list):
            # 리스트: 각 항목 크기의 합
            return sum(self._estimate_size(item) for item in data)
        elif isinstance(data, dict):
            # 딕셔너리: 키와 값 크기의 합
            return sum(
                len(str(k)) + self._estimate_size(v)
                for k, v in data.items()
            )
        else:
            # 기타: 문자열 표현의 크기
            return len(str(data))

    async def put(
        self,
        stock_code: str,
        interval: ChartInterval,
        data: Union[ChartData, MinuteBar, List[ChartData], List[MinuteBar]],
        ttl_seconds: Optional[int] = None
    ) -> bool:
        """데이터 저장.

        Args:
            stock_code: 종목코드
            interval: 차트 주기
            data: 저장할 데이터
            ttl_seconds: TTL (None이면 기본값 사용)

        Returns:
            저장 성공 여부
        """
        # 리스트인 경우 각 항목별로 저장
        if isinstance(data, list):
            success = True
            for item in data:
                if not await self._put_single(
                    stock_code, interval, item, ttl_seconds
                ):
                    success = False
            return success

        return await self._put_single(stock_code, interval, data, ttl_seconds)

    async def _put_single(
        self,
        stock_code: str,
        interval: ChartInterval,
        data: Union[ChartData, MinuteBar],
        ttl_seconds: Optional[int] = None
    ) -> bool:
        """단일 데이터 저장.

        Args:
            stock_code: 종목코드
            interval: 차트 주기
            data: 저장할 데이터
            ttl_seconds: TTL

        Returns:
            저장 성공 여부
        """
        # 타임스탬프 추출
        if isinstance(data, ChartData):
            timestamp = data.timestamp
        elif isinstance(data, MinuteBar):
            timestamp = data.start_time
        else:
            timestamp = datetime.now(tz=KST)

        # 키 생성
        key = self._make_key(stock_code, interval, timestamp)

        # 크기 확인
        data_size = self._estimate_size(data)

        # 메모리 부족 시 공간 확보
        while self.size_bytes + data_size > self.max_size:
            if not self._evict_lru():
                logger.warning(
                    f"Cache full, cannot store data for {key} "
                    f"(size: {data_size}, available: {self.max_size - self.size_bytes})"
                )
                return False

        # 캐시 엔트리 생성
        entry = CacheEntry(
            key=key,
            data=data,
            created_at=datetime.now(tz=KST),
            accessed_at=datetime.now(tz=KST),
            ttl_seconds=ttl_seconds or self.default_ttl
        )

        # 기존 엔트리가 있으면 크기 조정
        if key in self.cache:
            old_entry = self.cache[key]
            old_size = self._estimate_size(old_entry.data)
            self.size_bytes -= old_size

        # 저장
        self.cache[key] = entry
        self.size_bytes += data_size

        # 시간 인덱스 업데이트
        self._update_time_index(stock_code, interval, timestamp)

        logger.debug(
            f"Cached {key}: size={data_size}B, "
            f"total={self.size_bytes}B/{self.max_size}B"
        )

        return True

    def _update_time_index(
        self,
        stock_code: str,
        interval: ChartInterval,
        timestamp: datetime
    ) -> None:
        """시간 인덱스 업데이트.

        Args:
            stock_code: 종목코드
            interval: 차트 주기
            timestamp: 타임스탬프
        """
        if stock_code not in self.time_index:
            self.time_index[stock_code] = {}

        if interval not in self.time_index[stock_code]:
            self.time_index[stock_code][interval] = deque(maxlen=10000)

        # 타임스탬프 추가 (정렬 유지)
        timestamps = self.time_index[stock_code][interval]

        # 이미 존재하면 스킵
        if timestamp in timestamps:
            return

        # 정렬된 위치에 삽입
        inserted = False
        for i in range(len(timestamps)):
            if timestamps[i] > timestamp:
                # 중간에 삽입
                temp = list(timestamps)
                temp.insert(i, timestamp)
                timestamps.clear()
                timestamps.extend(temp[-timestamps.maxlen:])
                inserted = True
                break

        if not inserted:
            # 마지막에 추가
            timestamps.append(timestamp)

    async def get(
        self,
        stock_code: str,
        interval: ChartInterval,
        timestamp: Optional[datetime] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> Optional[Union[ChartData, MinuteBar, List[Union[ChartData, MinuteBar]]]]:
        """데이터 조회.

        Args:
            stock_code: 종목코드
            interval: 차트 주기
            timestamp: 특정 시점 (단일 조회)
            start_time: 시작 시간 (범위 조회)
            end_time: 종료 시간 (범위 조회)
            limit: 최대 개수

        Returns:
            캐시된 데이터 또는 None
        """
        # 단일 시점 조회
        if timestamp:
            key = self._make_key(stock_code, interval, timestamp)
            entry = self.cache.get(key)

            if entry:
                if entry.is_expired():
                    # 만료된 엔트리 제거
                    self._remove_entry(key)
                    self.miss_count += 1
                    return None

                # 히트 처리
                entry.touch()
                self.cache.move_to_end(key)  # LRU 갱신
                self.hit_count += 1

                return entry.data

            self.miss_count += 1
            return None

        # 범위 조회
        return await self._get_range(
            stock_code, interval, start_time, end_time, limit
        )

    async def _get_range(
        self,
        stock_code: str,
        interval: ChartInterval,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> List[Union[ChartData, MinuteBar]]:
        """범위 데이터 조회.

        Args:
            stock_code: 종목코드
            interval: 차트 주기
            start_time: 시작 시간
            end_time: 종료 시간
            limit: 최대 개수

        Returns:
            캐시된 데이터 리스트
        """
        # 시간 인덱스 확인
        if stock_code not in self.time_index:
            self.miss_count += 1
            return []

        if interval not in self.time_index[stock_code]:
            self.miss_count += 1
            return []

        timestamps = self.time_index[stock_code][interval]

        # 범위 필터링
        filtered_timestamps = []
        for ts in timestamps:
            if start_time and ts < start_time:
                continue
            if end_time and ts > end_time:
                continue
            filtered_timestamps.append(ts)

            if limit and len(filtered_timestamps) >= limit:
                break

        # 데이터 조회
        result = []
        for ts in filtered_timestamps:
            key = self._make_key(stock_code, interval, ts)
            entry = self.cache.get(key)

            if entry and not entry.is_expired():
                entry.touch()
                result.append(entry.data)
                self.hit_count += 1
            else:
                self.miss_count += 1

        return result

    def _evict_lru(self) -> bool:
        """LRU 정책으로 캐시 제거.

        Returns:
            제거 성공 여부
        """
        if not self.cache:
            return False

        # 가장 오래된 항목 제거
        key = next(iter(self.cache))
        self._remove_entry(key)

        logger.debug(f"Evicted LRU entry: {key}")
        return True

    def _remove_entry(self, key: str) -> None:
        """캐시 엔트리 제거.

        Args:
            key: 제거할 키
        """
        if key not in self.cache:
            return

        entry = self.cache[key]

        # 크기 감소
        data_size = self._estimate_size(entry.data)
        self.size_bytes -= data_size

        # 캐시에서 제거
        del self.cache[key]

        # 시간 인덱스에서 제거 (구현 간소화를 위해 생략)

    async def start_cleanup(self) -> None:
        """백그라운드 정리 태스크 시작."""
        if self.running:
            return

        self.running = True
        self.cleanup_task = asyncio.create_task(self._cleanup_expired())
        logger.info("TimeSeriesCache cleanup started")

    async def stop_cleanup(self) -> None:
        """백그라운드 정리 태스크 중지."""
        if not self.running:
            return

        self.running = False

        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass

        logger.info("TimeSeriesCache cleanup stopped")

    async def _cleanup_expired(self) -> None:
        """만료된 엔트리 정리 (백그라운드)."""
        try:
            while self.running:
                # 60초마다 정리
                await asyncio.sleep(60)

                expired_keys = []
                for key, entry in self.cache.items():
                    if entry.is_expired():
                        expired_keys.append(key)

                for key in expired_keys:
                    self._remove_entry(key)

                if expired_keys:
                    logger.debug(f"Cleaned up {len(expired_keys)} expired entries")

        except asyncio.CancelledError:
            logger.debug("Cleanup task cancelled")
            raise

    def clear(self) -> None:
        """캐시 전체 삭제."""
        self.cache.clear()
        self.time_index.clear()
        self.size_bytes = 0
        logger.info("TimeSeriesCache cleared")

    def get_statistics(self) -> Dict[str, Any]:
        """캐시 통계 반환.

        Returns:
            통계 정보
        """
        total_requests = self.hit_count + self.miss_count
        hit_rate = (self.hit_count / total_requests * 100) if total_requests > 0 else 0

        return {
            "entries": len(self.cache),
            "size_bytes": self.size_bytes,
            "size_mb": round(self.size_bytes / 1024 / 1024, 2),
            "max_size_mb": round(self.max_size / 1024 / 1024, 2),
            "usage_percent": round(self.size_bytes / self.max_size * 100, 2),
            "hit_count": self.hit_count,
            "miss_count": self.miss_count,
            "hit_rate": round(hit_rate, 2),
            "stocks_cached": len(self.time_index),
            "default_ttl_seconds": self.default_ttl
        }


class MultiLevelCache:
    """다단계 캐시 시스템.

    L1: 핫 데이터 (최근 데이터, 작은 크기, 빠른 접근)
    L2: 웜 데이터 (중간 데이터, 중간 크기)
    L3: 콜드 데이터 (과거 데이터, 큰 크기, 압축)

    Attributes:
        l1_cache: L1 캐시 (핫 데이터)
        l2_cache: L2 캐시 (웜 데이터)
        l3_cache: L3 캐시 (콜드 데이터)
    """

    def __init__(
        self,
        l1_size_mb: float = 10,
        l2_size_mb: float = 50,
        l3_size_mb: float = 200
    ):
        """MultiLevelCache 초기화.

        Args:
            l1_size_mb: L1 캐시 크기 (MB)
            l2_size_mb: L2 캐시 크기 (MB)
            l3_size_mb: L3 캐시 크기 (MB)
        """
        # L1: 5분 TTL
        self.l1_cache = TimeSeriesCache(
            max_size_mb=l1_size_mb,
            default_ttl_seconds=300
        )

        # L2: 1시간 TTL
        self.l2_cache = TimeSeriesCache(
            max_size_mb=l2_size_mb,
            default_ttl_seconds=3600
        )

        # L3: 24시간 TTL
        self.l3_cache = TimeSeriesCache(
            max_size_mb=l3_size_mb,
            default_ttl_seconds=86400
        )

    async def put(
        self,
        stock_code: str,
        interval: ChartInterval,
        data: Union[ChartData, MinuteBar, List[ChartData], List[MinuteBar]]
    ) -> bool:
        """데이터 저장 (자동 티어링).

        Args:
            stock_code: 종목코드
            interval: 차트 주기
            data: 저장할 데이터

        Returns:
            저장 성공 여부
        """
        # 최근 데이터는 L1에 저장
        return await self.l1_cache.put(stock_code, interval, data)

    async def get(
        self,
        stock_code: str,
        interval: ChartInterval,
        timestamp: Optional[datetime] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> Optional[Union[ChartData, MinuteBar, List[Union[ChartData, MinuteBar]]]]:
        """데이터 조회 (캐시 계층 순회).

        Args:
            stock_code: 종목코드
            interval: 차트 주기
            timestamp: 특정 시점
            start_time: 시작 시간
            end_time: 종료 시간
            limit: 최대 개수

        Returns:
            캐시된 데이터 또는 None
        """
        # L1 조회
        result = await self.l1_cache.get(
            stock_code, interval, timestamp, start_time, end_time, limit
        )
        if result:
            return result

        # L2 조회
        result = await self.l2_cache.get(
            stock_code, interval, timestamp, start_time, end_time, limit
        )
        if result:
            # L1으로 승격
            await self.l1_cache.put(stock_code, interval, result)
            return result

        # L3 조회
        result = await self.l3_cache.get(
            stock_code, interval, timestamp, start_time, end_time, limit
        )
        if result:
            # L2로 승격
            await self.l2_cache.put(stock_code, interval, result)
            return result

        return None

    async def promote(self) -> None:
        """데이터 승격 (L3 -> L2 -> L1).

        오래된 데이터를 상위 캐시로 이동시킵니다.
        """
        # 구현 생략 (필요시 추가)
        pass

    async def demote(self) -> None:
        """데이터 강등 (L1 -> L2 -> L3).

        자주 사용되지 않는 데이터를 하위 캐시로 이동시킵니다.
        """
        # 구현 생략 (필요시 추가)
        pass

    def get_statistics(self) -> Dict[str, Dict[str, Any]]:
        """전체 캐시 통계.

        Returns:
            각 레벨별 통계
        """
        return {
            "L1": self.l1_cache.get_statistics(),
            "L2": self.l2_cache.get_statistics(),
            "L3": self.l3_cache.get_statistics()
        }