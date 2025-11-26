"""RedisStreamManager 단위 테스트.

Phase 3: Queue Overflow 해결을 위한 Redis Streams 검증
- XADD로 메시지 추가
- XREAD로 메시지 읽기
- Conflation (종목별 최신 데이터)
- 시간 기반 트리밍
"""

import asyncio
import pytest
import time
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from src.cache.redis_stream_manager import RedisStreamManager
from src.models.stock import Stock

KST = ZoneInfo("Asia/Seoul")


class FakeRedisClient:
    """테스트용 가짜 Redis 클라이언트."""

    def __init__(self):
        self._streams = {}  # {stream_key: [(msg_id, fields), ...]}
        self._msg_counter = 0

    async def xadd(self, stream_key, fields, maxlen=None, approximate=True):
        """XADD 시뮬레이션."""
        if stream_key not in self._streams:
            self._streams[stream_key] = []

        # 메시지 ID 생성 (타임스탬프 기반)
        self._msg_counter += 1
        msg_id = f"{int(time.time() * 1000)}-{self._msg_counter}"

        self._streams[stream_key].append((msg_id, fields))

        # maxlen 적용
        if maxlen and len(self._streams[stream_key]) > maxlen:
            self._streams[stream_key] = self._streams[stream_key][-maxlen:]

        return msg_id.encode()

    async def xread(self, streams_dict, count=None, block=None):
        """XREAD 시뮬레이션."""
        result = []

        for stream_key, last_id in streams_dict.items():
            if stream_key not in self._streams:
                continue

            messages = []
            for msg_id, fields in self._streams[stream_key]:
                # last_id 이후의 메시지만
                if last_id == "0" or msg_id > last_id:
                    # bytes로 변환
                    encoded_fields = {
                        k.encode() if isinstance(k, str) else k:
                        v.encode() if isinstance(v, str) else v
                        for k, v in fields.items()
                    }
                    messages.append((msg_id.encode(), encoded_fields))

            if messages:
                if count:
                    messages = messages[:count]
                result.append((stream_key.encode(), messages))

        return result if result else None

    async def xtrim(self, stream_key, minid=None, maxlen=None):
        """XTRIM 시뮬레이션."""
        if stream_key not in self._streams:
            return 0

        original_len = len(self._streams[stream_key])

        if minid:
            # minid 이전 메시지 삭제
            self._streams[stream_key] = [
                (mid, fields) for mid, fields in self._streams[stream_key]
                if mid >= minid
            ]

        if maxlen:
            self._streams[stream_key] = self._streams[stream_key][-maxlen:]

        return original_len - len(self._streams[stream_key])

    async def xinfo_stream(self, stream_key):
        """XINFO STREAM 시뮬레이션."""
        from redis.exceptions import RedisError
        if stream_key not in self._streams:
            raise RedisError("Stream not found")

        stream = self._streams[stream_key]
        return {
            "length": len(stream),
            "first-entry": stream[0] if stream else None,
            "last-entry": stream[-1] if stream else None,
        }


class FakeRedisManager:
    """테스트용 가짜 RedisManager."""

    def __init__(self):
        self.client = FakeRedisClient()


@pytest.fixture
def redis_manager():
    """테스트용 RedisManager."""
    return FakeRedisManager()


@pytest.fixture
def stream_manager(redis_manager):
    """테스트용 RedisStreamManager."""
    return RedisStreamManager(
        redis_manager=redis_manager,
        stream_prefix="test:",
        max_len=1000,
        retention_hours=1,
    )


@pytest.mark.asyncio
async def test_xadd_returns_message_id(stream_manager):
    """XADD가 메시지 ID를 반환해야 함."""
    # When: 메시지 추가
    msg_id = await stream_manager.xadd(
        "market_data",
        {
            "stock_code": "005930",
            "current_price": "70000",
            "volume": 1000,
        }
    )

    # Then: 메시지 ID 반환
    assert msg_id is not None
    assert "-" in msg_id  # 타임스탬프-시퀀스 형식
    assert stream_manager._stats["xadd_count"] == 1


@pytest.mark.asyncio
async def test_xadd_multiple_messages(stream_manager, redis_manager):
    """여러 메시지가 순서대로 추가되어야 함."""
    # When: 여러 메시지 추가
    msg_ids = []
    for i in range(5):
        msg_id = await stream_manager.xadd(
            "market_data",
            {
                "stock_code": "005930",
                "current_price": str(70000 + i * 100),
            }
        )
        msg_ids.append(msg_id)

    # Then: 5개 메시지 추가됨
    stream_key = "test:market_data"
    assert len(redis_manager.client._streams[stream_key]) == 5
    assert stream_manager._stats["xadd_count"] == 5

    # 메시지 ID가 순차적
    for i in range(1, len(msg_ids)):
        assert msg_ids[i] > msg_ids[i-1]


