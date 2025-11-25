"""Redis 캐시 클리어 스크립트."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.cache.redis_manager import RedisManager
from src.config.settings import Settings


async def main():
    """Redis 캐시를 클리어합니다."""
    settings = Settings()

    redis_manager = RedisManager(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password
    )

    try:
        await redis_manager.initialize()
        print(f"Redis 연결 성공: {settings.redis_host}:{settings.redis_port}")

        # 현재 데이터베이스의 모든 키 삭제
        result = await redis_manager.flush_db()

        if result:
            print("[SUCCESS] Redis 캐시가 모두 삭제되었습니다!")
        else:
            print("[ERROR] Redis 캐시 삭제 실패")

    except Exception as e:
        print(f"[ERROR] Redis 연결 실패: {e}")
        print(f"Redis가 {settings.redis_host}:{settings.redis_port}에서 실행 중인지 확인하세요.")
    finally:
        await redis_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
