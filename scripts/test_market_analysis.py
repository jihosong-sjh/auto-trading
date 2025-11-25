"""Market Close Analyzer 테스트 스크립트.

이 스크립트는 장 마감 분석 기능을 수동으로 테스트합니다.
TimescaleDB가 실행 중이어야 합니다.
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.market_close_analyzer import MarketCloseAnalyzer
from src.config.settings import Settings


async def test_analyzer():
    """분석기 테스트."""
    print("=" * 70)
    print("Market Close Analyzer Test")
    print("=" * 70)

    settings = Settings()

    # TimescaleDB 활성화 확인
    if not settings.enable_timescaledb:
        print("[WARNING] TimescaleDB is disabled in settings.")
        print("Set ENABLE_TIMESCALEDB=true in .env to enable.")
        return

    print(f"\n[INFO] TimescaleDB: {settings.timescaledb_host}:{settings.timescaledb_port}")
    print(f"[INFO] Database: {settings.timescaledb_database}")

    analyzer = MarketCloseAnalyzer(settings=settings)

    try:
        print("\n[INFO] Running analysis...")
        result = await analyzer.analyze()

        print("\n" + "=" * 70)
        print("Analysis Result")
        print("=" * 70)

        # 텍스트 형식 출력
        text_report = analyzer.format_analysis_text(result)
        print(text_report)

        # Discord 메타데이터 출력
        print("\n" + "-" * 70)
        print("Discord Metadata:")
        print("-" * 70)
        discord_meta = analyzer.format_analysis_for_discord(result)
        for key, value in discord_meta.items():
            print(f"  {key}: {value}")

        print("\n[SUCCESS] Analysis completed successfully!")

    except Exception as e:
        print(f"\n[ERROR] Analysis failed: {e}")
        import traceback
        traceback.print_exc()


async def test_scheduled_sender():
    """ScheduledReportSender 분석 기능 테스트."""
    print("\n" + "=" * 70)
    print("ScheduledReportSender Analysis Test")
    print("=" * 70)

    from src.services.scheduled_report import ScheduledReportSender
    from src.services.report_generator import DailyReportGenerator
    from src.timeseries.database import TimeSeriesDB

    settings = Settings()

    if not settings.enable_timescaledb:
        print("[WARNING] TimescaleDB is disabled. Skipping.")
        return

    # Mock objects for testing
    db = TimeSeriesDB(
        host=settings.timescaledb_host,
        port=settings.timescaledb_port,
        database=settings.timescaledb_database,
        user=settings.timescaledb_user,
        password=settings.timescaledb_password
    )

    report_generator = DailyReportGenerator(db)

    # ScheduledReportSender with analysis enabled
    sender = ScheduledReportSender(
        report_generator=report_generator,
        notifiers=[],  # No notifiers for test
        enabled=False,  # Don't start scheduler
        enable_analysis=True,
        settings=settings
    )

    try:
        print("\n[INFO] Running analysis via ScheduledReportSender...")
        result = await sender.run_analysis_only()

        if result:
            print(f"\n[SUCCESS] Analysis completed!")
            print(f"  Total logs: {result.total_logs:,}")
            print(f"  Errors: {result.error_count}")
            print(f"  Warnings: {result.warning_count}")
            print(f"  Strategy signals: {result.strategy_signals}")
        else:
            print("\n[WARNING] Analysis returned None")

    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """메인 함수."""
    await test_analyzer()
    await test_scheduled_sender()

    print("\n" + "=" * 70)
    print("All tests completed!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
