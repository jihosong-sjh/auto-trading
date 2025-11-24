"""Rate Limiter for Kiwoom API with Priority Queue-based Buffering.

환경별 Rate Limiting:
- 모의투자: 1 request/second
- 실전투자: 5 requests/second

Priority Queue-based buffering으로 burst 요청을 우선순위에 따라 처리합니다.
1 req/sec 제약 환경에서 중요한 요청을 우선 처리합니다.
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ..utils.logger import get_logger

logger = get_logger(__name__)


class RequestPriority(Enum):
    """API 요청 우선순위.

    숫자가 낮을수록 높은 우선순위.
    """
    CRITICAL = 1  # 주문 실행, 주문 취소
    HIGH = 2      # 포지션 관련, 계좌 조회
    MEDIUM = 3    # 시세 조회 (포지션 있는 종목)
    LOW = 4       # 시세 조회 (일반)
    BACKGROUND = 5  # 히스토리컬 데이터, 통계


@dataclass(order=True)
class PriorityRequest:
    """우선순위가 있는 요청."""
    priority: int = field(compare=True)
    future: asyncio.Future = field(compare=False)
    created_at: float = field(default_factory=time.time, compare=False)
    description: str = field(default="", compare=False)


class RateLimiter:
    """API Rate Limiter with Priority Queue-based Buffering.

    키움증권 서버의 rate limit을 준수하면서 burst 요청을
    우선순위에 따라 효율적으로 처리하기 위한 Priority Queue 기반 rate limiter.

    Attributes:
        max_requests: 최대 요청 수
        time_window: 시간 창 (초)
        request_queue: 우선순위 기반 대기 요청 큐
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

        # Priority Queue-based buffering (1 req/sec 제약 대응)
        self.request_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._processor_task: Optional[asyncio.Task] = None

        # Statistics
        self._total_requests = 0
        self._total_wait_time = 0.0
        self._max_wait_time = 0.0
        self._priority_stats = {p: 0 for p in RequestPriority}

        logger.info(
            f"Priority RateLimiter initialized: {max_requests} requests per {time_window}s"
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
        """Priority Queue에서 요청을 가져와 rate limit을 준수하며 처리."""
        while True:
            try:
                # Priority Queue에서 요청 대기
                priority_request: PriorityRequest = await self.request_queue.get()

                # 대기 시간 계산
                wait_time = time.time() - priority_request.created_at

                # Rate limit 체크 및 대기
                await self._wait_for_slot()

                # 요청 승인
                if not priority_request.future.done():
                    priority_request.future.set_result(None)

                    # 통계 업데이트
                    self._total_wait_time += wait_time
                    self._max_wait_time = max(self._max_wait_time, wait_time)

                    # 우선순위별 통계
                    for p in RequestPriority:
                        if p.value == priority_request.priority:
                            self._priority_stats[p] += 1
                            break

                    if priority_request.description:
                        logger.debug(
                            f"[PRIORITY {priority_request.priority}] Processed: {priority_request.description} "
                            f"(waited: {wait_time:.2f}s)"
                        )

            except asyncio.CancelledError:
                # Graceful shutdown
                while not self.request_queue.empty():
                    priority_request = self.request_queue.get_nowait()
                    if not priority_request.future.done():
                        priority_request.future.cancel()
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

    async def acquire(self, priority: RequestPriority = RequestPriority.LOW, description: str = "") -> None:
        """Rate limit을 고려하여 요청 허가를 기다림.

        요청을 priority queue에 추가하고 처리될 때까지 대기합니다.

        Args:
            priority: 요청 우선순위 (기본값: LOW)
            description: 요청 설명 (로깅용)
        """
        # Processor가 실행 중이 아니면 시작
        if self._processor_task is None or self._processor_task.done():
            await self.start()

        # PriorityRequest 생성 및 queue에 추가
        future = asyncio.Future()
        priority_request = PriorityRequest(
            priority=priority.value,
            future=future,
            description=description
        )
        await self.request_queue.put(priority_request)

        # 큐 크기 경고
        queue_size = self.request_queue.qsize()
        if queue_size > 50:
            logger.warning(f"Request queue size is high: {queue_size} (priority: {priority.name})")
        elif queue_size > 100:
            logger.error(f"Request queue critically high: {queue_size} (priority: {priority.name})")

        # 처리 대기
        try:
            await future
        except asyncio.CancelledError:
            logger.warning(f"Request cancelled while waiting in queue (priority: {priority.name})")
            raise

    async def acquire_with_priority(self, priority: RequestPriority, description: str = "") -> None:
        """우선순위를 명시적으로 지정하여 요청 허가를 기다림.

        Args:
            priority: 요청 우선순위
            description: 요청 설명 (로깅용)
        """
        await self.acquire(priority=priority, description=description)

    def get_statistics(self) -> dict:
        """Rate limiter 통계 반환.

        Returns:
            통계 정보 딕셔너리:
            - total_requests: 총 요청 수
            - avg_wait_time: 평균 대기 시간
            - max_wait_time: 최대 대기 시간
            - queue_size: 현재 대기 큐 크기
            - priority_breakdown: 우선순위별 요청 수
        """
        avg_wait = (
            self._total_wait_time / self._total_requests
            if self._total_requests > 0
            else 0
        )

        # 우선순위별 통계 정리
        priority_breakdown = {
            p.name: self._priority_stats.get(p, 0)
            for p in RequestPriority
        }

        return {
            "total_requests": self._total_requests,
            "avg_wait_time": avg_wait,
            "max_wait_time": self._max_wait_time,
            "queue_size": self.request_queue.qsize(),
            "rate_limit": f"{self.max_requests}/{self.time_window}s",
            "priority_breakdown": priority_breakdown
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