"""AccountCache 단위 테스트.

Phase 3: Queue Overflow 해결을 위한 AccountCache 검증
- 캐시에서 계좌 정보 조회 (API 호출 없음)
- 백그라운드 동기화
- 체결 시 잔고 업데이트
- Redis 장애 시 로컬 폴백
"""

import asyncio
import pytest
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from src.cache.account_cache import AccountCache
from src.models.account import Account
from src.models.order import Order
from src.models import OrderType, OrderStatus, PriceType

KST = ZoneInfo("Asia/Seoul")


class FakeRedisManager:
    """테스트용 가짜 RedisManager."""

    def __init__(self):
        self._store = {}
        self._get_count = 0
        self._set_count = 0

    async def get(self, key: str):
        self._get_count += 1
        return self._store.get(key)

    async def set(self, key: str, value, ttl: int = None):
        self._set_count += 1
        self._store[key] = value

    async def delete(self, key: str):
        if key in self._store:
            del self._store[key]

    def reset_counts(self):
        self._get_count = 0
        self._set_count = 0


class FakeApiClient:
    """테스트용 가짜 API 클라이언트."""

    def __init__(self, account: Account):
        self.account = account
        self.call_count = 0

    async def get_account(self) -> Account:
        self.call_count += 1
        return Account(
            account_number=self.account.account_number,
            name=self.account.name,
            cash_balance=self.account.cash_balance,
            total_asset_value=self.account.total_asset_value,
            total_pnl=self.account.total_pnl,
            daily_pnl=self.account.daily_pnl,
            daily_loss_limit=self.account.daily_loss_limit,
            updated_at=datetime.now(tz=KST),
        )


@pytest.fixture
def sample_account():
    """테스트용 샘플 계좌."""
    return Account(
        account_number="12345678",
        name="Test Account",
        cash_balance=Decimal("10000000"),
        total_asset_value=Decimal("15000000"),
        total_pnl=Decimal("500000"),
        daily_pnl=Decimal("0"),
        daily_loss_limit=Decimal("750000"),
        updated_at=datetime.now(tz=KST),
    )


@pytest.fixture
def redis_manager():
    """테스트용 RedisManager."""
    return FakeRedisManager()


@pytest.fixture
def api_client(sample_account):
    """테스트용 API 클라이언트."""
    return FakeApiClient(sample_account)


@pytest.fixture
def account_cache(redis_manager):
    """테스트용 AccountCache."""
    return AccountCache(
        redis_manager=redis_manager,
        sync_interval=1,  # 테스트용 짧은 간격
        local_fallback_enabled=True,
    )


@pytest.mark.asyncio
async def test_get_cached_account_no_api_call(account_cache, redis_manager, sample_account):
    """캐시에서 계좌 정보 조회 시 API 호출이 없어야 함."""
    # Given: Redis에 계좌 정보가 캐시되어 있음
    cache_data = {
        "account_number": sample_account.account_number,
        "name": sample_account.name,
        "cash_balance": str(sample_account.cash_balance),
        "total_asset_value": str(sample_account.total_asset_value),
        "total_pnl": str(sample_account.total_pnl),
        "daily_pnl": str(sample_account.daily_pnl),
        "daily_loss_limit": str(sample_account.daily_loss_limit),
        "updated_at": sample_account.updated_at.isoformat(),
    }
    redis_manager._store[AccountCache.CACHE_KEY] = cache_data

    # When: 캐시된 계좌 정보 조회
    account = await account_cache.get_cached_account()

    # Then: API 호출 없이 캐시에서 조회됨
    assert account is not None
    assert account.account_number == sample_account.account_number
    assert account.cash_balance == sample_account.cash_balance
    assert account_cache._stats["cache_hits"] == 1
    assert account_cache._stats["cache_misses"] == 0


@pytest.mark.asyncio
async def test_get_cached_account_cache_miss(account_cache, redis_manager):
    """캐시가 없을 때 None 반환."""
    # Given: Redis에 캐시 없음

    # When: 캐시된 계좌 정보 조회
    account = await account_cache.get_cached_account()

    # Then: None 반환
    assert account is None
    assert account_cache._stats["cache_misses"] == 1


@pytest.mark.asyncio
async def test_background_sync_updates_cache(account_cache, api_client, redis_manager):
    """백그라운드 동기화가 캐시를 갱신해야 함."""
    # When: 동기화 태스크 시작 (초기 동기화 포함)
    await account_cache.start_sync_task(api_client)

    # Then: API가 호출되고 캐시가 갱신됨
    assert api_client.call_count >= 1
    assert account_cache._stats["api_calls"] >= 1
    assert account_cache._stats["sync_count"] >= 1

    # 캐시 확인
    account = await account_cache.get_cached_account()
    assert account is not None
    assert account.account_number == "12345678"

    # 정리
    await account_cache.stop_sync_task()


