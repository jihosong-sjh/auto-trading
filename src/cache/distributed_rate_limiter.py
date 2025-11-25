"""Redis 기반 분산 Rate Limiter.

여러 프로세스/서버에서 공유하는 Rate Limiting 구현.
Sliding Window Log 알고리즘 사용.
"""

import asyncio
import time
from typing import Optional, Dict, Any
from enum import Enum

from redis.exceptions import RedisError, TimeoutError as RedisTimeoutError

from ..utils.logger import get_logger
from .redis_manager import RedisManager

logger = get_logger(__name__)


class RateLimitAlgorithm(Enum):
    """Rate Limiting 알고리즘."""
    SLIDING_WINDOW_LOG = "sliding_window_log"
    SLIDING_WINDOW_COUNTER = "sliding_window_counter"
    TOKEN_BUCKET = "token_bucket"
    LEAKY_BUCKET = "leaky_bucket"


class DistributedRateLimiter:
    """Redis 기반 분산 Rate Limiter.

    여러 프로세스/서버가 공유하는 API Rate Limiting.
    Sliding Window Log 알고리즘으로 정확한 rate limiting 보장.

    Attributes:
        redis: Redis 매니저
        max_requests: 시간 윈도우 내 최대 요청 수
        time_window: 시간 윈도우 (초)
        algorithm: Rate limiting 알고리즘
    """

    def __init__(
        self,
        redis_manager: RedisManager,
        max_requests: int = 1,
        time_window: int = 1,
        algorithm: RateLimitAlgorithm = RateLimitAlgorithm.SLIDING_WINDOW_LOG
    ):
        """DistributedRateLimiter 초기화.

        Args:
            redis_manager: Redis 매니저
            max_requests: 시간 윈도우 내 최대 요청 수 (기본: 1)
            time_window: 시간 윈도우 (초, 기본: 1)
            algorithm: Rate limiting 알고리즘
        """
        self.redis = redis_manager
        self.max_requests = max_requests
        self.time_window = time_window
        self.algorithm = algorithm

        # 키 프리픽스
        self.rate_limit_prefix = "rate_limit:"
        self.stats_prefix = "rate_limit_stats:"

        # Lua 스크립트 (원자성 보장)
        self._init_lua_scripts()

    def _init_lua_scripts(self) -> None:
        """Lua 스크립트 초기화 (원자성 보장)."""
        # Sliding Window Log 알고리즘 Lua 스크립트
        self.sliding_window_lua = """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        local window = tonumber(ARGV[2])
        local max_requests = tonumber(ARGV[3])

        -- 오래된 요청 제거
        redis.call('ZREMRANGEBYSCORE', key, 0, now - window)

        -- 현재 요청 수 확인
        local current_requests = redis.call('ZCARD', key)

        if current_requests < max_requests then
            -- 요청 허용: 현재 시간을 점수로 추가
            redis.call('ZADD', key, now, now)
            redis.call('EXPIRE', key, window + 1)
            return 1
        else
            -- 요청 거부
            return 0
        end
        """

        # Token Bucket 알고리즘 Lua 스크립트
        self.token_bucket_lua = """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        local capacity = tonumber(ARGV[2])
        local refill_rate = tonumber(ARGV[3])
        local requested_tokens = tonumber(ARGV[4] or 1)

        local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
        local tokens = tonumber(bucket[1]) or capacity
        local last_refill = tonumber(bucket[2]) or now

        -- 토큰 리필
        local time_passed = now - last_refill
        local tokens_to_add = time_passed * refill_rate
        tokens = math.min(capacity, tokens + tokens_to_add)

        if tokens >= requested_tokens then
            -- 토큰 사용
            tokens = tokens - requested_tokens
            redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
            redis.call('EXPIRE', key, 60)
            return 1
        else
            -- 토큰 부족
            redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
            redis.call('EXPIRE', key, 60)
            return 0
        end
        """

    async def acquire(
        self,
        identifier: str,
        tokens: int = 1,
        wait: bool = False,
        timeout: float = 10.0
    ) -> bool:
        """Rate limit 확인 및 요청 허가.

        Args:
            identifier: 식별자 (예: user_id, api_key, ip_address)
            tokens: 요청 토큰 수 (Token Bucket 알고리즘용)
            wait: True면 허가될 때까지 대기
            timeout: 대기 시간 제한 (초)

        Returns:
            요청 허가 시 True, 거부 시 False
        """
        if self.algorithm == RateLimitAlgorithm.SLIDING_WINDOW_LOG:
            return await self._sliding_window_acquire(identifier, wait, timeout)
        elif self.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
            return await self._token_bucket_acquire(identifier, tokens, wait, timeout)
        else:
            # 기본: Sliding Window Log
            return await self._sliding_window_acquire(identifier, wait, timeout)

    async def _sliding_window_acquire(
        self,
        identifier: str,
        wait: bool = False,
        timeout: float = 10.0
    ) -> bool:
        """Sliding Window Log 알고리즘으로 rate limit 체크.

        Args:
            identifier: 식별자
            wait: 대기 여부
            timeout: 대기 시간 제한

        Returns:
            요청 허가 시 True
        """
        key = f"{self.rate_limit_prefix}{identifier}"
        start_time = time.time()

        while True:
            try:
                # Lua 스크립트 실행 (원자성 보장)
                result = await self.redis.client.eval(
                    self.sliding_window_lua,
                    1,  # 키 개수
                    key,  # KEYS[1]
                    time.time(),  # ARGV[1]: 현재 시간
                    self.time_window,  # ARGV[2]: 시간 윈도우
                    self.max_requests  # ARGV[3]: 최대 요청 수
                )

                if result == 1:
                    # 요청 허가
                    await self._increment_stats(identifier, "allowed")
                    logger.debug(f"[RATE LIMIT] Allowed request for {identifier}")
                    return True
                elif not wait:
                    # 요청 거부 (대기하지 않음)
                    await self._increment_stats(identifier, "rejected")
                    logger.debug(f"[RATE LIMIT] Rejected request for {identifier}")
                    return False
                else:
                    # 대기 모드: 잠시 후 재시도
                    if time.time() - start_time > timeout:
                        # 타임아웃
                        await self._increment_stats(identifier, "timeout")
                        logger.warning(f"[RATE LIMIT] Timeout for {identifier}")
                        return False

                    # 다음 가능한 시간 계산
                    wait_time = await self._calculate_wait_time(identifier)
                    if wait_time > 0:
                        await asyncio.sleep(min(wait_time, 0.1))

            except asyncio.TimeoutError:
                logger.warning(f"Redis asyncio timeout for {identifier}, will retry")
                if time.time() - start_time > timeout:
                    await self._increment_stats(identifier, "timeout")
                    return False
                await asyncio.sleep(0.1)
                continue
            except (RedisError, RedisTimeoutError) as e:
                logger.warning(f"Redis error for {identifier}: {e}, will retry")
                if time.time() - start_time > timeout:
                    await self._increment_stats(identifier, "timeout")
                    return False
                await asyncio.sleep(0.1)
                continue
            except Exception as e:
                logger.error(f"Unexpected rate limit error for {identifier}: {e}")
                await self._increment_stats(identifier, "timeout")
                return False

    async def _token_bucket_acquire(
        self,
        identifier: str,
        tokens: int = 1,
        wait: bool = False,
        timeout: float = 10.0
    ) -> bool:
        """Token Bucket 알고리즘으로 rate limit 체크.

        Args:
            identifier: 식별자
            tokens: 필요한 토큰 수
            wait: 대기 여부
            timeout: 대기 시간 제한

        Returns:
            요청 허가 시 True
        """
        key = f"{self.rate_limit_prefix}{identifier}"
        start_time = time.time()

        # 리필 속도 계산 (토큰/초)
        refill_rate = self.max_requests / self.time_window

        while True:
            try:
                # Lua 스크립트 실행
                result = await self.redis.client.eval(
                    self.token_bucket_lua,
                    1,  # 키 개수
                    key,  # KEYS[1]
                    time.time(),  # ARGV[1]: 현재 시간
                    self.max_requests,  # ARGV[2]: 버킷 용량
                    refill_rate,  # ARGV[3]: 리필 속도
                    tokens  # ARGV[4]: 요청 토큰 수
                )

                if result == 1:
                    # 토큰 사용 성공
                    await self._increment_stats(identifier, "allowed")
                    return True
                elif not wait:
                    # 토큰 부족 (대기하지 않음)
                    await self._increment_stats(identifier, "rejected")
                    return False
                else:
                    # 대기 모드
                    if time.time() - start_time > timeout:
                        await self._increment_stats(identifier, "timeout")
                        return False

                    # 토큰 리필 대기
                    wait_time = tokens / refill_rate
                    await asyncio.sleep(min(wait_time, 0.1))

            except asyncio.TimeoutError:
                logger.warning(f"Redis asyncio timeout for {identifier}, will retry")
                if time.time() - start_time > timeout:
                    await self._increment_stats(identifier, "timeout")
                    return False
                await asyncio.sleep(0.1)
                continue
            except (RedisError, RedisTimeoutError) as e:
                logger.warning(f"Redis error for {identifier}: {e}, will retry")
                if time.time() - start_time > timeout:
                    await self._increment_stats(identifier, "timeout")
                    return False
                await asyncio.sleep(0.1)
                continue
            except Exception as e:
                logger.error(f"Unexpected token bucket error for {identifier}: {e}")
                await self._increment_stats(identifier, "timeout")
                return False

    async def _calculate_wait_time(self, identifier: str) -> float:
        """다음 요청까지 대기 시간 계산.

        Args:
            identifier: 식별자

        Returns:
            대기 시간 (초)
        """
        try:
            key = f"{self.rate_limit_prefix}{identifier}"

            # 가장 오래된 요청 시간 조회
            oldest_requests = await self.redis.client.zrange(
                key, 0, 0, withscores=True
            )

            if oldest_requests:
                oldest_time = oldest_requests[0][1]
                # 가장 오래된 요청이 윈도우를 벗어날 때까지 대기
                wait_time = (oldest_time + self.time_window) - time.time()
                return max(0, wait_time)

            return 0

        except Exception as e:
            logger.error(f"Failed to calculate wait time for {identifier}: {e}")
            return 1.0  # 기본 대기 시간

    async def reset(self, identifier: str) -> bool:
        """특정 식별자의 rate limit 초기화.

        Args:
            identifier: 식별자

        Returns:
            성공 시 True
        """
        try:
            key = f"{self.rate_limit_prefix}{identifier}"
            deleted = await self.redis.delete(key)
            logger.info(f"Reset rate limit for {identifier}")
            return deleted > 0

        except Exception as e:
            logger.error(f"Failed to reset rate limit for {identifier}: {e}")
            return False

    async def get_remaining(self, identifier: str) -> int:
        """남은 요청 수 조회.

        Args:
            identifier: 식별자

        Returns:
            남은 요청 수
        """
        try:
            key = f"{self.rate_limit_prefix}{identifier}"
            now = time.time()

            # 현재 윈도우 내 요청 수 조회
            current_requests = await self.redis.client.zcount(
                key,
                now - self.time_window,
                now
            )

            return max(0, self.max_requests - current_requests)

        except Exception as e:
            logger.error(f"Failed to get remaining requests for {identifier}: {e}")
            return 0

    async def get_reset_time(self, identifier: str) -> float:
        """Rate limit 리셋 시간 조회.

        Args:
            identifier: 식별자

        Returns:
            리셋까지 남은 시간 (초)
        """
        try:
            key = f"{self.rate_limit_prefix}{identifier}"
            now = time.time()

            # 가장 오래된 요청 시간 조회
            oldest_requests = await self.redis.client.zrange(
                key, 0, 0, withscores=True
            )

            if oldest_requests:
                oldest_time = oldest_requests[0][1]
                reset_time = (oldest_time + self.time_window) - now
                return max(0, reset_time)

            return 0

        except Exception as e:
            logger.error(f"Failed to get reset time for {identifier}: {e}")
            return self.time_window

    async def _increment_stats(self, identifier: str, stat_type: str) -> None:
        """통계 업데이트.

        Args:
            identifier: 식별자
            stat_type: 통계 타입 (allowed, rejected, timeout)
        """
        try:
            stats_key = f"{self.stats_prefix}{identifier}:{stat_type}"
            await self.redis.incr(stats_key)
            await self.redis.expire(stats_key, 86400)  # 24시간 TTL

        except Exception as e:
            logger.debug(f"Failed to update stats: {e}")

    async def get_stats(self, identifier: Optional[str] = None) -> Dict[str, Any]:
        """Rate limit 통계 조회.

        Args:
            identifier: 특정 식별자 (None이면 전체)

        Returns:
            통계 딕셔너리
        """
        try:
            if identifier:
                # 특정 식별자 통계
                allowed = await self.redis.get(f"{self.stats_prefix}{identifier}:allowed") or 0
                rejected = await self.redis.get(f"{self.stats_prefix}{identifier}:rejected") or 0
                timeout = await self.redis.get(f"{self.stats_prefix}{identifier}:timeout") or 0
                total = allowed + rejected + timeout

                return {
                    "identifier": identifier,
                    "allowed": allowed,
                    "rejected": rejected,
                    "timeout": timeout,
                    "total": total,
                    "allow_rate": f"{(allowed / total * 100):.2f}%" if total > 0 else "0%",
                    "remaining": await self.get_remaining(identifier),
                    "reset_in": f"{await self.get_reset_time(identifier):.2f}s",
                    "limit": f"{self.max_requests}/{self.time_window}s"
                }
            else:
                # 전체 통계
                return {
                    "algorithm": self.algorithm.value,
                    "max_requests": self.max_requests,
                    "time_window": self.time_window,
                    "message": "Use identifier parameter for detailed stats"
                }

        except Exception as e:
            logger.error(f"Failed to get rate limit stats: {e}")
            return {}

    async def update_limit(self, max_requests: int, time_window: Optional[int] = None) -> None:
        """Rate limit 설정 변경.

        Args:
            max_requests: 새로운 최대 요청 수
            time_window: 새로운 시간 윈도우 (선택)
        """
        old_limit = f"{self.max_requests}/{self.time_window}s"

        self.max_requests = max_requests
        if time_window is not None:
            self.time_window = time_window

        new_limit = f"{self.max_requests}/{self.time_window}s"
        logger.info(f"Rate limit updated: {old_limit} → {new_limit}")


