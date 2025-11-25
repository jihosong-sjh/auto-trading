"""실시간 이벤트 로그 분석 스크립트.

TimescaleDB에 저장된 로그를 분석하여 시스템 동작을 리뷰합니다.
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config.settings import Settings
from src.timeseries.database import TimeSeriesDB


async def analyze_today_logs():
    """오늘 날짜의 로그 분석."""
    print("=" * 70)
    print("Trading System Log Analysis")
    print("=" * 70)

    config = Settings()
    db = TimeSeriesDB(
        host=config.timescaledb_host,
        port=config.timescaledb_port,
        database=config.timescaledb_database,
        user=config.timescaledb_user,
        password=config.timescaledb_password
    )

    try:
        await db.connect()
        print(f"\n[INFO] Connected to TimescaleDB\n")

        # 오늘 날짜 범위
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)

        async with db.pool.acquire() as conn:
            # 1. 전체 로그 통계
            print("1. Overall Statistics")
            print("-" * 70)

            total = await conn.fetchval(
                "SELECT COUNT(*) FROM system_event_logs WHERE time >= $1 AND time < $2",
                today, tomorrow
            )
            print(f"   Total logs today: {total}")

            # 2. 로그 레벨별 통계
            print("\n2. Log Level Distribution")
            print("-" * 70)

            levels = await conn.fetch("""
                SELECT log_level, COUNT(*) as count
                FROM system_event_logs
                WHERE time >= $1 AND time < $2
                GROUP BY log_level
                ORDER BY count DESC
            """, today, tomorrow)

            for level in levels:
                print(f"   {level['log_level']:10} : {level['count']:>6} logs")

            # 3. 모듈별 로그 통계 (top 10)
            print("\n3. Top 10 Active Modules")
            print("-" * 70)

            modules = await conn.fetch("""
                SELECT logger_name, COUNT(*) as count
                FROM system_event_logs
                WHERE time >= $1 AND time < $2
                GROUP BY logger_name
                ORDER BY count DESC
                LIMIT 10
            """, today, tomorrow)

            for module in modules:
                print(f"   {module['logger_name']:40} : {module['count']:>6} logs")

            # 4. 에러 로그 (최근 10개)
            print("\n4. Recent Error Logs")
            print("-" * 70)

            errors = await conn.fetch("""
                SELECT time, logger_name, message
                FROM system_event_logs
                WHERE time >= $1 AND time < $2 AND log_level = 'ERROR'
                ORDER BY time DESC
                LIMIT 10
            """, today, tomorrow)

            if errors:
                for error in errors:
                    timestamp = error['time'].strftime("%H:%M:%S")
                    print(f"   [{timestamp}] {error['logger_name']}")
                    print(f"      {error['message'][:60]}...")
                    print()
            else:
                print("   No errors found today!")

            # 5. 주요 이벤트 (최근 20개)
            print("\n5. Recent Important Events (INFO level)")
            print("-" * 70)

            events = await conn.fetch("""
                SELECT time, logger_name, message
                FROM system_event_logs
                WHERE time >= $1 AND time < $2 AND log_level = 'INFO'
                AND (
                    message LIKE '%started%' OR
                    message LIKE '%stopped%' OR
                    message LIKE '%connected%' OR
                    message LIKE '%disconnected%' OR
                    message LIKE '%initialized%' OR
                    message LIKE '%shutdown%'
                )
                ORDER BY time DESC
                LIMIT 20
            """, today, tomorrow)

            for event in events:
                timestamp = event['time'].strftime("%H:%M:%S")
                print(f"   [{timestamp}] {event['message'][:60]}")

        await db.disconnect()

    except Exception as e:
        print(f"[ERROR] Failed to analyze logs: {e}")
        import traceback
        traceback.print_exc()


async def analyze_recent_session(minutes: int = 30):
    """최근 N분 동안의 세션 분석."""
    print(f"\n\n{'=' * 70}")
    print(f"Recent {minutes} Minutes Analysis")
    print("=" * 70)

    config = Settings()
    db = TimeSeriesDB(
        host=config.timescaledb_host,
        port=config.timescaledb_port,
        database=config.timescaledb_database,
        user=config.timescaledb_user,
        password=config.timescaledb_password
    )

    try:
        await db.connect()

        start_time = datetime.now() - timedelta(minutes=minutes)

        async with db.pool.acquire() as conn:
            # 최근 세션의 로그 수
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM system_event_logs WHERE time >= $1",
                start_time
            )
            print(f"\nTotal logs in last {minutes} minutes: {count}")

            # 타임라인 (분 단위 집계)
            print(f"\nActivity Timeline (per minute)")
            print("-" * 70)

            timeline = await conn.fetch("""
                SELECT
                    DATE_TRUNC('minute', time) as minute,
                    COUNT(*) as log_count,
                    COUNT(CASE WHEN log_level = 'ERROR' THEN 1 END) as error_count
                FROM system_event_logs
                WHERE time >= $1
                GROUP BY minute
                ORDER BY minute
            """, start_time)

            for entry in timeline:
                minute = entry['minute'].strftime("%H:%M")
                total = entry['log_count']
                errors = entry['error_count']
                bar = "█" * min(int(total / 5), 50)  # 스케일링
                error_mark = f" ({errors} errors)" if errors > 0 else ""
                print(f"   {minute} | {bar} {total}{error_mark}")

        await db.disconnect()

    except Exception as e:
        print(f"[ERROR] Failed to analyze recent session: {e}")


async def main():
    """메인 함수."""
    # 오늘 전체 분석
    await analyze_today_logs()

    # 최근 30분 상세 분석
    await analyze_recent_session(minutes=30)

    print(f"\n{'=' * 70}")
    print("Analysis complete!")
    print("=" * 70)
    print("\nTo view raw logs:")
    print("  docker exec <container_id> psql -U postgres -d trading -c \\")
    print("    \"SELECT * FROM system_event_logs ORDER BY time DESC LIMIT 50;\"")
    print()


if __name__ == "__main__":
    asyncio.run(main())
