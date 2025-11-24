"""Rate Limiter for Kiwoom API with Queue-based Buffering.

환경별 Rate Limiting:
- 모의투자: 1 request/second
- 실전투자: 5 requests/second

Queue-based buffering으로 burst 요청을 순차적으로 처리합니다.
"""

import asyncio
import time
from collections import deque
from typing import Optional

from ..utils.logger import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """API Rate Limiter with Queue-based Buffering.

    키움증권 서버의 rate limit을 준수하면서 burst 요청을
    효율적으로 처리하기 위한 Queue 기반 rate limiter.

    Attributes:
        max_requests: 최대 요청 수
        time_window: 시간 창 (초)
        request_queue: 대기 중인 요청 큐
        request_history: 최근 요청 타임스탬프 기록
    """

    def __init__(self, max_requests: int = 1, time_window: float = 1.0):
        """RateLimiter 초기화.

        Args:
            max_requests: 시간 창 내 최대 요청 수 (기본값: 1, 모의투자 제한)
            time_window: 시간 창 (초, 기본값: 1.0)
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.request_history: deque = deque(maxlen=max_requests)
        self._lock = asyncio.Lock()

        # Queue-based buffering
        self.request_queue: asyncio.Queue = asyncio.Queue()
        self._processor_task: Optional[asyncio.Task] = None

        # Statistics
        self._total_requests = 0
        self._total_wait_time = 0.0
        self._max_wait_time = 0.0

        logger.info(
            f"RateLimiter initialized: {max_requests} requests per {time_window}s"
        )

    async def start(self) -> None:
        """Request processor 시작."""
        if self._processor_task is None or self._processor_task.done():
            self._processor_task = asyncio.create_task(self._process_requests())
            logger.debug("Request processor started")

    async def stop(self) -> None:
        """Request processor 중지."""
        if self._processor_task and not self._processor_task.done():
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
            logger.debug("Request processor stopped")

    async def _process_requests(self) -> None:
        """Queue에서 요청을 가져와 rate limit을 준수하며 처리."""
        while True:
            try:
                # Queue에서 요청 대기
                future = await self.request_queue.get()

                # Rate limit 체크 및 대기
                await self._wait_for_slot()

                # 요청 승인
                if not future.done():
                    future.set_result(None)

            except asyncio.CancelledError:
                # Graceful shutdown
                while not self.request_queue.empty():
                    future = self.request_queue.get_nowait()
                    if not future.done():
                        future.cancel()
                break
            except Exception as e:
                logger.error(f"Error in request processor: {e}")

    async def _wait_for_slot(self) -> None:
        """Rate limit을 준수하며 요청 슬롯을 기다림."""
        async with self._lock:
            now = time.time()

            # 오래된 요청 기록 제거
            while self.request_history and self.request_history[0] <= now - self.time_window:
                self.request_history.popleft()

            # Rate limit 체크
            if len(self.request_history) >= self.max_requests:
                # 가장 오래된 요청으로부터 time_window 후까지 대기
                wait_until = self.request_history[0] + self.time_window
                wait_time = wait_until - now

                if wait_time > 0:
                    logger.debug(f"Rate limit reached. Waiting {wait_time:.2f}s")
                    await asyncio.sleep(wait_time)

                    # Statistics update
                    self._total_wait_time += wait_time
                    self._max_wait_time = max(self._max_wait_time, wait_time)

            # 현재 요청 기록
            self.request_history.append(time.time())
            self._total_requests += 1

    async def acquire(self) -> None:
        """Rate limit을 고려하여 요청 허가를 기다림.

        요청을 queue에 추가하고 처리될 때까지 대기합니다.
        """
        # Processor가 실행 중이 아니면 시작
        if self._processor_task is None or self._processor_task.done():
            await self.start()

        # Future 생성 및 queue에 추가
        future = asyncio.Future()
        await self.request_queue.put(future)

        # 처리 대기
        try:
            await future
        except asyncio.CancelledError:
            logger.warning("Request cancelled while waiting in queue")
            raise

    def get_statistics(self) -> dict:
        """Rate limiter 통계 반환.

        Returns:
            통계 정보 딕셔너리:
            - total_requests: 총 요청 수
            - avg_wait_time: 평균 대기 시간
            - max_wait_time: 최대 대기 시간
            - queue_size: 현재 대기 큐 크기
        """
        avg_wait = (
            self._total_wait_time / self._total_requests
            if self._total_requests > 0
            else 0
        )

        return {
            "total_requests": self._total_requests,
            "avg_wait_time": avg_wait,
            "max_wait_time": self._max_wait_time,
            "queue_size": self.request_queue.qsize(),
            "rate_limit": f"{self.max_requests}/{self.time_window}s"
        }

    def update_rate_limit(self, max_requests: int) -> None:
        """Rate limit 동적 업데이트.

        Args:
            max_requests: 새로운 최대 요청 수
        """
        old_limit = self.max_requests
        self.max_requests = max_requests
        self.request_history = deque(self.request_history, maxlen=max_requests)

        logger.info(
            f"Rate limit updated: {old_limit}/{self.time_window}s → "
            f"{max_requests}/{self.time_window}s"
        )