@pytest.mark.asyncio
async def test_xread_latest_returns_new_messages(stream_manager):
    """XREAD가 마지막 읽은 위치 이후의 메시지를 반환해야 함."""
    # Given: 여러 메시지 추가
    for i in range(3):
        await stream_manager.xadd(
            "market_data",
            {
                "stock_code": "005930",
                "current_price": str(70000 + i * 100),
            }
        )

    # When: 처음 읽기 (모든 메시지)
    messages = await stream_manager.xread_latest("market_data", count=10)

    # Then: 3개 메시지 반환
    assert len(messages) == 3
    assert stream_manager._stats["xread_count"] == 1

    # When: 추가 메시지 없이 다시 읽기
    messages2 = await stream_manager.xread_latest("market_data", count=10)

    # Then: 빈 리스트 (새 메시지 없음)
    assert len(messages2) == 0


@pytest.mark.asyncio
async def test_get_latest_by_stock_returns_newest(stream_manager):
    """Conflation: 종목별 최신 데이터만 반환해야 함."""
    # Given: 같은 종목의 여러 데이터 추가
    for price in [70000, 70100, 70200]:
        await stream_manager.xadd(
            "market_data",
            {
                "stock_code": "005930",
                "stock_name": "Samsung",
                "market": "KOSPI",
                "current_price": str(price),
                "volume": 1000,
                "timestamp": datetime.now(KST).isoformat(),
            }
        )

    # 다른 종목도 추가
    await stream_manager.xadd(
        "market_data",
        {
            "stock_code": "000660",
            "stock_name": "SK Hynix",
            "market": "KOSPI",
            "current_price": "150000",
            "volume": 500,
            "timestamp": datetime.now(KST).isoformat(),
        }
    )

    # When: Conflation 적용하여 읽기
    latest = await stream_manager.get_latest_by_stock("market_data", count=100)

    # Then: 종목별 최신 데이터만 (2개)
    assert len(latest) == 2
    assert "005930" in latest
    assert "000660" in latest

    # 삼성전자는 최신 가격 (70200)
    assert latest["005930"].current_price == Decimal("70200")
    assert latest["000660"].current_price == Decimal("150000")

    assert stream_manager._stats["conflation_count"] == 1


@pytest.mark.asyncio
async def test_get_latest_by_stock_empty_stream(stream_manager):
    """빈 스트림에서 Conflation 시 빈 딕셔너리 반환."""
    # When: 빈 스트림에서 읽기
    latest = await stream_manager.get_latest_by_stock("market_data")

    # Then: 빈 딕셔너리
    assert latest == {}


@pytest.mark.asyncio
async def test_throttling_skips_recent_data(stream_manager):
    """Throttling: 100ms 이내 동일 종목 중복 처리 방지."""
    # Given: 여러 메시지 추가
    for i in range(10):
        await stream_manager.xadd(
            "market_data",
            {
                "stock_code": "005930",
                "stock_name": "Samsung",
                "market": "KOSPI",
                "current_price": str(70000 + i * 10),
                "volume": 1000,
                "timestamp": datetime.now(KST).isoformat(),
            }
        )

    # When: Conflation으로 읽기
    latest = await stream_manager.get_latest_by_stock("market_data")

    # Then: 종목별 1개만 (최신값)
    assert len(latest) == 1
    assert latest["005930"].current_price == Decimal("70090")  # 마지막 값


@pytest.mark.asyncio
async def test_trim_by_time_removes_old(stream_manager, redis_manager):
    """시간 기반 트리밍이 오래된 메시지를 삭제해야 함."""
    # Given: 메시지 추가
    stream_key = "test:market_data"
    redis_manager.client._streams[stream_key] = []

    # 오래된 메시지 (1시간 전 타임스탬프)
    old_timestamp = int((time.time() - 3700) * 1000)  # 1시간 + 100초 전
    redis_manager.client._streams[stream_key].append(
        (f"{old_timestamp}-1", {"stock_code": "005930", "price": "70000"})
    )

    # 최신 메시지
    new_timestamp = int(time.time() * 1000)
    redis_manager.client._streams[stream_key].append(
        (f"{new_timestamp}-1", {"stock_code": "005930", "price": "71000"})
    )

    # When: 1시간 기준으로 트리밍
    trimmed = await stream_manager.trim_by_time("market_data", retention_hours=1)

    # Then: 오래된 메시지 삭제
    assert trimmed == 1
    assert len(redis_manager.client._streams[stream_key]) == 1
    assert stream_manager._stats["trim_count"] == 1


@pytest.mark.asyncio
async def test_get_stream_info(stream_manager):
    """스트림 정보 조회."""
    # Given: 메시지 추가
    await stream_manager.xadd("market_data", {"stock_code": "005930"})
    await stream_manager.xadd("market_data", {"stock_code": "000660"})
    await stream_manager.xadd("market_data", {"stock_code": "035420"})

    # When: 스트림 정보 조회
    info = await stream_manager.get_stream_info("market_data")

    # Then: 올바른 정보
    assert info["length"] == 3
    assert info["first_entry"] is not None
    assert info["last_entry"] is not None