class PriorityRateLimiter(DistributedRateLimiter):
    """우선순위 기반 분산 Rate Limiter.

    우선순위별로 다른 rate limit 적용.
    """

    def __init__(
        self,
        redis_manager: RedisManager,
        priority_limits: Dict[str, Dict[str, int]]
    ):
        """PriorityRateLimiter 초기화.

        Args:
            redis_manager: Redis 매니저
            priority_limits: 우선순위별 제한 설정
                {
                    "high": {"max_requests": 5, "time_window": 1},
                    "medium": {"max_requests": 2, "time_window": 1},
                    "low": {"max_requests": 1, "time_window": 1}
                }
        """
        # 기본 설정으로 초기화
        super().__init__(redis_manager)

        self.priority_limits = priority_limits
        self.limiters = {}

        # 우선순위별 limiter 생성
        for priority, limits in priority_limits.items():
            self.limiters[priority] = DistributedRateLimiter(
                redis_manager,
                max_requests=limits["max_requests"],
                time_window=limits["time_window"]
            )

    async def acquire_with_priority(
        self,
        identifier: str,
        priority: str = "low",
        tokens: int = 1,
        wait: bool = False,
        timeout: float = 10.0
    ) -> bool:
        """우선순위 기반 rate limit 체크.

        Args:
            identifier: 식별자
            priority: 우선순위 (high, medium, low)
            tokens: 요청 토큰 수
            wait: 대기 여부
            timeout: 대기 시간 제한

        Returns:
            요청 허가 시 True
        """
        if priority not in self.limiters:
            logger.warning(f"Unknown priority: {priority}, using 'low'")
            priority = "low"

        limiter = self.limiters[priority]
        result = await limiter.acquire(
            f"{priority}:{identifier}",
            tokens,
            wait,
            timeout
        )

        if result:
            logger.debug(f"[PRIORITY RATE LIMIT] Allowed {priority} request for {identifier}")
        else:
            logger.debug(f"[PRIORITY RATE LIMIT] Rejected {priority} request for {identifier}")

        return result