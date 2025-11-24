"""Redis를 통한 프로세스간 데이터 공유.

여러 프로세스/전략이 실시간 데이터를 공유하는 메커니즘.
Pub/Sub과 Shared State를 통한 효율적인 데이터 동기화.
"""

import asyncio
import json
import time
from typing import Any, Callable, Dict, List, Optional, Set
from datetime import datetime

from ..utils.logger import get_logger
from .redis_manager import RedisManager

logger = get_logger(__name__)


class SharedDataManager:
    """프로세스간 데이터 공유 매니저.

    Redis를 백엔드로 사용하여 여러 프로세스가
    실시간으로 데이터를 공유할 수 있도록 합니다.

    주요 기능:
    - Shared State: 공유 상태 관리
    - Pub/Sub: 실시간 이벤트 브로드캐스트
    - Leader Election: 리더 프로세스 선출
    - Distributed Lock: 분산 락
    """

    def __init__(self, redis_manager: RedisManager, process_id: Optional[str] = None):
        """SharedDataManager 초기화.

        Args:
            redis_manager: Redis 매니저
            process_id: 프로세스 식별자 (None이면 자동 생성)
        """
        self.redis = redis_manager
        self.process_id = process_id or f"process_{int(time.time() * 1000)}"

        # 키 프리픽스
        self.state_prefix = "shared_state:"
        self.pubsub_prefix = "pubsub:"
        self.leader_prefix = "leader:"
        self.lock_prefix = "lock:"
        self.heartbeat_prefix = "heartbeat:"

        # Pub/Sub 관련
        self.pubsub = None
        self.subscriptions: Dict[str, List[Callable]] = {}
        self.pubsub_task: Optional[asyncio.Task] = None

        # Heartbeat 관련
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.heartbeat_interval = 5  # 5초마다 heartbeat

    async def initialize(self) -> None:
        """매니저 초기화 및 heartbeat 시작."""
        await self.redis.initialize()
        await self.start_heartbeat()
        logger.info(f"SharedDataManager initialized for process: {self.process_id}")

    async def close(self) -> None:
        """매니저 종료 및 정리."""
        await self.stop_heartbeat()
        await self.stop_pubsub()
        logger.info(f"SharedDataManager closed for process: {self.process_id}")

    # ==================== Shared State ====================

    async def get_state(self, key: str, default: Any = None) -> Any:
        """공유 상태 조회.

        Args:
            key: 상태 키
            default: 기본값

        Returns:
            상태 값
        """
        state_key = f"{self.state_prefix}{key}"
        return await self.redis.get(state_key, default)

    async def set_state(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        broadcast: bool = True
    ) -> bool:
        """공유 상태 설정.

        Args:
            key: 상태 키
            value: 상태 값
            ttl: TTL (초)
            broadcast: 변경 이벤트 브로드캐스트 여부

        Returns:
            성공 시 True
        """
        state_key = f"{self.state_prefix}{key}"
        success = await self.redis.set(state_key, value, ttl=ttl)

        if success and broadcast:
            # 상태 변경 이벤트 발행
            await self.publish(
                "state_changed",
                {
                    "key": key,
                    "value": value,
                    "process_id": self.process_id,
                    "timestamp": time.time()
                }
            )

        return success

    async def update_state(
        self,
        key: str,
        updater: Callable[[Any], Any],
        default: Any = None
    ) -> Any:
        """원자적 상태 업데이트.

        Args:
            key: 상태 키
            updater: 업데이트 함수
            default: 기본값

        Returns:
            업데이트된 값
        """
        # Optimistic Locking 사용
        max_retries = 5
        for _ in range(max_retries):
            # 현재 값 조회
            current = await self.get_state(key, default)

            # 업데이트 함수 적용
            new_value = updater(current)

            # CAS (Compare And Swap) 시도
            state_key = f"{self.state_prefix}{key}"
            lock_key = f"{self.lock_prefix}{key}"

            # 짧은 락 획득
            if await self.acquire_lock(lock_key, timeout=1):
                try:
                    # 다시 확인 (Double-Check)
                    current_check = await self.get_state(key, default)
                    if current_check == current:
                        # 값이 변경되지 않았으면 업데이트
                        await self.set_state(key, new_value)
                        return new_value
                finally:
                    await self.release_lock(lock_key)

            # 짧은 대기 후 재시도
            await asyncio.sleep(0.01)

        raise Exception(f"Failed to update state after {max_retries} retries")

    async def delete_state(self, key: str) -> bool:
        """공유 상태 삭제.

        Args:
            key: 상태 키

        Returns:
            삭제 성공 시 True
        """
        state_key = f"{self.state_prefix}{key}"
        return await self.redis.delete(state_key) > 0

    # ==================== Pub/Sub ====================

    async def start_pubsub(self) -> None:
        """Pub/Sub 시작."""
        if self.pubsub_task and not self.pubsub_task.done():
            return

        self.pubsub = self.redis.client.pubsub()
        self.pubsub_task = asyncio.create_task(self._pubsub_listener())
        logger.debug("Pub/Sub started")

    async def stop_pubsub(self) -> None:
        """Pub/Sub 중지."""
        if self.pubsub_task:
            self.pubsub_task.cancel()
            try:
                await self.pubsub_task
            except asyncio.CancelledError:
                pass

        if self.pubsub:
            await self.pubsub.close()

        logger.debug("Pub/Sub stopped")

    async def subscribe(self, channel: str, callback: Callable) -> None:
        """채널 구독.

        Args:
            channel: 채널 이름
            callback: 메시지 수신 콜백 함수
        """
        if not self.pubsub_task:
            await self.start_pubsub()

        # Redis 구독
        full_channel = f"{self.pubsub_prefix}{channel}"
        await self.pubsub.subscribe(full_channel)

        # 콜백 등록
        if channel not in self.subscriptions:
            self.subscriptions[channel] = []
        self.subscriptions[channel].append(callback)

        logger.debug(f"Subscribed to channel: {channel}")

    async def unsubscribe(self, channel: str) -> None:
        """채널 구독 해제.

        Args:
            channel: 채널 이름
        """
        if self.pubsub:
            full_channel = f"{self.pubsub_prefix}{channel}"
            await self.pubsub.unsubscribe(full_channel)

        # 콜백 제거
        if channel in self.subscriptions:
            del self.subscriptions[channel]

        logger.debug(f"Unsubscribed from channel: {channel}")

    async def publish(self, channel: str, message: Any) -> int:
        """메시지 발행.

        Args:
            channel: 채널 이름
            message: 발행할 메시지

        Returns:
            메시지를 수신한 구독자 수
        """
        full_channel = f"{self.pubsub_prefix}{channel}"

        # 메시지 직렬화
        if isinstance(message, (str, bytes, int, float)):
            payload = message
        else:
            payload = json.dumps(message, ensure_ascii=False)

        # 발행
        subscribers = await self.redis.client.publish(full_channel, payload)
        logger.debug(f"Published to {channel}: {subscribers} subscribers")

        return subscribers

    async def _pubsub_listener(self) -> None:
        """Pub/Sub 메시지 리스너."""
        try:
            async for message in self.pubsub.listen():
                if message["type"] == "message":
                    # 채널에서 프리픽스 제거
                    channel = message["channel"].decode()
                    channel = channel.replace(self.pubsub_prefix, "")

                    # 메시지 디시리얼라이즈
                    try:
                        data = json.loads(message["data"])
                    except (json.JSONDecodeError, TypeError):
                        data = message["data"].decode() if isinstance(message["data"], bytes) else message["data"]

                    # 콜백 실행
                    if channel in self.subscriptions:
                        for callback in self.subscriptions[channel]:
                            try:
                                if asyncio.iscoroutinefunction(callback):
                                    await callback(data)
                                else:
                                    callback(data)
                            except Exception as e:
                                logger.error(f"Callback error for channel {channel}: {e}")

        except asyncio.CancelledError:
            logger.debug("Pub/Sub listener cancelled")
            raise
        except Exception as e:
            logger.error(f"Pub/Sub listener error: {e}")

    # ==================== Leader Election ====================

    async def elect_leader(self, service: str, ttl: int = 30) -> bool:
        """리더 선출 시도.

        Args:
            service: 서비스 이름
            ttl: 리더십 TTL (초)

        Returns:
            리더가 되면 True
        """
        leader_key = f"{self.leader_prefix}{service}"

        # 현재 프로세스를 리더로 설정 시도 (nx: 키가 없을 때만)
        success = await self.redis.set(
            leader_key,
            self.process_id,
            ttl=ttl,
            nx=True
        )

        if success:
            logger.info(f"Process {self.process_id} elected as leader for {service}")
        else:
            current_leader = await self.redis.get(leader_key)
            logger.debug(f"Current leader for {service}: {current_leader}")

        return success

    async def is_leader(self, service: str) -> bool:
        """리더 여부 확인.

        Args:
            service: 서비스 이름

        Returns:
            리더면 True
        """
        leader_key = f"{self.leader_prefix}{service}"
        current_leader = await self.redis.get(leader_key)
        return current_leader == self.process_id

    async def renew_leadership(self, service: str, ttl: int = 30) -> bool:
        """리더십 갱신.

        Args:
            service: 서비스 이름
            ttl: 리더십 TTL (초)

        Returns:
            갱신 성공 시 True
        """
        if not await self.is_leader(service):
            return False

        leader_key = f"{self.leader_prefix}{service}"
        return await self.redis.expire(leader_key, ttl)

    async def step_down(self, service: str) -> bool:
        """리더십 포기.

        Args:
            service: 서비스 이름

        Returns:
            성공 시 True
        """
        if not await self.is_leader(service):
            return False

        leader_key = f"{self.leader_prefix}{service}"
        await self.redis.delete(leader_key)
        logger.info(f"Process {self.process_id} stepped down as leader for {service}")
        return True

    # ==================== Distributed Lock ====================

    async def acquire_lock(
        self,
        resource: str,
        timeout: float = 10.0,
        blocking: bool = True,
        blocking_timeout: float = 5.0
    ) -> bool:
        """분산 락 획득.

        Args:
            resource: 리소스 이름
            timeout: 락 타임아웃 (초)
            blocking: 블로킹 모드
            blocking_timeout: 블로킹 대기 시간

        Returns:
            락 획득 성공 시 True
        """
        lock_key = f"{self.lock_prefix}{resource}"
        lock_value = f"{self.process_id}:{time.time()}"

        if not blocking:
            # Non-blocking 모드: 한 번만 시도
            return await self.redis.set(lock_key, lock_value, ttl=int(timeout), nx=True)

        # Blocking 모드: 타임아웃까지 재시도
        start_time = time.time()
        while time.time() - start_time < blocking_timeout:
            if await self.redis.set(lock_key, lock_value, ttl=int(timeout), nx=True):
                logger.debug(f"Lock acquired for {resource} by {self.process_id}")
                return True

            await asyncio.sleep(0.01)

        logger.warning(f"Failed to acquire lock for {resource} after {blocking_timeout}s")
        return False

    async def release_lock(self, resource: str) -> bool:
        """분산 락 해제.

        Args:
            resource: 리소스 이름

        Returns:
            해제 성공 시 True
        """
        lock_key = f"{self.lock_prefix}{resource}"

        # 현재 락 소유자 확인
        lock_value = await self.redis.get(lock_key)
        if lock_value and lock_value.startswith(self.process_id):
            await self.redis.delete(lock_key)
            logger.debug(f"Lock released for {resource} by {self.process_id}")
            return True

        logger.warning(f"Cannot release lock for {resource}: not owner")
        return False

    async def extend_lock(self, resource: str, timeout: float = 10.0) -> bool:
        """락 시간 연장.

        Args:
            resource: 리소스 이름
            timeout: 새로운 타임아웃 (초)

        Returns:
            연장 성공 시 True
        """
        lock_key = f"{self.lock_prefix}{resource}"

        # 현재 락 소유자 확인
        lock_value = await self.redis.get(lock_key)
        if lock_value and lock_value.startswith(self.process_id):
            return await self.redis.expire(lock_key, int(timeout))

        return False

    # ==================== Heartbeat ====================

    async def start_heartbeat(self) -> None:
        """Heartbeat 시작."""
        if self.heartbeat_task and not self.heartbeat_task.done():
            return

        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.debug(f"Heartbeat started for process {self.process_id}")

    async def stop_heartbeat(self) -> None:
        """Heartbeat 중지."""
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass

        # 마지막 heartbeat 제거
        heartbeat_key = f"{self.heartbeat_prefix}{self.process_id}"
        await self.redis.delete(heartbeat_key)

        logger.debug(f"Heartbeat stopped for process {self.process_id}")

    async def _heartbeat_loop(self) -> None:
        """Heartbeat 루프."""
        try:
            while True:
                heartbeat_key = f"{self.heartbeat_prefix}{self.process_id}"
                await self.redis.set(
                    heartbeat_key,
                    {
                        "process_id": self.process_id,
                        "timestamp": time.time(),
                        "alive": True
                    },
                    ttl=self.heartbeat_interval * 2  # 2배 TTL로 설정
                )

                await asyncio.sleep(self.heartbeat_interval)

        except asyncio.CancelledError:
            logger.debug("Heartbeat loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")

    async def get_alive_processes(self) -> List[str]:
        """활성 프로세스 목록 조회.

        Returns:
            활성 프로세스 ID 리스트
        """
        pattern = f"{self.heartbeat_prefix}*"
        cursor = 0
        alive_processes = []

        while True:
            cursor, keys = await self.redis.client.scan(cursor, match=pattern, count=100)

            for key in keys:
                # 키에서 프로세스 ID 추출
                key_str = key.decode() if isinstance(key, bytes) else key
                process_id = key_str.replace(self.heartbeat_prefix, "")
                alive_processes.append(process_id)

            if cursor == 0:
                break

        return alive_processes

    # ==================== Shared Metrics ====================

    async def increment_metric(self, metric: str, value: int = 1) -> int:
        """메트릭 증가.

        Args:
            metric: 메트릭 이름
            value: 증가량

        Returns:
            증가 후 값
        """
        metric_key = f"metric:{metric}"
        return await self.redis.incr(metric_key, value)

    async def get_metric(self, metric: str) -> int:
        """메트릭 조회.

        Args:
            metric: 메트릭 이름

        Returns:
            메트릭 값
        """
        metric_key = f"metric:{metric}"
        return await self.redis.get(metric_key, 0)

    async def reset_metric(self, metric: str) -> bool:
        """메트릭 리셋.

        Args:
            metric: 메트릭 이름

        Returns:
            성공 시 True
        """
        metric_key = f"metric:{metric}"
        return await self.redis.delete(metric_key) > 0