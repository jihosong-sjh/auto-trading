"""TimeSeriesCache 단위 테스트."""

import asyncio
import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.models import ChartInterval
from src.models.chart_data import ChartData
from src.services.minute_bar_collector import MinuteBar
from src.services.timeseries_cache import (
    CacheEntry,
    MultiLevelCache,
    TimeSeriesCache,
)

KST = ZoneInfo("Asia/Seoul")


class TestCacheEntry:
    """CacheEntry 테스트."""

    def test_cache_entry_creation(self):
        """CacheEntry 생성 테스트."""
        now = datetime.now(tz=KST)
        entry = CacheEntry(
            key="test_key",
            data={"value": 123},
            created_at=now,
            accessed_at=now,
            access_count=0,
            ttl_seconds=60
        )

        assert entry.key == "test_key"
        assert entry.data == {"value": 123}
        assert entry.ttl_seconds == 60
        assert entry.access_count == 0

    def test_cache_entry_expiration(self):
        """만료 확인 테스트."""
        # 만료되지 않은 엔트리
        now = datetime.now(tz=KST)
        entry = CacheEntry(
            key="test_key",
            data="data",
            created_at=now,
            accessed_at=now,
            ttl_seconds=60
        )
        assert not entry.is_expired()

        # 만료된 엔트리
        old_time = now - timedelta(seconds=120)
        expired_entry = CacheEntry(
            key="test_key",
            data="data",
            created_at=old_time,
            accessed_at=old_time,
            ttl_seconds=60
        )
        assert expired_entry.is_expired()

        # TTL이 없는 엔트리
        no_ttl_entry = CacheEntry(
            key="test_key",
            data="data",
            created_at=old_time,
            accessed_at=old_time,
            ttl_seconds=None
        )
        assert not no_ttl_entry.is_expired()

    def test_cache_entry_touch(self):
        """접근 업데이트 테스트."""
        now = datetime.now(tz=KST)
        entry = CacheEntry(
            key="test_key",
            data="data",
            created_at=now,
            accessed_at=now,
            access_count=0
        )

        # Touch
        entry.touch()
        assert entry.access_count == 1
        assert entry.accessed_at > now

        # 다시 Touch
        entry.touch()
        assert entry.access_count == 2


