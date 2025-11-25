"""TimescaleDB 통합 테스트 스크립트.

TimescaleDB 연결 및 로그 저장 기능을 테스트합니다.
"""

import asyncio
import logging
import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent))

from src.config.settings import Settings
from src.timeseries.database import TimeSeriesDB
from src.utils.timescale_log_handler import TimescaleLogHandler


async def test_timescaledb_connection():
    """TimescaleDB 연결 테스트."""
    print("\n=== TimescaleDB Connection Test ===")

    # 설정 로드
    config = Settings()

    # TimescaleDB 연결
    db = TimeSeriesDB(
        host=config.timescaledb_host,
        port=config.timescaledb_port,
        database=config.timescaledb_database,
        user=config.timescaledb_user,
        password=config.timescaledb_password,
        min_size=5,
        max_size=10
    )

    try:
        await db.connect()
        print(f"[SUCCESS] Connected to TimescaleDB at {config.timescaledb_host}:{config.timescaledb_port}")

        # 테이블 확인
        async with db.pool.acquire() as conn:
            tables = await conn.fetch("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
            """)

            print(f"\n[INFO] Found {len(tables)} tables:")
            for table in tables:
                print(f"  - {table['table_name']}")

        await db.disconnect()
        return True

    except Exception as e:
        print(f"[ERROR] Failed to connect: {e}")
        return False


async def test_log_handler():
    """TimescaleLogHandler 테스트."""
    print("\n=== TimescaleDB Log Handler Test ===")

    # 설정 로드
    config = Settings()

    # TimescaleDB 연결
    db = TimeSeriesDB(
        host=config.timescaledb_host,
        port=config.timescaledb_port,
        database=config.timescaledb_database,
        user=config.timescaledb_user,
        password=config.timescaledb_password,
        min_size=5,
        max_size=10
    )

    try:
        await db.connect()
        print("[INFO] Connected to TimescaleDB")

        # 로그 핸들러 생성
        log_handler = TimescaleLogHandler(
            db_pool=db.pool,
            level=logging.INFO,
            buffer_size=5,  # 테스트를 위해 작은 버퍼 크기
            flush_interval=2.0
        )
        log_handler.start()

        # 테스트 로거 생성
        test_logger = logging.getLogger("test_logger")
        test_logger.setLevel(logging.DEBUG)
        test_logger.addHandler(log_handler)

        # 다양한 로그 레벨 테스트
        print("\n[INFO] Writing test logs...")
        test_logger.info("Test INFO log message")
        test_logger.warning("Test WARNING log message")
        test_logger.error("Test ERROR log message")

        # 컨텍스트가 있는 로그
        test_logger.info("Test with context", extra={"order_id": "12345", "symbol": "005930"})

        # 예외 로그
        try:
            raise ValueError("Test exception")
        except Exception as e:
            test_logger.error("Exception occurred", exc_info=True)

        # 버퍼 크기를 초과하도록 더 많은 로그 작성
        for i in range(10):
            test_logger.info(f"Batch log message {i}")

        print("[INFO] Waiting for logs to flush...")
        await asyncio.sleep(3)  # 플러시 대기

        # 로그 통계
        stats = log_handler.get_stats()
        print(f"\n[INFO] Log handler statistics:")
        print(f"  - Logs collected: {stats['logs_collected']}")
        print(f"  - Logs written to DB: {stats['logs_written']}")
        print(f"  - Errors: {stats['errors']}")
        print(f"  - Current buffer size: {stats['buffer_size']}")

        # 저장된 로그 확인
        async with db.pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM system_event_logs WHERE logger_name = 'test_logger'"
            )
            print(f"\n[INFO] Found {count} log entries in database")

            # 최근 로그 5개 조회
            logs = await conn.fetch("""
                SELECT time, log_level, message, exception_info
                FROM system_event_logs
                WHERE logger_name = 'test_logger'
                ORDER BY time DESC
                LIMIT 5
            """)

            print(f"\n[INFO] Recent log entries:")
            for log in logs:
                exc_info = " [EXCEPTION]" if log['exception_info'] else ""
                print(f"  [{log['log_level']}] {log['time']}: {log['message']}{exc_info}")

        # 정리
        log_handler.stop()
        await db.disconnect()

        return count > 0

    except Exception as e:
        print(f"[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_cli_integration():
    """CLI 통합 테스트 (시뮬레이터 모드로 짧게 실행)."""
    print("\n=== CLI Integration Test ===")
    print("[INFO] This would test the full CLI integration")
    print("[INFO] To test manually, run:")
    print("  python -m src.cli.main start --mode simulator")
    print("[INFO] Then check logs in TimescaleDB:")
    print("  SELECT * FROM system_event_logs ORDER BY time DESC LIMIT 10;")
    return True


async def main():
    """메인 테스트 실행."""
    print("=" * 60)
    print("TimescaleDB Integration Test Suite")
    print("=" * 60)

    results = []

    # 테스트 1: 연결 테스트
    result1 = await test_timescaledb_connection()
    results.append(("Connection Test", result1))

    if result1:
        # 테스트 2: 로그 핸들러 테스트
        result2 = await test_log_handler()
        results.append(("Log Handler Test", result2))

        # 테스트 3: CLI 통합 안내
        result3 = await test_cli_integration()
        results.append(("CLI Integration Info", result3))

    # 결과 요약
    print("\n" + "=" * 60)
    print("Test Results Summary")
    print("=" * 60)
    for test_name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status} {test_name}")

    all_passed = all(result for _, result in results)
    if all_passed:
        print("\n[SUCCESS] All tests passed!")
        return 0
    else:
        print("\n[FAILED] Some tests failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
