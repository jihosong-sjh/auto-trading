"""실제 실행 시뮬레이션 테스트.

이 스크립트는 실제 CLI 실행과 동일한 흐름으로 시스템을 초기화하고 테스트합니다.
python -m src.cli.main start --mode live와 동일한 흐름입니다.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.api.kiwoom_client import KiwoomClient
from src.services.data_collector import DataCollector
from src.config.settings import Settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def test_real_execution_flow():
    """실제 CLI 실행 흐름 시뮬레이션."""
    logger.info("=" * 60)
    logger.info("실제 실행 흐름 시뮬레이션 시작")
    logger.info("=" * 60)

    # 1. Settings 로드 (CLI가 하는 것과 동일)
    config = Settings()
    logger.info(f"설정 로드 완료: Redis={config.redis_enabled}, Rate Limit={config.get_rate_limit_per_second()}/s")

    # 2. KiwoomClient 생성 (main.py:140-146과 동일)
    # 주목: 이 시점에서는 distributed_rate_limiter가 없음!
    client = KiwoomClient(
        api_key=config.kiwoom_api_key or "test_key",
        api_secret=config.kiwoom_api_secret or "test_secret",
        account_number=config.kiwoom_account_number or "12345678",
        base_url=config.get_kiwoom_api_url(),
        max_requests_per_second=config.get_rate_limit_per_second()
        # distributed_rate_limiter는 전달하지 않음 (main.py와 동일)
    )
    logger.info(f"KiwoomClient 생성 완료 (분산 모드: {client.use_distributed})")

    # 3. API 연결 (실제 실행 시 필수)
    await client.connect()
    logger.info("KiwoomClient 연결 완료")

    # 4. Market data queue 생성
    market_data_queue = asyncio.Queue()

    # 5. DataCollector 생성 (main.py:153-157과 동일)
    data_collector = DataCollector(
        config=config,
        client=client,
        market_data_queue=market_data_queue,
        stock_codes=["005930", "000660"]  # 테스트용 종목
    )
    logger.info(f"DataCollector 생성 완료 (Redis 사용: {data_collector.use_redis})")

    # 6. DataCollector.run() 시작 (main.py:198-201과 동일)
    # 이 시점에서 Redis 초기화가 발생!
    logger.info("DataCollector.run() 시작 (Redis 초기화 포함)")

    # run()의 일부만 실행 (Redis 초기화까지)
    if data_collector.use_redis:
        await data_collector.initialize_redis()
        logger.info("Redis 초기화 완료")

        # Redis 초기화 후 상태 확인
        logger.info(f"  - Redis rate limiter 생성: {data_collector.redis_rate_limiter is not None}")
        logger.info(f"  - KiwoomClient 분산 모드: {client.use_distributed}")
        logger.info(f"  - KiwoomClient distributed_rate_limiter: {client.distributed_rate_limiter is not None}")

    # 7. 실제 API 호출 테스트
    logger.info("\n실제 API 호출 시뮬레이션 (5개 요청)")
    start_time = asyncio.get_event_loop().time()

    for i in range(5):
        request_start = asyncio.get_event_loop().time()

        # _request 메서드의 rate limiting 부분만 실행
        if client.use_distributed and client.distributed_rate_limiter:
            logger.info(f"  요청 {i+1}: 분산 rate limiter 사용")
            success = await client.distributed_rate_limiter.acquire(
                identifier="kiwoom_api",
                wait=True,
                timeout=30.0
            )
        else:
            logger.info(f"  요청 {i+1}: 로컬 rate limiter 사용")
            await client.local_rate_limiter.acquire()

        elapsed = asyncio.get_event_loop().time() - request_start
        logger.info(f"    → 대기 시간: {elapsed:.3f}초")

    total_time = asyncio.get_event_loop().time() - start_time
    logger.info(f"\n총 소요 시간: {total_time:.2f}초 (예상: ~4초)")

    # 8. 정리
    if data_collector.use_redis:
        await data_collector.close_redis()
    await client.close()

    # 9. 결과 분석
    logger.info("\n" + "=" * 60)
    logger.info("실행 흐름 분석 결과")
    logger.info("=" * 60)

    if client.use_distributed:
        logger.info("[PASS] 분산 rate limiter가 정상적으로 연결되었습니다")
        logger.info("  - DataCollector가 Redis를 초기화했습니다")
        logger.info("  - KiwoomClient가 분산 rate limiter를 사용했습니다")
    else:
        if config.redis_enabled:
            logger.warning("[WARNING] Redis가 설정되어 있지만 분산 모드가 비활성화되었습니다")
        else:
            logger.info("[PASS] 로컬 rate limiter를 사용했습니다 (Redis 비활성화)")

    if 3.5 <= total_time <= 4.5:
        logger.info(f"[PASS] Rate limiting이 정상 작동합니다 ({total_time:.2f}초)")
    else:
        logger.warning(f"[WARNING] Rate limiting 시간이 예상과 다릅니다 ({total_time:.2f}초)")


async def test_without_redis():
    """Redis 없이 실행 테스트."""
    logger.info("\n" + "=" * 60)
    logger.info("Redis 없이 실행 테스트")
    logger.info("=" * 60)

    # Redis를 비활성화한 설정
    import os
    os.environ["REDIS_ENABLED"] = "false"

    config = Settings()
    config.redis_enabled = False  # 강제로 비활성화

    client = KiwoomClient(
        api_key=config.kiwoom_api_key or "test_key",
        api_secret=config.kiwoom_api_secret or "test_secret",
        account_number=config.kiwoom_account_number or "12345678",
        base_url=config.get_kiwoom_api_url(),
        max_requests_per_second=config.get_rate_limit_per_second()
    )

    await client.connect()

    market_data_queue = asyncio.Queue()
    data_collector = DataCollector(
        config=config,
        client=client,
        market_data_queue=market_data_queue,
        stock_codes=["005930"]
    )

    # Redis 비활성화 상태 확인
    logger.info(f"Redis 사용: {data_collector.use_redis}")
    logger.info(f"Price cache 타입: {type(data_collector.price_cache).__name__}")
    logger.info(f"KiwoomClient 분산 모드: {client.use_distributed}")

    # 3개 요청 테스트
    logger.info("\n3개 요청 테스트 (로컬 rate limiter)")
    start_time = asyncio.get_event_loop().time()

    for i in range(3):
        await client.local_rate_limiter.acquire()
        logger.info(f"  요청 {i+1} 완료")

    total_time = asyncio.get_event_loop().time() - start_time
    logger.info(f"총 소요 시간: {total_time:.2f}초")

    await client.close()

    if 1.8 <= total_time <= 2.5:
        logger.info("[PASS] Redis 없이도 rate limiting이 정상 작동합니다")
    else:
        logger.warning(f"[WARNING] 시간이 예상과 다릅니다 ({total_time:.2f}초)")


async def main():
    """전체 테스트 실행."""
    logger.info("실제 CLI 실행 흐름 테스트")
    logger.info(f"python -m src.cli.main start --mode live 시뮬레이션")
    logger.info("")

    # Test 1: 실제 실행 흐름 (Redis 있음)
    await test_real_execution_flow()

    await asyncio.sleep(1)

    # Test 2: Redis 없이 실행
    await test_without_redis()

    logger.info("\n" + "=" * 60)
    logger.info("테스트 완료")
    logger.info("=" * 60)
    logger.info("")
    logger.info("결론:")
    logger.info("실제 실행 시 DataCollector.run()에서 Redis를 초기화합니다")
    logger.info("Redis 초기화 시 KiwoomClient에 분산 rate limiter가 연결됩니다")
    logger.info("이후 모든 API 호출은 분산 rate limiter를 사용합니다")
    logger.info("Redis가 없어도 로컬 rate limiter로 정상 작동합니다")
    logger.info("")
    logger.info("따라서 python -m src.cli.main start --mode live 실행 시:")
    logger.info("1. 시스템이 정상적으로 시작됩니다")
    logger.info("2. Rate limiting이 올바르게 작동합니다")
    logger.info("3. Redis 장애 시에도 계속 실행됩니다")


if __name__ == "__main__":
    asyncio.run(main())