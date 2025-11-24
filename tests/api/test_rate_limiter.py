"""Rate Limiter 테스트.

환경별 rate limit 설정 및 queue-based buffering 검증.
"""

import asyncio
import time
from unittest.mock import patch

import pytest

from src.api.rate_limiter import RateLimiter


@pytest.mark.unit
class TestRateLimiter:
    """RateLimiter 단위 테스트."""

    @pytest.mark.asyncio
    async def test_initialization_default(self):
        """기본 초기화 테스트 (모의투자: 1 req/s)."""
        limiter = RateLimiter()
        assert limiter.max_requests == 1
        assert limiter.time_window == 1.0
        assert limiter.request_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_initialization_custom(self):
        """커스텀 초기화 테스트 (실전투자: 5 req/s)."""
        limiter = RateLimiter(max_requests=5)
        assert limiter.max_requests == 5
        assert limiter.time_window == 1.0

    @pytest.mark.asyncio
    async def test_single_request(self):
        """단일 요청 처리 테스트."""
        limiter = RateLimiter(max_requests=1)
        await limiter.start()

        start = time.time()
        await limiter.acquire()
        elapsed = time.time() - start

        # 첫 요청은 즉시 처리
        assert elapsed < 0.1
        assert limiter._total_requests == 1

        await limiter.stop()

    @pytest.mark.asyncio
    async def test_rate_limiting_enforcement(self):
        """Rate limit 강제 테스트 (1 req/s)."""
        limiter = RateLimiter(max_requests=1)
        await limiter.start()

        start = time.time()

        # 2개 요청을 연속으로 보냄
        await limiter.acquire()
        first_time = time.time() - start

        await limiter.acquire()
        second_time = time.time() - start

        # 첫 번째는 즉시, 두 번째는 1초 후
        assert first_time < 0.1
        assert 0.9 < second_time < 1.2  # 약간의 여유 허용

        await limiter.stop()

    @pytest.mark.asyncio
    async def test_burst_requests_queuing(self):
        """Burst 요청 큐잉 테스트."""
        limiter = RateLimiter(max_requests=2, time_window=1.0)
        await limiter.start()

        # 5개 요청을 동시에 보냄
        tasks = [limiter.acquire() for _ in range(5)]
        start = time.time()
        await asyncio.gather(*tasks)
        elapsed = time.time() - start

        # 2 req/s로 5개 처리: 약 2초 소요
        assert 1.8 < elapsed < 2.5
        assert limiter._total_requests == 5

        await limiter.stop()

    @pytest.mark.asyncio
    async def test_queue_statistics(self):
        """통계 정보 테스트."""
        limiter = RateLimiter(max_requests=1)
        await limiter.start()

        # 몇 개 요청 처리
        await limiter.acquire()
        await asyncio.sleep(1.1)
        await limiter.acquire()

        stats = limiter.get_statistics()
        assert stats["total_requests"] == 2
        assert stats["rate_limit"] == "1/1.0s"
        assert stats["queue_size"] >= 0
        assert stats["avg_wait_time"] >= 0
        assert stats["max_wait_time"] >= 0

        await limiter.stop()

    @pytest.mark.asyncio
    async def test_dynamic_rate_limit_update(self):
        """동적 rate limit 업데이트 테스트."""
        limiter = RateLimiter(max_requests=1)
        await limiter.start()

        # 초기 설정 확인
        assert limiter.max_requests == 1

        # Rate limit 업데이트 (실전투자 모드로 전환)
        limiter.update_rate_limit(5)
        assert limiter.max_requests == 5

        # 업데이트된 limit으로 동작 확인
        start = time.time()
        tasks = [limiter.acquire() for _ in range(5)]
        await asyncio.gather(*tasks)
        elapsed = time.time() - start

        # 5 req/s로 5개는 1초 내 처리
        assert elapsed < 1.2

        await limiter.stop()

    @pytest.mark.asyncio
    async def test_graceful_shutdown(self):
        """Graceful shutdown 테스트."""
        limiter = RateLimiter(max_requests=1)
        await limiter.start()

        # 큐에 요청 추가 후 즉시 종료
        future1 = asyncio.create_task(limiter.acquire())
        future2 = asyncio.create_task(limiter.acquire())
        future3 = asyncio.create_task(limiter.acquire())

        await asyncio.sleep(0.1)  # 첫 요청만 처리되도록
        await limiter.stop()

        # 처리되지 않은 요청은 취소됨
        assert future1.done()  # 첫 번째는 처리됨
        with pytest.raises(asyncio.CancelledError):
            await future2  # 나머지는 취소됨
        with pytest.raises(asyncio.CancelledError):
            await future3

    @pytest.mark.asyncio
    async def test_concurrent_requests_ordering(self):
        """동시 요청의 순서 보장 테스트."""
        limiter = RateLimiter(max_requests=1)
        await limiter.start()

        results = []

        async def make_request(id_):
            await limiter.acquire()
            results.append(id_)

        # 순서대로 요청 생성
        tasks = [make_request(i) for i in range(5)]
        await asyncio.gather(*tasks)

        # FIFO 순서 확인
        assert results == [0, 1, 2, 3, 4]

        await limiter.stop()