@pytest.mark.asyncio
async def test_sync_loop_periodically_updates(account_cache, api_client):
    """동기화 루프가 주기적으로 API를 호출해야 함."""
    # Given: 동기화 간격 1초
    account_cache.sync_interval = 1

    # When: 동기화 태스크 시작
    await account_cache.start_sync_task(api_client)

    # 초기 동기화 완료 (1회)
    initial_calls = api_client.call_count

    # 2초 대기 (추가 1-2회 동기화 예상)
    await asyncio.sleep(2.5)

    # Then: 추가 API 호출이 있어야 함
    assert api_client.call_count > initial_calls

    # 정리
    await account_cache.stop_sync_task()


@pytest.mark.asyncio
async def test_update_on_fill_adjusts_balance_buy(account_cache, redis_manager, sample_account):
    """매수 체결 시 예수금이 감소해야 함."""
    # Given: 캐시에 계좌 정보 저장
    cache_data = {
        "account_number": sample_account.account_number,
        "name": sample_account.name,
        "cash_balance": str(sample_account.cash_balance),  # 10,000,000
        "total_asset_value": str(sample_account.total_asset_value),
        "total_pnl": str(sample_account.total_pnl),
        "daily_pnl": str(sample_account.daily_pnl),
        "daily_loss_limit": str(sample_account.daily_loss_limit),
        "updated_at": sample_account.updated_at.isoformat(),
    }
    redis_manager._store[AccountCache.CACHE_KEY] = cache_data

    # 매수 주문 생성
    buy_order = Order(
        order_id="TEST001",
        account_number="12345678",
        stock_code="005930",
        order_type=OrderType.BUY,
        quantity=10,
        limit_price=Decimal("70000"),
        price_type=PriceType.LIMIT,
        status=OrderStatus.FILLED,
    )

    # When: 체결 시 잔고 업데이트
    await account_cache.update_on_fill(buy_order, filled_price=Decimal("70000"))

    # Then: 예수금이 감소 (10,000,000 - 700,000 = 9,300,000)
    account = await account_cache.get_cached_account()
    assert account.cash_balance == Decimal("9300000")
    assert account_cache._stats["fill_updates"] == 1


@pytest.mark.asyncio
async def test_update_on_fill_adjusts_balance_sell(account_cache, redis_manager, sample_account):
    """매도 체결 시 예수금이 증가해야 함."""
    # Given: 캐시에 계좌 정보 저장
    cache_data = {
        "account_number": sample_account.account_number,
        "name": sample_account.name,
        "cash_balance": str(sample_account.cash_balance),  # 10,000,000
        "total_asset_value": str(sample_account.total_asset_value),
        "total_pnl": str(sample_account.total_pnl),
        "daily_pnl": str(sample_account.daily_pnl),
        "daily_loss_limit": str(sample_account.daily_loss_limit),
        "updated_at": sample_account.updated_at.isoformat(),
    }
    redis_manager._store[AccountCache.CACHE_KEY] = cache_data

    # 매도 주문 생성
    sell_order = Order(
        order_id="TEST002",
        account_number="12345678",
        stock_code="005930",
        order_type=OrderType.SELL,
        quantity=10,
        limit_price=Decimal("75000"),
        price_type=PriceType.LIMIT,
        status=OrderStatus.FILLED,
    )

    # When: 체결 시 잔고 업데이트
    await account_cache.update_on_fill(sell_order, filled_price=Decimal("75000"))

    # Then: 예수금이 증가 (10,000,000 + 750,000 = 10,750,000)
    account = await account_cache.get_cached_account()
    assert account.cash_balance == Decimal("10750000")


@pytest.mark.asyncio
async def test_force_sync_calls_api(account_cache, api_client):
    """강제 동기화 시 API를 호출해야 함."""
    # Given: API 클라이언트 설정
    account_cache._api_client = api_client

    # When: 강제 동기화
    account = await account_cache.force_sync()

    # Then: API 호출됨
    assert api_client.call_count == 1
    assert account is not None
    assert account.account_number == "12345678"


@pytest.mark.asyncio
async def test_local_fallback_on_redis_error(account_cache, sample_account):
    """Redis 오류 시 로컬 캐시로 폴백해야 함."""
    # Given: 로컬 캐시에 데이터 저장
    account_cache._local_cache = sample_account
    account_cache._local_cache_time = 1000000

    # Redis 오류 시뮬레이션 (get에서 예외 발생)
    async def raise_error(key):
        raise Exception("Redis connection error")

    account_cache.redis.get = raise_error

    # When: 캐시 조회
    account = await account_cache.get_cached_account()

    # Then: 로컬 캐시에서 반환
    assert account is not None
    assert account.account_number == sample_account.account_number
    assert account_cache._stats["cache_hits"] == 1


