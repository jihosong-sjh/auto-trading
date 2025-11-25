"""Quick CLI test - 5초만 실행하고 종료."""

import asyncio
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.cli.main import TradingSystem, Settings


async def main():
    """5초 동안 시스템 실행 후 종료."""
    print("=" * 60)
    print("Quick Test: Starting trading system for 5 seconds...")
    print("=" * 60)

    config = Settings()
    system = TradingSystem(config)

    # 5초 후 자동 종료
    async def auto_shutdown():
        await asyncio.sleep(5)
        print("\n[INFO] Auto shutdown after 5 seconds...")
        system.shutdown_event.set()

    # 자동 종료 태스크 시작
    shutdown_task = asyncio.create_task(auto_shutdown())

    try:
        await system.start(mode="simulator")
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user")
    finally:
        if not shutdown_task.done():
            shutdown_task.cancel()

    print("\n[SUCCESS] System shut down cleanly")


if __name__ == "__main__":
    asyncio.run(main())
