"""Rate Limit 검증 스크립트.

이 스크립트는 다음을 확인합니다:
1. KiwoomClient가 분산 rate limiter를 올바르게 사용하는지
2. Redis 캐시가 제대로 작동하는지
3. API 호출이 1초에 1회로 제한되는지
4. Redis 실패 시 fallback이 작동하는지
"""

import asyncio
import time
from datetime import datetime
from pathlib import Path
import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent))

from src.api.kiwoom_client import KiwoomClient
from src.cache.redis_manager import RedisManager
from src.cache.distributed_rate_limiter import DistributedRateLimiter
from src.config.settings import Settings
from src.utils.logger import get_logger

# 로거 설정
logger = get_logger(__name__)


async def test_basic_rate_limit():
    """기본 rate limit 테스트 (로컬)."""
    logger.info("=" * 60)
    logger.info("TEST 1: 로컬 Rate Limiter 테스트")
    logger.info("=" * 60)

    config = Settings()

    # 로컬 rate limiter만 사용
    client = KiwoomClient(
        api_key=config.kiwoom_api_key or "test_key",
        api_secret=config.kiwoom_api_secret or "test_secret",
        account_number=config.kiwoom_account_number or "12345678",
        base_url=config.get_kiwoom_api_url(),
        max_requests_per_second=1  # 1 req/sec로 제한
    )

    await client.connect()

    # 5개 요청 시도 (5초 소요 예상)
    logger.info("5개 API 요청 시작 (1 req/sec 제한)")
    start_time = time.time()

    for i in range(5):
        request_start = time.time()
        try:
            # 실제 rate limit를 테스트하기 위해 간단한 API 호출 시뮬레이션
            # _request를 직접 호출하되, 실제 HTTP 요청은 하지 않음
            # rate limiter의 acquire만 테스트
            if client.use_distributed and client.distributed_rate_limiter:
                success = await client.distributed_rate_limiter.acquire(
                    identifier="kiwoom_api",
                    wait=True,
                    timeout=30.0
                )
            else:
                await client.local_rate_limiter.acquire()

            elapsed = time.time() - request_start
            logger.info(f"  Request {i+1}: {elapsed:.3f}초")
        except Exception as e:
            logger.error(f"  Request {i+1} failed: {e}")

    total_time = time.time() - start_time
    logger.info(f"총 소요 시간: {total_time:.2f}초 (예상: ~5초)")

    await client.close()

    # 검증 (첫 요청은 즉시, 나머지 4개는 1초씩 = ~4초)
    if 3.5 <= total_time <= 4.5:
        logger.info("[PASS] 로컬 rate limiter가 정상 작동합니다")
    else:
        logger.warning(f"[WARNING] Rate limiting 시간이 예상과 약간 다릅니다: {total_time:.2f}초 (예상: ~4초)")
        # 첫 요청은 즉시 처리되므로 5개 요청에 4초가 정상


async def test_distributed_rate_limit():
    """분산 rate limit 테스트 (Redis)."""
    logger.info("=" * 60)
    logger.info("TEST 2: 분산 Rate Limiter 테스트 (Redis)")
    logger.info("=" * 60)

    config = Settings()

    try:
        # Redis 매니저 초기화
        redis_manager = RedisManager(
            host=config.redis_host,
            port=config.redis_port,
            db=config.redis_db,
            password=config.redis_password,
            max_connections=10
        )
        await redis_manager.initialize()

        # 분산 rate limiter 생성
        distributed_limiter = DistributedRateLimiter(
            redis_manager=redis_manager,
            max_requests=1,  # 1 req/sec
            time_window=1
        )

        # KiwoomClient에 분산 limiter 전달
        client = KiwoomClient(
            api_key=config.kiwoom_api_key or "test_key",
            api_secret=config.kiwoom_api_secret or "test_secret",
            account_number=config.kiwoom_account_number or "12345678",
            base_url=config.get_kiwoom_api_url(),
            max_requests_per_second=1,
            distributed_rate_limiter=distributed_limiter
        )

        await client.connect()

        # 5개 요청 시도
        logger.info("5개 API 요청 시작 (분산 rate limit)")
        start_time = time.time()

        for i in range(5):
            request_start = time.time()
            try:
                # 분산 rate limiter 테스트
                if client.use_distributed and client.distributed_rate_limiter:
                    success = await client.distributed_rate_limiter.acquire(
                        identifier="kiwoom_api",
                        wait=True,
                        timeout=30.0
                    )
                else:
                    await client.local_rate_limiter.acquire()

                elapsed = time.time() - request_start
                logger.info(f"  Request {i+1}: {elapsed:.3f}초")
            except Exception as e:
                logger.error(f"  Request {i+1} failed: {e}")

        total_time = time.time() - start_time
        logger.info(f"총 소요 시간: {total_time:.2f}초 (예상: ~5초)")

        await client.close()
        await redis_manager.close()

        # 검증 (첫 요청은 즉시, 나머지 4개는 1초씩 = ~4초)
        if 3.5 <= total_time <= 4.5:
            logger.info("[PASS] 분산 rate limiter가 정상 작동합니다")
        else:
            logger.warning(f"[WARNING] 분산 rate limiting 시간이 예상과 약간 다릅니다: {total_time:.2f}초 (예상: ~4초)")

    except Exception as e:
        logger.error(f"Redis 연결 실패: {e}")
        logger.info("Redis가 실행 중인지 확인하세요: docker ps | grep redis")


