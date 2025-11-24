"""Rate Limiter 구현.

중앙화된 API Rate Limit 관리
"""

import time
import asyncio
from typing import Dict, Optional
from dataclasses import dataclass
from collections import defaultdict
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Rate Limit 설정."""

    requests_per_second: float = 10.0  # 초당 요청 수
    requests_per_minute: int = 500     # 분당 요청 수
    requests_per_hour: int = 20000     # 시간당 요청 수
    burst_size: int = 20               # 버스트 허용 크기


class TokenBucket:
    """Token Bucket 알고리즘 구현."""

    def __init__(self, rate: float, capacity: int):
        self.rate = rate  # 초당 토큰 보충률
        self.capacity = capacity  # 버킷 최대 용량
        self.tokens = capacity
        self.last_update = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> bool:
        """토큰 획득 시도."""
        async with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_update

            # 시간 경과에 따른 토큰 보충
            self.tokens = min(
                self.capacity,
                self.tokens + elapsed * self.rate
            )
            self.last_update = now

            # 토큰 사용 가능 여부 확인
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    async def wait_for_token(self, tokens: int = 1) -> None:
        """토큰이 사용 가능할 때까지 대기."""
        while not await self.acquire(tokens):
            # 다음 토큰까지 필요한 시간 계산
            wait_time = (tokens - self.tokens) / self.rate
            await asyncio.sleep(min(wait_time, 0.1))


class RateLimiter:
    """중앙화된 Rate Limiter."""

    def __init__(self, config: Optional[RateLimitConfig] = None):
        self.config = config or RateLimitConfig()

        # 다중 레벨 Rate Limit
        self.second_bucket = TokenBucket(
            rate=self.config.requests_per_second,
            capacity=int(self.config.requests_per_second * 2)
        )

        self.minute_bucket = TokenBucket(
            rate=self.config.requests_per_minute / 60,
            capacity=self.config.requests_per_minute
        )

        self.hour_bucket = TokenBucket(
            rate=self.config.requests_per_hour / 3600,
            capacity=self.config.requests_per_hour
        )

        # API별 Rate Limit 추적
        self.api_limits: Dict[str, TokenBucket] = {}

        # 통계 정보
        self.stats = defaultdict(lambda: {
            "total_requests": 0,
            "blocked_requests": 0,
            "last_request": None,
            "average_wait_time": 0.0,
        })

        self.lock = asyncio.Lock()

    async def acquire(self, api_key: str = "default", priority: int = 0) -> bool:
        """Rate Limit 확인 및 토큰 획득."""
        # API별 개별 제한이 있는 경우, 해당 제한만 확인
        if api_key in self.api_limits:
            if not await self.api_limits[api_key].acquire():
                self.stats[api_key]["blocked_requests"] += 1
                return False
        else:
            # API별 제한이 없는 경우에만 글로벌 제한 적용
            can_proceed = (
                await self.second_bucket.acquire() and
                await self.minute_bucket.acquire() and
                await self.hour_bucket.acquire()
            )

            if not can_proceed:
                self.stats[api_key]["blocked_requests"] += 1
                return False

        # 통계 업데이트
        self.stats[api_key]["total_requests"] += 1
        self.stats[api_key]["last_request"] = datetime.now()

        return True

    async def wait_and_acquire(
        self,
        api_key: str = "default",
        timeout: float = 30.0
    ) -> bool:
        """토큰이 사용 가능할 때까지 대기 후 획득."""
        start_time = time.monotonic()

        while time.monotonic() - start_time < timeout:
            if await self.acquire(api_key):
                wait_time = time.monotonic() - start_time

                # 평균 대기 시간 업데이트
                stats = self.stats[api_key]
                if stats["average_wait_time"] == 0:
                    stats["average_wait_time"] = wait_time
                else:
                    stats["average_wait_time"] = (
                        stats["average_wait_time"] * 0.9 + wait_time * 0.1
                    )

                return True

            await asyncio.sleep(0.1)

        logger.warning(f"Rate limit timeout for API: {api_key}")
        return False

    def register_api(
        self,
        api_key: str,
        requests_per_second: float,
        burst_size: Optional[int] = None
    ) -> None:
        """특정 API에 대한 Rate Limit 등록."""
        burst = burst_size or int(requests_per_second * 2)
        self.api_limits[api_key] = TokenBucket(
            rate=requests_per_second,
            capacity=burst
        )
        logger.info(
            f"Registered API '{api_key}' with "
            f"{requests_per_second} req/s, burst: {burst}"
        )

    def get_stats(self, api_key: Optional[str] = None) -> Dict:
        """통계 정보 반환."""
        if api_key:
            return dict(self.stats.get(api_key, {}))
        return {k: dict(v) for k, v in self.stats.items()}

    async def reset_limits(self, api_key: Optional[str] = None) -> None:
        """Rate Limit 초기화."""
        async with self.lock:
            if api_key and api_key in self.api_limits:
                # 특정 API 초기화
                bucket = self.api_limits[api_key]
                bucket.tokens = bucket.capacity
                bucket.last_update = time.monotonic()
            else:
                # 전체 초기화
                for bucket in [
                    self.second_bucket,
                    self.minute_bucket,
                    self.hour_bucket
                ]:
                    bucket.tokens = bucket.capacity
                    bucket.last_update = time.monotonic()

                for bucket in self.api_limits.values():
                    bucket.tokens = bucket.capacity
                    bucket.last_update = time.monotonic()

            logger.info(f"Reset rate limits for: {api_key or 'all'}")

    def get_remaining_capacity(self) -> Dict[str, float]:
        """현재 남은 용량 확인."""
        return {
            "second": self.second_bucket.tokens,
            "minute": self.minute_bucket.tokens,
            "hour": self.hour_bucket.tokens,
            "apis": {
                api: bucket.tokens
                for api, bucket in self.api_limits.items()
            }
        }