@pytest.mark.asyncio
async def test_local_fallback_disabled(redis_manager, sample_account):
    """로컬 폴백 비활성화 시 None 반환."""
    # Given: 로컬 폴백 비활성화
    cache = AccountCache(
        redis_manager=redis_manager,
        sync_interval=10,
        local_fallback_enabled=False,
    )
    cache._local_cache = sample_account

    # Redis 오류 시뮬레이션
    async def raise_error(key):
        raise Exception("Redis connection error")

    cache.redis.get = raise_error

    # When: 캐시 조회
    account = await cache.get_cached_account()

    # Then: None 반환 (로컬 폴백 비활성화)
    assert account is None
    assert cache._stats["cache_misses"] == 1


@pytest.mark.asyncio
async def test_invalidate_clears_cache(account_cache, redis_manager, sample_account):
    """캐시 무효화 시 Redis와 로컬 캐시 모두 삭제."""
    # Given: 캐시에 데이터 저장
    redis_manager._store[AccountCache.CACHE_KEY] = {"test": "data"}
    redis_manager._store[AccountCache.TIMESTAMP_KEY] = "123456"
    account_cache._local_cache = sample_account
    account_cache._local_cache_time = 1000000

    # When: 캐시 무효화
    result = await account_cache.invalidate()

    # Then: 모든 캐시 삭제
    assert result is True
    assert AccountCache.CACHE_KEY not in redis_manager._store
    assert AccountCache.TIMESTAMP_KEY not in redis_manager._store
    assert account_cache._local_cache is None
    assert account_cache._local_cache_time is None


@pytest.mark.asyncio
async def test_stop_sync_task_cancels_task(account_cache, api_client):
    """동기화 태스크 중지 시 태스크가 취소되어야 함."""
    # Given: 동기화 태스크 시작
    await account_cache.start_sync_task(api_client)
    assert account_cache._running is True

    # When: 동기화 태스크 중지
    await account_cache.stop_sync_task()

    # Then: 태스크가 취소됨
    assert account_cache._running is False
    assert account_cache._sync_task is None


@pytest.mark.asyncio
async def test_get_stats_returns_correct_data(account_cache, redis_manager, sample_account):
    """통계가 올바르게 반환되어야 함."""
    # Given: 캐시에 데이터 저장
    cache_data = {
        "account_number": sample_account.account_number,
        "name": sample_account.name,
        "cash_balance": str(sample_account.cash_balance),
        "total_asset_value": str(sample_account.total_asset_value),
        "total_pnl": str(sample_account.total_pnl),
        "daily_pnl": str(sample_account.daily_pnl),
        "daily_loss_limit": str(sample_account.daily_loss_limit),
        "updated_at": sample_account.updated_at.isoformat(),
    }
    redis_manager._store[AccountCache.CACHE_KEY] = cache_data

    # 캐시 히트 생성
    await account_cache.get_cached_account()
    await account_cache.get_cached_account()

    # When: 통계 조회
    stats = account_cache.get_stats()

    # Then: 올바른 통계
    assert stats["cache_hits"] == 2
    assert stats["cache_misses"] == 0
    assert "hit_rate" in stats
    assert stats["sync_interval"] == 1
    assert stats["has_cache"] is True


@pytest.mark.asyncio
async def test_update_on_fill_no_cache_logs_warning(account_cache):
    """캐시가 없을 때 update_on_fill이 경고 로그를 남겨야 함."""
    # Given: 캐시 없음
    order = Order(
        order_id="TEST001",
        account_number="12345678",
        stock_code="005930",
        order_type=OrderType.BUY,
        quantity=10,
        limit_price=Decimal("70000"),
        price_type=PriceType.LIMIT,
        status=OrderStatus.FILLED,
    )

    # When: 체결 업데이트 시도
    await account_cache.update_on_fill(order, filled_price=Decimal("70000"))

    # Then: fill_updates 카운트 증가 안 함 (캐시가 없으므로)
    assert account_cache._stats["fill_updates"] == 0


@pytest.mark.asyncio
async def test_double_start_sync_task_returns_existing(account_cache, api_client):
    """이미 실행 중인 동기화 태스크가 있으면 기존 태스크 반환."""
    # Given: 동기화 태스크 시작
    task1 = await account_cache.start_sync_task(api_client)

    # When: 다시 시작 시도
    task2 = await account_cache.start_sync_task(api_client)

    # Then: 같은 태스크 반환
    assert task1 is task2

    # 정리
    await account_cache.stop_sync_task()