@pytest.mark.integration
class TestRateLimiterIntegration:
    """RateLimiter 통합 테스트."""

    @pytest.mark.asyncio
    async def test_with_mock_api_calls(self):
        """모의 API 호출과 함께 테스트."""
        limiter = RateLimiter(max_requests=2)
        await limiter.start()

        api_call_times = []

        async def mock_api_call():
            await limiter.acquire()
            api_call_times.append(time.time())
            return len(api_call_times)

        # 10개 API 호출
        start = time.time()
        results = await asyncio.gather(*[mock_api_call() for _ in range(10)])

        # 결과 검증
        assert results == list(range(1, 11))
        assert len(api_call_times) == 10

        # 2 req/s로 10개: 약 4.5초
        elapsed = time.time() - start
        assert 4.0 < elapsed < 5.5

        # 호출 간격 확인
        intervals = [
            api_call_times[i] - api_call_times[i - 1]
            for i in range(1, len(api_call_times))
        ]

        # 각 간격은 최소 0.5초 (2 req/s)
        for interval in intervals[1::2]:  # 매 두 번째 간격
            assert interval >= 0.45  # 약간의 여유

        await limiter.stop()

    @pytest.mark.asyncio
    async def test_stress_test(self):
        """대량 요청 스트레스 테스트."""
        limiter = RateLimiter(max_requests=10)  # 높은 limit
        await limiter.start()

        # 100개 동시 요청
        tasks = [limiter.acquire() for _ in range(100)]
        start = time.time()
        await asyncio.gather(*tasks)
        elapsed = time.time() - start

        # 10 req/s로 100개: 약 10초
        assert 9.0 < elapsed < 11.0
        assert limiter._total_requests == 100

        # 통계 확인
        stats = limiter.get_statistics()
        assert stats["total_requests"] == 100
        assert stats["avg_wait_time"] > 0

        await limiter.stop()


@pytest.mark.asyncio
async def test_rate_limiter_with_settings():
    """Settings와 통합된 rate limiter 테스트."""
    from src.config.settings import Settings

    # 모의투자 설정
    settings = Settings(kiwoom_trading_mode="virtual")
    assert settings.get_rate_limit_per_second() == 1

    limiter = RateLimiter(max_requests=settings.get_rate_limit_per_second())
    assert limiter.max_requests == 1

    # 실전투자 설정
    settings = Settings(kiwoom_trading_mode="real")
    assert settings.get_rate_limit_per_second() == 5

    limiter = RateLimiter(max_requests=settings.get_rate_limit_per_second())
    assert limiter.max_requests == 5

    # 사용자 지정 설정
    settings = Settings(kiwoom_rate_limit_per_second=3)
    assert settings.get_rate_limit_per_second() == 3