class TestTimeSeriesCache:
    """TimeSeriesCache 테스트."""

    @pytest.mark.asyncio
    async def test_cache_initialization(self):
        """캐시 초기화 테스트."""
        cache = TimeSeriesCache(max_size_mb=10, default_ttl_seconds=300)

        assert cache.max_size == 10 * 1024 * 1024
        assert cache.default_ttl == 300
        assert cache.size_bytes == 0
        assert cache.hit_count == 0
        assert cache.miss_count == 0

    @pytest.mark.asyncio
    async def test_put_and_get_single(self):
        """단일 데이터 저장/조회 테스트."""
        cache = TimeSeriesCache()

        # ChartData 저장
        now = datetime.now(tz=KST)
        chart_data = ChartData(
            stock_code="005930",
            interval=ChartInterval.MINUTE_1,
            timestamp=now,
            open_price=Decimal("70000"),
            high_price=Decimal("70100"),
            low_price=Decimal("69900"),
            close_price=Decimal("70050"),
            volume=1000
        )

        # 저장
        success = await cache.put("005930", ChartInterval.MINUTE_1, chart_data)
        assert success
        assert cache.size_bytes > 0

        # 조회
        retrieved = await cache.get("005930", ChartInterval.MINUTE_1, timestamp=now)
        assert retrieved is not None
        assert retrieved.stock_code == "005930"
        assert retrieved.close_price == Decimal("70050")
        assert cache.hit_count == 1

        # 없는 데이터 조회
        missing = await cache.get("005930", ChartInterval.MINUTE_1,
                                 timestamp=now + timedelta(hours=1))
        assert missing is None
        assert cache.miss_count == 1

    @pytest.mark.asyncio
    async def test_put_and_get_list(self):
        """리스트 데이터 저장/조회 테스트."""
        cache = TimeSeriesCache()

        # 여러 개의 ChartData
        now = datetime.now(tz=KST)
        data_list = []
        for i in range(5):
            data = ChartData(
                stock_code="005930",
                interval=ChartInterval.MINUTE_1,
                timestamp=now + timedelta(minutes=i),
                open_price=Decimal("70000"),
                high_price=Decimal("70100"),
                low_price=Decimal("69900"),
                close_price=Decimal(f"{70000 + i * 10}"),
                volume=1000
            )
            data_list.append(data)

        # 리스트 저장
        success = await cache.put("005930", ChartInterval.MINUTE_1, data_list)
        assert success

        # 범위 조회
        retrieved_list = await cache.get(
            "005930",
            ChartInterval.MINUTE_1,
            start_time=now,
            end_time=now + timedelta(minutes=3)
        )
        assert len(retrieved_list) == 4  # end_time 포함

    @pytest.mark.asyncio
    async def test_range_query(self):
        """범위 조회 테스트."""
        cache = TimeSeriesCache()

        # 10개 데이터 저장
        now = datetime.now(tz=KST)
        for i in range(10):
            bar = MinuteBar(
                stock_code="005930",
                interval_minutes=1,
                start_time=now + timedelta(minutes=i),
                end_time=now + timedelta(minutes=i + 1),
                open_price=Decimal("70000"),
                high_price=Decimal("70100"),
                low_price=Decimal("69900"),
                close_price=Decimal("70050"),
                volume=100
            )
            await cache.put("005930", ChartInterval.MINUTE_1, bar)

        # 전체 조회
        all_data = await cache.get(
            "005930",
            ChartInterval.MINUTE_1,
            start_time=now,
            end_time=now + timedelta(minutes=10)
        )
        assert len(all_data) == 10

        # 부분 조회
        partial_data = await cache.get(
            "005930",
            ChartInterval.MINUTE_1,
            start_time=now + timedelta(minutes=3),
            end_time=now + timedelta(minutes=7),
        )
        assert len(partial_data) == 5  # end_time 포함

        # Limit 적용
        limited_data = await cache.get(
            "005930",
            ChartInterval.MINUTE_1,
            start_time=now,
            limit=3
        )
        assert len(limited_data) == 3

    @pytest.mark.asyncio
    async def test_lru_eviction(self):
        """LRU 제거 테스트."""
        # 아주 작은 캐시
        cache = TimeSeriesCache(max_size_mb=0.001)  # 약 1KB

        # 많은 데이터 저장 시도
        now = datetime.now(tz=KST)
        for i in range(100):
            bar = MinuteBar(
                stock_code="005930",
                interval_minutes=1,
                start_time=now + timedelta(minutes=i),
                end_time=now + timedelta(minutes=i + 1),
                open_price=Decimal("70000"),
                high_price=Decimal("70100"),
                low_price=Decimal("69900"),
                close_price=Decimal("70050"),
                volume=100
            )
            await cache.put("005930", ChartInterval.MINUTE_1, bar)

        # 캐시 크기가 제한 이하
        assert cache.size_bytes <= cache.max_size
        # 모든 데이터가 저장되지 않음
        assert len(cache.cache) < 100

    @pytest.mark.asyncio
    async def test_ttl_expiration(self):
        """TTL 만료 테스트."""
        cache = TimeSeriesCache(default_ttl_seconds=0)  # 즉시 만료

        # 데이터 저장
        now = datetime.now(tz=KST)
        chart_data = ChartData(
            stock_code="005930",
            interval=ChartInterval.MINUTE_1,
            timestamp=now,
            open_price=Decimal("70000"),
            high_price=Decimal("70100"),
            low_price=Decimal("69900"),
            close_price=Decimal("70050"),
            volume=1000
        )

        await cache.put("005930", ChartInterval.MINUTE_1, chart_data)

        # 즉시 조회 시 만료
        await asyncio.sleep(0.01)
        retrieved = await cache.get("005930", ChartInterval.MINUTE_1, timestamp=now)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_statistics(self):
        """통계 테스트."""
        cache = TimeSeriesCache()

        stats = cache.get_statistics()
        assert "entries" in stats
        assert "size_bytes" in stats
        assert "size_mb" in stats
        assert "hit_count" in stats
        assert "miss_count" in stats
        assert "hit_rate" in stats

        # 데이터 추가 후
        now = datetime.now(tz=KST)
        chart_data = ChartData(
            stock_code="005930",
            interval=ChartInterval.MINUTE_1,
            timestamp=now,
            open_price=Decimal("70000"),
            high_price=Decimal("70100"),
            low_price=Decimal("69900"),
            close_price=Decimal("70050"),
            volume=1000
        )
        await cache.put("005930", ChartInterval.MINUTE_1, chart_data)

        stats2 = cache.get_statistics()
        assert stats2["entries"] == 1
        assert stats2["stocks_cached"] == 1

    @pytest.mark.asyncio
    async def test_clear(self):
        """캐시 초기화 테스트."""
        cache = TimeSeriesCache()

        # 데이터 추가
        now = datetime.now(tz=KST)
        for i in range(5):
            chart_data = ChartData(
                stock_code="005930",
                interval=ChartInterval.MINUTE_1,
                timestamp=now + timedelta(minutes=i),
                open_price=Decimal("70000"),
                high_price=Decimal("70100"),
                low_price=Decimal("69900"),
                close_price=Decimal("70050"),
                volume=1000
            )
            await cache.put("005930", ChartInterval.MINUTE_1, chart_data)

        assert len(cache.cache) == 5
        assert cache.size_bytes > 0

        # 초기화
        cache.clear()
        assert len(cache.cache) == 0
        assert cache.size_bytes == 0
        assert len(cache.time_index) == 0


