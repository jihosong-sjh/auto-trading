"""계좌 정보 캐싱 레이어.

전략 엔진의 get_account() API 호출을 제거하여 처리 속도를 개선합니다.
백그라운드 태스크가 주기적으로 실제 API를 호출하여 캐시를 갱신합니다.
"""

import asyncio
import json
import time
from decimal import Decimal
from typing import Any, Callable, Coroutine, Optional, Protocol

from ..models.account import Account
from ..models.order import Order
from ..models import OrderType
from ..utils.logger import get_logger
from .redis_manager import RedisManager

logger = get_logger(__name__)


class AccountProviderProtocol(Protocol):
    """Account provider interface."""

    async def get_account(self) -> Account:
        """Fetch account information from API."""
        ...


class AccountCache:
    """계좌 정보 캐시 (백그라운드 동기화).

    전략 엔진 루프에서 API 호출을 완전히 제거합니다.
    백그라운드 태스크가 주기적으로 실제 API를 호출하여 캐시를 갱신합니다.

    Features:
    - Redis 기반 캐시 (프로세스 간 공유 가능)
    - 백그라운드 동기화 (configurable interval)
    - 체결 시 추정 잔고 즉시 업데이트
    - 로컬 메모리 폴백 (Redis 장애 시)

    Usage:
        ```python
        cache = AccountCache(redis_manager, sync_interval=10)
        await cache.start_sync_task(kiwoom_client)

        # 전략 루프에서 (API 호출 없음, 1ms 미만)
        account = await cache.get_cached_account()

        # 체결 시
        await cache.update_on_fill(order, filled_price)

        # 종료 시
        await cache.stop_sync_task()
        ```
    """

    # Redis 키
    CACHE_KEY = "account:cache:data"
    TIMESTAMP_KEY = "account:cache:timestamp"
    LOCK_KEY = "account:cache:sync_lock"

    def __init__(
        self,
        redis_manager: RedisManager,
        sync_interval: int = 10,
        local_fallback_enabled: bool = True,
    ):
        """AccountCache 초기화.

        Args:
            redis_manager: Redis 매니저 인스턴스.
            sync_interval: 백그라운드 동기화 간격 (초). 기본값 10초.
            local_fallback_enabled: Redis 장애 시 로컬 캐시 사용 여부.
        """
        self.redis = redis_manager
        self.sync_interval = sync_interval
        self.local_fallback_enabled = local_fallback_enabled

        # 로컬 메모리 캐시 (폴백용)
        self._local_cache: Optional[Account] = None
        self._local_cache_time: Optional[float] = None

        # 백그라운드 태스크
        self._sync_task: Optional[asyncio.Task] = None
        self._api_client: Optional[AccountProviderProtocol] = None
        self._running = False

        # 통계
        self._stats = {
            "cache_hits": 0,
            "cache_misses": 0,
            "api_calls": 0,
            "sync_count": 0,
            "fill_updates": 0,
            "errors": 0,
        }

    async def get_cached_account(self) -> Optional[Account]:
        """캐시된 계좌 정보 조회 (API 호출 없음).

        전략 엔진에서 사용하는 핵심 메서드입니다.
        Redis 캐시 → 로컬 캐시 순으로 조회합니다.

        Returns:
            캐시된 Account 객체. 캐시가 없으면 None.

        Note:
            이 메서드는 절대 외부 API를 호출하지 않습니다.
            캐시가 없으면 start_sync_task()가 호출되었는지 확인하세요.
        """
        # 1. Redis 캐시 조회
        try:
            data = await self.redis.get(self.CACHE_KEY)
            if data:
                self._stats["cache_hits"] += 1
                account = self._deserialize_account(data)

                # 로컬 캐시도 업데이트
                self._local_cache = account
                self._local_cache_time = time.time()

                return account
        except Exception as e:
            logger.warning(f"Redis cache read failed: {e}")
            self._stats["errors"] += 1

        # 2. 로컬 캐시 폴백
        if self.local_fallback_enabled and self._local_cache:
            self._stats["cache_hits"] += 1
            logger.debug("Using local cache fallback")
            return self._local_cache

        # 3. 캐시 없음
        self._stats["cache_misses"] += 1
        logger.warning("No cached account available")
        return None

    async def start_sync_task(
        self,
        api_client: AccountProviderProtocol,
    ) -> asyncio.Task:
        """백그라운드 동기화 태스크 시작.

        Args:
            api_client: get_account() 메서드를 가진 API 클라이언트.

        Returns:
            시작된 asyncio.Task.
        """
        if self._running:
            logger.warning("Sync task is already running")
            return self._sync_task

        self._api_client = api_client
        self._running = True

        # 초기 동기화 (시작 시 1회)
        logger.info("Performing initial account sync...")
        await self._sync_account()

        # 백그라운드 태스크 시작
        self._sync_task = asyncio.create_task(self._sync_loop())
        logger.info(
            f"Account cache sync task started "
            f"(interval: {self.sync_interval}s)"
        )

        return self._sync_task

    async def stop_sync_task(self) -> None:
        """백그라운드 동기화 태스크 중지."""
        if not self._running:
            return

        self._running = False

        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
            self._sync_task = None

        logger.info("Account cache sync task stopped")

    async def update_on_fill(
        self,
        order: Order,
        filled_price: Decimal,
        filled_quantity: Optional[int] = None,
    ) -> None:
        """체결 시 추정 잔고 업데이트.

        실제 API 호출 없이 캐시된 잔고를 조정합니다.
        다음 sync에서 실제 값으로 보정됩니다.

        Args:
            order: 체결된 주문.
            filled_price: 체결 가격.
            filled_quantity: 체결 수량. None이면 order.quantity 사용.
        """
        account = await self.get_cached_account()
        if not account:
            logger.warning("Cannot update on fill: no cached account")
            return

        quantity = filled_quantity or order.quantity
        total_amount = filled_price * quantity

        # 잔고 조정
        order_type_value = order.order_type.value if hasattr(order.order_type, 'value') else str(order.order_type)
        if order_type_value == "BUY":
            # 매수: 예수금 감소
            new_cash = account.cash_balance - total_amount
        else:
            # 매도: 예수금 증가
            new_cash = account.cash_balance + total_amount

        # 새 Account 객체 생성 (immutable 패턴)
        updated_account = Account(
            account_number=account.account_number,
            name=account.name,
            cash_balance=max(Decimal("0"), new_cash),  # 음수 방지
            total_asset_value=account.total_asset_value,
            total_pnl=account.total_pnl,
            daily_pnl=account.daily_pnl,
            daily_loss_limit=account.daily_loss_limit,
            updated_at=account.updated_at,
        )

        # 캐시 업데이트
        await self._update_cache(updated_account)
        self._stats["fill_updates"] += 1

        order_type_str = order.order_type.value if hasattr(order.order_type, 'value') else str(order.order_type)
        logger.debug(
            f"Account cache updated on fill: "
            f"{order_type_str} {order.stock_code} "
            f"{quantity}@{filled_price} -> "
            f"cash: {account.cash_balance} -> {updated_account.cash_balance}"
        )

    async def force_sync(self) -> Optional[Account]:
        """강제 동기화.

        즉시 API를 호출하여 캐시를 갱신합니다.

        Returns:
            갱신된 Account 객체. 실패 시 None.
        """
        if not self._api_client:
            logger.error("Cannot force sync: no API client configured")
            return None

        return await self._sync_account()

    async def invalidate(self) -> bool:
        """캐시 무효화.

        Returns:
            성공 여부.
        """
        try:
            await self.redis.delete(self.CACHE_KEY)
            await self.redis.delete(self.TIMESTAMP_KEY)
            self._local_cache = None
            self._local_cache_time = None
            logger.debug("Account cache invalidated")
            return True
        except Exception as e:
            logger.error(f"Cache invalidation failed: {e}")
            return False

    def get_stats(self) -> dict:
        """캐시 통계 반환.

        Returns:
            통계 딕셔너리.
        """
        total = self._stats["cache_hits"] + self._stats["cache_misses"]
        hit_rate = (self._stats["cache_hits"] / total * 100) if total > 0 else 0

        return {
            **self._stats,
            "hit_rate": f"{hit_rate:.2f}%",
            "sync_interval": self.sync_interval,
            "running": self._running,
            "has_cache": self._local_cache is not None,
        }

    # === Private Methods ===

    async def _sync_loop(self) -> None:
        """백그라운드 동기화 루프."""
        while self._running:
            try:
                await asyncio.sleep(self.sync_interval)

                if not self._running:
                    break

                await self._sync_account()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Sync loop error: {e}")
                self._stats["errors"] += 1

    async def _sync_account(self) -> Optional[Account]:
        """계좌 정보 동기화 (실제 API 호출).

        Returns:
            갱신된 Account 객체. 실패 시 None.
        """
        if not self._api_client:
            return None

        try:
            # API 호출
            self._stats["api_calls"] += 1
            account = await self._api_client.get_account()

            # 캐시 업데이트
            await self._update_cache(account)
            self._stats["sync_count"] += 1

            logger.debug(
                f"Account synced: cash={account.cash_balance:,.0f}, "
                f"total={account.total_asset_value:,.0f}"
            )

            return account

        except Exception as e:
            logger.error(f"Account sync failed: {e}")
            self._stats["errors"] += 1
            return None

    async def _update_cache(self, account: Account) -> None:
        """캐시 업데이트.

        Args:
            account: 저장할 Account 객체.
        """
        now = time.time()

        # 로컬 캐시 업데이트
        self._local_cache = account
        self._local_cache_time = now

        # Redis 캐시 업데이트
        try:
            data = self._serialize_account(account)
            await self.redis.set(
                self.CACHE_KEY,
                data,
                ttl=self.sync_interval * 3  # sync 간격의 3배
            )
            await self.redis.set(
                self.TIMESTAMP_KEY,
                str(now),
                ttl=self.sync_interval * 3
            )
        except Exception as e:
            logger.warning(f"Redis cache write failed: {e}")

    def _serialize_account(self, account: Account) -> dict:
        """Account를 직렬화.

        Args:
            account: 직렬화할 Account 객체.

        Returns:
            딕셔너리.
        """
        return {
            "account_number": account.account_number,
            "name": account.name,
            "cash_balance": str(account.cash_balance),
            "total_asset_value": str(account.total_asset_value),
            "total_pnl": str(account.total_pnl),
            "daily_pnl": str(account.daily_pnl),
            "daily_loss_limit": str(account.daily_loss_limit),
            "updated_at": account.updated_at.isoformat(),
        }

    def _deserialize_account(self, data: dict) -> Account:
        """딕셔너리를 Account로 역직렬화.

        Args:
            data: 역직렬화할 딕셔너리.

        Returns:
            Account 객체.
        """
        from datetime import datetime
        from ..models.stock import KST

        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=KST)

        return Account(
            account_number=data["account_number"],
            name=data.get("name", ""),
            cash_balance=Decimal(data["cash_balance"]),
            total_asset_value=Decimal(data["total_asset_value"]),
            total_pnl=Decimal(data.get("total_pnl", "0")),
            daily_pnl=Decimal(data.get("daily_pnl", "0")),
            daily_loss_limit=Decimal(data.get("daily_loss_limit", "0")),
            updated_at=updated_at,
        )