@pytest.mark.asyncio
async def test_get_stream_info_nonexistent(stream_manager):
    """존재하지 않는 스트림 정보 조회 시 기본값 반환."""
    # When: 존재하지 않는 스트림 조회
    info = await stream_manager.get_stream_info("nonexistent")

    # Then: length=0
    assert info["length"] == 0


@pytest.mark.asyncio
async def test_reset_read_position(stream_manager):
    """읽기 위치 리셋."""
    # Given: 메시지 추가 후 읽기
    await stream_manager.xadd("market_data", {"stock_code": "005930"})
    await stream_manager.xread_latest("market_data")

    # 마지막 읽은 위치 확인
    assert stream_manager._last_read_ids.get("market_data") is not None

    # When: 읽기 위치 리셋
    stream_manager.reset_read_position("market_data", "0")

    # Then: 처음부터 다시 읽을 수 있음
    assert stream_manager._last_read_ids["market_data"] == "0"

    messages = await stream_manager.xread_latest("market_data")
    assert len(messages) == 1


@pytest.mark.asyncio
async def test_get_stats(stream_manager):
    """통계 조회."""
    # Given: 여러 작업 수행
    await stream_manager.xadd("market_data", {"stock_code": "005930"})
    await stream_manager.xread_latest("market_data")

    # When: 통계 조회
    stats = stream_manager.get_stats()

    # Then: 올바른 통계
    assert stats["xadd_count"] == 1
    assert stats["xread_count"] == 1
    assert stats["stream_prefix"] == "test:"
    assert stats["max_len"] == 1000
    assert stats["retention_hours"] == 1


@pytest.mark.asyncio
async def test_xadd_with_decimal_and_datetime(stream_manager):
    """Decimal과 datetime 직렬화 테스트."""
    # When: Decimal과 datetime 포함 데이터 추가
    msg_id = await stream_manager.xadd(
        "market_data",
        {
            "stock_code": "005930",
            "current_price": Decimal("70000.50"),
            "volume": 1000,
            "timestamp": datetime.now(KST),
        }
    )

    # Then: 정상 추가
    assert msg_id is not None
    assert stream_manager._stats["xadd_count"] == 1


@pytest.mark.asyncio
async def test_maxlen_limits_stream_size(stream_manager, redis_manager):
    """MAXLEN이 스트림 크기를 제한해야 함."""
    # Given: maxlen=5로 설정
    small_stream_manager = RedisStreamManager(
        redis_manager=redis_manager,
        stream_prefix="small:",
        max_len=5,
    )

    # When: 10개 메시지 추가
    for i in range(10):
        await small_stream_manager.xadd(
            "market_data",
            {"stock_code": "005930", "price": str(i)}
        )

    # Then: 최대 5개만 유지
    stream_key = "small:market_data"
    assert len(redis_manager.client._streams[stream_key]) == 5

    # 최신 5개만 남음 (5, 6, 7, 8, 9)
    prices = [
        fields["price"]
        for _, fields in redis_manager.client._streams[stream_key]
    ]
    assert prices == ["5", "6", "7", "8", "9"]


@pytest.mark.asyncio
async def test_data_to_stock_conversion(stream_manager):
    """딕셔너리가 Stock 객체로 올바르게 변환되어야 함."""
    # Given: 완전한 데이터 추가
    timestamp = datetime.now(KST)
    await stream_manager.xadd(
        "market_data",
        {
            "stock_code": "005930",
            "stock_name": "Samsung Electronics",
            "market": "KOSPI",
            "current_price": "70000",
            "volume": 1000000,
            "timestamp": timestamp.isoformat(),
        }
    )

    # When: Conflation으로 읽기
    latest = await stream_manager.get_latest_by_stock("market_data")

    # Then: Stock 객체로 변환됨
    stock = latest["005930"]
    assert isinstance(stock, Stock)
    assert stock.stock_code == "005930"
    assert stock.stock_name == "Samsung Electronics"
    assert stock.current_price == Decimal("70000")
    assert stock.volume == 1000000


@pytest.mark.asyncio
async def test_xadd_error_handling(stream_manager, redis_manager):
    """XADD 오류 처리."""
    # Given: Redis 오류 시뮬레이션
    async def raise_error(*args, **kwargs):
        from redis.exceptions import RedisError
        raise RedisError("Connection error")

    redis_manager.client.xadd = raise_error

    # When: XADD 시도
    result = await stream_manager.xadd("market_data", {"test": "data"})

    # Then: None 반환, 오류 카운트 증가
    assert result is None
    assert stream_manager._stats["errors"] == 1