class TestMultiLevelCache:
    """MultiLevelCache 테스트."""

    @pytest.mark.asyncio
    async def test_multi_level_initialization(self):
        """다단계 캐시 초기화 테스트."""
        cache = MultiLevelCache(l1_size_mb=1, l2_size_mb=5, l3_size_mb=10)

        assert cache.l1_cache.max_size == 1 * 1024 * 1024
        assert cache.l2_cache.max_size == 5 * 1024 * 1024
        assert cache.l3_cache.max_size == 10 * 1024 * 1024

        assert cache.l1_cache.default_ttl == 300  # 5분
        assert cache.l2_cache.default_ttl == 3600  # 1시간
        assert cache.l3_cache.default_ttl == 86400  # 24시간

    @pytest.mark.asyncio
    async def test_multi_level_put_get(self):
        """다단계 저장/조회 테스트."""
        cache = MultiLevelCache()

        # 데이터 저장 (L1에 저장됨)
        now = datetime.now(tz=KST)
        chart_data = ChartData(
            stock_code="005930",
            interval=ChartInterval.MINUTE_1,
            timestamp=now,
            open_price=Decimal("70000"),
            high_price=Decimal("70100"),
            low_price=Decimal("69900"),
            close_price=Decimal("70050"),
            volume=1000
        )

        success = await cache.put("005930", ChartInterval.MINUTE_1, chart_data)
        assert success

        # L1에서 조회
        retrieved = await cache.get("005930", ChartInterval.MINUTE_1, timestamp=now)
        assert retrieved is not None
        assert cache.l1_cache.hit_count == 1

    @pytest.mark.asyncio
    async def test_multi_level_promotion(self):
        """캐시 승격 테스트."""
        cache = MultiLevelCache()

        # L2에 직접 데이터 저장
        now = datetime.now(tz=KST)
        chart_data = ChartData(
            stock_code="005930",
            interval=ChartInterval.MINUTE_1,
            timestamp=now,
            open_price=Decimal("70000"),
            high_price=Decimal("70100"),
            low_price=Decimal("69900"),
            close_price=Decimal("70050"),
            volume=1000
        )

        await cache.l2_cache.put("005930", ChartInterval.MINUTE_1, chart_data)

        # 조회 시 L1으로 승격
        retrieved = await cache.get("005930", ChartInterval.MINUTE_1, timestamp=now)
        assert retrieved is not None

        # L1에도 존재하는지 확인
        l1_data = await cache.l1_cache.get(
            "005930", ChartInterval.MINUTE_1, timestamp=now
        )
        assert l1_data is not None

    @pytest.mark.asyncio
    async def test_multi_level_statistics(self):
        """다단계 통계 테스트."""
        cache = MultiLevelCache()

        stats = cache.get_statistics()
        assert "L1" in stats
        assert "L2" in stats
        assert "L3" in stats

        assert "entries" in stats["L1"]
        assert "size_mb" in stats["L1"]