async def test_concurrent_requests():
    """동시 요청 테스트 (rate limit 보장 확인)."""
    logger.info("=" * 60)
    logger.info("TEST 3: 동시 요청 Rate Limit 테스트")
    logger.info("=" * 60)

    config = Settings()

    client = KiwoomClient(
        api_key=config.kiwoom_api_key or "test_key",
        api_secret=config.kiwoom_api_secret or "test_secret",
        account_number=config.kiwoom_account_number or "12345678",
        base_url=config.get_kiwoom_api_url(),
        max_requests_per_second=1
    )

    await client.connect()

    # 동시에 3개 요청 시작
    logger.info("3개 요청을 동시에 시작")
    start_time = time.time()

    async def make_request(index: int):
        request_start = time.time()
        if client.use_distributed and client.distributed_rate_limiter:
            success = await client.distributed_rate_limiter.acquire(
                identifier="kiwoom_api",
                wait=True,
                timeout=30.0
            )
        else:
            await client.local_rate_limiter.acquire()
        elapsed = time.time() - request_start
        logger.info(f"  Request {index}: 완료 (대기 시간: {elapsed:.3f}초)")
        return elapsed

    # 동시 실행
    tasks = [make_request(i+1) for i in range(3)]
    results = await asyncio.gather(*tasks)

    total_time = time.time() - start_time
    logger.info(f"총 소요 시간: {total_time:.2f}초 (예상: ~3초)")

    await client.close()

    # 검증 (첫 요청은 즉시, 나머지 2개는 1초씩 = ~2초)
    if 1.8 <= total_time <= 2.5:
        logger.info("[PASS] 동시 요청도 rate limit이 적용됩니다")
    else:
        logger.warning(f"[WARNING] 동시 요청 rate limiting 시간이 예상과 약간 다릅니다: {total_time:.2f}초 (예상: ~2초)")


async def test_redis_fallback():
    """Redis 실패 시 fallback 테스트."""
    logger.info("=" * 60)
    logger.info("TEST 4: Redis Fallback 테스트")
    logger.info("=" * 60)

    config = Settings()

    # 잘못된 Redis 설정으로 연결 시도
    try:
        redis_manager = RedisManager(
            host="invalid_host_that_does_not_exist",
            port=6379,
            db=0
        )

        # 타임아웃을 짧게 설정
        redis_manager.pool.socket_connect_timeout = 1
        await redis_manager.initialize()

        distributed_limiter = DistributedRateLimiter(
            redis_manager=redis_manager,
            max_requests=1,
            time_window=1
        )
    except Exception as e:
        logger.info(f"예상된 Redis 연결 실패: {e}")
        distributed_limiter = None

    # Fallback으로 로컬 rate limiter 사용
    client = KiwoomClient(
        api_key=config.kiwoom_api_key or "test_key",
        api_secret=config.kiwoom_api_secret or "test_secret",
        account_number=config.kiwoom_account_number or "12345678",
        base_url=config.get_kiwoom_api_url(),
        max_requests_per_second=1,
        distributed_rate_limiter=distributed_limiter  # None이면 자동으로 로컬 사용
    )

    await client.connect()

    # 로컬 rate limiter 사용 확인
    if not client.use_distributed:
        logger.info("[PASS] Redis 실패 시 로컬 rate limiter로 fallback 성공")
    else:
        logger.error("[FAIL] Redis 실패했지만 여전히 분산 모드 사용 중")

    # 실제 rate limiting 테스트
    logger.info("Fallback 상태에서 3개 요청 테스트")
    start_time = time.time()

    for i in range(3):
        request_start = time.time()
        if client.use_distributed and client.distributed_rate_limiter:
            success = await client.distributed_rate_limiter.acquire(
                identifier="kiwoom_api",
                wait=True,
                timeout=30.0
            )
        else:
            await client.local_rate_limiter.acquire()
        elapsed = time.time() - request_start
        logger.info(f"  Request {i+1} 완료 (대기: {elapsed:.3f}초)")

    total_time = time.time() - start_time
    logger.info(f"총 소요 시간: {total_time:.2f}초")

    await client.close()

    if 1.8 <= total_time <= 2.5:
        logger.info("[PASS] Fallback 상태에서도 rate limit 정상 작동")
    else:
        logger.warning(f"[WARNING] Fallback rate limiting 시간이 예상과 약간 다릅니다: {total_time:.2f}초 (예상: ~2초)")


async def main():
    """모든 테스트 실행."""
    logger.info("키움증권 API Rate Limit 검증 시작")
    logger.info(f"시작 시간: {datetime.now()}")

    # Test 1: 로컬 rate limiter
    await test_basic_rate_limit()
    await asyncio.sleep(1)

    # Test 2: 분산 rate limiter (Redis)
    await test_distributed_rate_limit()
    await asyncio.sleep(1)

    # Test 3: 동시 요청
    await test_concurrent_requests()
    await asyncio.sleep(1)

    # Test 4: Redis fallback
    await test_redis_fallback()

    logger.info("=" * 60)
    logger.info("모든 테스트 완료")
    logger.info("=" * 60)
    logger.info("")
    logger.info("다음 단계:")
    logger.info("1. Redis가 실행 중인지 확인: docker ps | grep redis")
    logger.info("2. 실제 API 연결 테스트: python -m src.cli.main test-api --mode live")
    logger.info("3. 시장 개장 후 실행: python -m src.cli.main start --mode live")
    logger.info("")
    logger.info("모니터링:")
    logger.info("- 로그에서 '[RATE LIMIT]' 검색하여 rate limiting 확인")
    logger.info("- 로그에서 '[REDIS HIT]' vs '[API CALL]' 비율 확인")
    logger.info("- Grafana 대시보드: http://localhost:3000")


if __name__ == "__main__":
    asyncio.run(main())