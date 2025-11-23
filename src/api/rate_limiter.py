"""Rate Limiter for Kiwoom API."""

import asyncio

from ..utils.logger import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """API Rate Limiter 구현 (초당 최대 요청 수 제한).

    Attributes:
        max_requests: 최대 요청 수
        time_window: 시간 창 (초)
        requests: 최근 요청 타임스탬프 목록
    """

    def __init__(self, max_requests: int = 15, time_window: float = 1.0):
        """RateLimiter 초기화.

        Args:
            max_requests: 시간 창 내 최대 요청 수 (기본값: 15)
            time_window: 시간 창 (초, 기본값: 1.0)
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Rate limit을 고려하여 요청 허가를 기다림.

        현재 시간 창 내 요청 수가 최대치를 초과하면 대기합니다.
        """
        async with self._lock:
            now = asyncio.get_event_loop().time()

            # 시간 창 밖의 오래된 요청 제거
            cutoff = now - self.time_window
            self.requests = [req_time for req_time in self.requests if req_time > cutoff]

            # 요청 수가 최대치에 도달하면 대기
            if len(self.requests) >= self.max_requests:
                sleep_time = self.requests[0] + self.time_window - now
                if sleep_time > 0:
                    logger.warning(f"Rate limit reached. Sleeping for {sleep_time:.2f} seconds")
                    await asyncio.sleep(sleep_time)
                    # 재귀 호출로 다시 확인
                    return await self.acquire()

            # 현재 요청 기록
            self.requests.append(now)
            return None
