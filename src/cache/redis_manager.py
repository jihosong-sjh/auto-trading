"""Redis 연결 관리 및 기본 캐시 기능.

Connection pooling과 기본 캐싱 인터페이스를 제공합니다.
"""

import json
import pickle
from typing import Any, Optional, Union, List, Dict, Set, Tuple
from datetime import timedelta

import redis.asyncio as redis
from redis.asyncio import ConnectionPool
from redis.exceptions import RedisError

from ..utils.logger import get_logger

logger = get_logger(__name__)


def _safe_decode(value: Any, encoding: str = 'utf-8') -> Any:
    """바이트를 안전하게 디코드.

    Args:
        value: 디코드할 값
        encoding: 사용할 인코딩 (기본: utf-8)

    Returns:
        디코드된 문자열 또는 원본 값
    """
    if not isinstance(value, bytes):
        return value

    try:
        return value.decode(encoding)
    except UnicodeDecodeError as e:
        logger.warning(
            f"UTF-8 decode failed, trying latin-1 fallback: {e}"
        )
        try:
            # latin-1은 모든 바이트 값을 허용하므로 실패하지 않음
            return value.decode('latin-1')
        except Exception as fallback_error:
            logger.error(
                f"All decode attempts failed: {fallback_error}, "
                f"returning raw bytes"
            )
            return value


class RedisManager:
    """Redis 연결 관리 및 기본 캐시 작업.

    Connection pooling을 통한 효율적인 Redis 연결 관리와
    다양한 직렬화 포맷 지원.

    Attributes:
        pool: Redis connection pool
        client: Redis async client
        default_ttl: 기본 TTL (초)
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        max_connections: int = 50,
        default_ttl: int = 60,
        decode_responses: bool = False
    ):
        """RedisManager 초기화.

        Args:
            host: Redis 호스트
            port: Redis 포트
            db: Redis 데이터베이스 번호
            password: Redis 패스워드 (선택)
            max_connections: 최대 연결 수
            default_ttl: 기본 TTL (초)
            decode_responses: 문자열 자동 디코딩 여부
        """
        self.host = host
        self.port = port
        self.db = db
        self.default_ttl = default_ttl

        # Connection pool 생성
        self.pool = ConnectionPool(
            host=host,
            port=port,
            db=db,
            password=password,
            max_connections=max_connections,
            decode_responses=decode_responses,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30
        )

        self.client: Optional[redis.Redis] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Redis 클라이언트 초기화 및 연결 확인."""
        if self._initialized:
            return

        try:
            self.client = redis.Redis(connection_pool=self.pool)

            # 연결 테스트
            await self.client.ping()

            # 서버 정보 로깅
            info = await self.client.info()
            logger.info(
                f"Redis connected: {self.host}:{self.port}, "
                f"version={info.get('redis_version', 'unknown')}, "
                f"connected_clients={info.get('connected_clients', 0)}"
            )

            self._initialized = True

        except RedisError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def close(self) -> None:
        """Redis 연결 종료."""
        if self.client:
            await self.client.close()
            await self.pool.disconnect()
            self._initialized = False
            logger.info("Redis connection closed")

    async def ping(self) -> bool:
        """Redis 연결 상태 확인.

        Returns:
            연결 성공 시 True, 실패 시 False
        """
        if not self._initialized:
            await self.initialize()

        try:
            await self.client.ping()
            return True
        except (RedisError, AttributeError):
            return False

    # ==================== 기본 캐시 작업 ====================

    async def get(self, key: str, default: Any = None) -> Any:
        """캐시에서 값 조회.

        Args:
            key: 캐시 키
            default: 키가 없을 때 반환할 기본값

        Returns:
            캐시된 값 또는 기본값
        """
        if not self._initialized:
            await self.initialize()

        try:
            value = await self.client.get(key)
            if value is None:
                return default

            # bytes를 먼저 UTF-8로 디코딩 시도
            if isinstance(value, bytes):
                try:
                    value = value.decode('utf-8')
                except UnicodeDecodeError:
                    # UTF-8 디코딩 실패 시 pickle 데이터로 간주
                    try:
                        return pickle.loads(value)
                    except (pickle.PickleError, TypeError):
                        return _safe_decode(value)

            # JSON 디시리얼라이즈 시도
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                # JSON 파싱 실패 시 원본 문자열 반환
                return value

        except RedisError as e:
            logger.error(f"Redis get error for key '{key}': {e}")
            return default

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        nx: bool = False,
        xx: bool = False
    ) -> bool:
        """캐시에 값 저장.

        Args:
            key: 캐시 키
            value: 저장할 값
            ttl: TTL (초), None이면 default_ttl 사용
            nx: True면 키가 없을 때만 설정
            xx: True면 키가 있을 때만 설정

        Returns:
            저장 성공 시 True
        """
        if not self._initialized:
            await self.initialize()

        try:
            # 직렬화
            if isinstance(value, (str, bytes, int, float)):
                serialized = value
            else:
                # 복잡한 객체는 JSON 또는 Pickle로 직렬화
                try:
                    # ensure_ascii=True로 한글을 유니코드 이스케이프 처리하여 UTF-8 디코딩 문제 방지
                    serialized = json.dumps(value, ensure_ascii=True)
                except (TypeError, ValueError):
                    serialized = pickle.dumps(value)

            # TTL 설정
            ttl = ttl or self.default_ttl

            # Redis SET 실행
            result = await self.client.set(
                key,
                serialized,
                ex=ttl,
                nx=nx,
                xx=xx
            )

            return bool(result)

        except RedisError as e:
            logger.error(f"Redis set error for key '{key}': {e}")
            return False

    async def delete(self, *keys: str) -> int:
        """캐시에서 키 삭제.

        Args:
            *keys: 삭제할 키들

        Returns:
            삭제된 키 개수
        """
        if not self._initialized:
            await self.initialize()

        try:
            return await self.client.delete(*keys)
        except RedisError as e:
            logger.error(f"Redis delete error for keys {keys}: {e}")
            return 0

    async def exists(self, key: str) -> bool:
        """키 존재 여부 확인.

        Args:
            key: 확인할 키

        Returns:
            키가 존재하면 True
        """
        if not self._initialized:
            await self.initialize()

        try:
            return bool(await self.client.exists(key))
        except RedisError as e:
            logger.error(f"Redis exists error for key '{key}': {e}")
            return False

    async def expire(self, key: str, ttl: int) -> bool:
        """기존 키의 TTL 갱신.

        Args:
            key: 대상 키
            ttl: 새로운 TTL (초)

        Returns:
            TTL 설정 성공 시 True
        """
        if not self._initialized:
            await self.initialize()

        try:
            return bool(await self.client.expire(key, ttl))
        except RedisError as e:
            logger.error(f"Redis expire error for key '{key}': {e}")
            return False

    async def ttl(self, key: str) -> int:
        """키의 남은 TTL 조회.

        Args:
            key: 대상 키

        Returns:
            남은 TTL (초), -1이면 TTL 없음, -2면 키 없음
        """
        if not self._initialized:
            await self.initialize()

        try:
            return await self.client.ttl(key)
        except RedisError as e:
            logger.error(f"Redis ttl error for key '{key}': {e}")
            return -2

    # ==================== 배치 작업 ====================

    async def mget(self, keys: List[str]) -> List[Any]:
        """여러 키를 한 번에 조회.

        Args:
            keys: 조회할 키 리스트

        Returns:
            값 리스트 (키가 없으면 None)
        """
        if not self._initialized:
            await self.initialize()

        try:
            values = await self.client.mget(keys)
            result = []

            for value in values:
                if value is None:
                    result.append(None)
                else:
                    # bytes를 먼저 UTF-8로 디코딩 시도
                    if isinstance(value, bytes):
                        try:
                            value = value.decode('utf-8')
                        except UnicodeDecodeError:
                            # UTF-8 디코딩 실패 시 pickle 데이터로 간주
                            try:
                                result.append(pickle.loads(value))
                                continue
                            except (pickle.PickleError, TypeError):
                                result.append(_safe_decode(value))
                                continue

                    # 디시리얼라이즈
                    try:
                        result.append(json.loads(value))
                    except (json.JSONDecodeError, TypeError):
                        result.append(value)

            return result

        except RedisError as e:
            logger.error(f"Redis mget error for keys {keys}: {e}")
            return [None] * len(keys)

    async def mset(self, mapping: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        """여러 키-값 쌍을 한 번에 저장.

        Args:
            mapping: 키-값 매핑
            ttl: TTL (초)

        Returns:
            저장 성공 시 True
        """
        if not self._initialized:
            await self.initialize()

        try:
            # 직렬화
            serialized = {}
            for key, value in mapping.items():
                if isinstance(value, (str, bytes, int, float)):
                    serialized[key] = value
                else:
                    try:
                        # ensure_ascii=True로 한글을 유니코드 이스케이프 처리하여 UTF-8 디코딩 문제 방지
                        serialized[key] = json.dumps(value, ensure_ascii=True)
                    except (TypeError, ValueError):
                        serialized[key] = pickle.dumps(value)

            # MSET 실행
            async with self.client.pipeline() as pipe:
                pipe.mset(serialized)

                # TTL 설정
                if ttl:
                    for key in serialized:
                        pipe.expire(key, ttl)

                await pipe.execute()

            return True

        except RedisError as e:
            logger.error(f"Redis mset error: {e}")
            return False

    # ==================== 카운터 작업 ====================

    async def incr(self, key: str, amount: int = 1) -> int:
        """카운터 증가.

        Args:
            key: 카운터 키
            amount: 증가량

        Returns:
            증가 후 값
        """
        if not self._initialized:
            await self.initialize()

        try:
            return await self.client.incrby(key, amount)
        except RedisError as e:
            logger.error(f"Redis incr error for key '{key}': {e}")
            return 0

    async def decr(self, key: str, amount: int = 1) -> int:
        """카운터 감소.

        Args:
            key: 카운터 키
            amount: 감소량

        Returns:
            감소 후 값
        """
        if not self._initialized:
            await self.initialize()

        try:
            return await self.client.decrby(key, amount)
        except RedisError as e:
            logger.error(f"Redis decr error for key '{key}': {e}")
            return 0

    # ==================== 리스트 작업 ====================

    async def lpush(self, key: str, *values: Any) -> int:
        """리스트 왼쪽에 값 추가.

        Args:
            key: 리스트 키
            *values: 추가할 값들

        Returns:
            리스트 길이
        """
        if not self._initialized:
            await self.initialize()

        try:
            serialized = []
            for value in values:
                if isinstance(value, (str, bytes, int, float)):
                    serialized.append(value)
                else:
                    # ensure_ascii=True로 한글을 유니코드 이스케이프 처리하여 UTF-8 디코딩 문제 방지
                    serialized.append(json.dumps(value, ensure_ascii=True))

            return await self.client.lpush(key, *serialized)

        except RedisError as e:
            logger.error(f"Redis lpush error for key '{key}': {e}")
            return 0

    async def lrange(self, key: str, start: int = 0, end: int = -1) -> List[Any]:
        """리스트 범위 조회.

        Args:
            key: 리스트 키
            start: 시작 인덱스
            end: 끝 인덱스 (-1이면 끝까지)

        Returns:
            리스트 값들
        """
        if not self._initialized:
            await self.initialize()

        try:
            values = await self.client.lrange(key, start, end)
            result = []

            for value in values:
                # bytes를 먼저 UTF-8로 디코딩 시도
                if isinstance(value, bytes):
                    try:
                        value = value.decode('utf-8')
                    except UnicodeDecodeError:
                        result.append(_safe_decode(value))
                        continue

                try:
                    result.append(json.loads(value))
                except (json.JSONDecodeError, TypeError):
                    result.append(value)

            return result

        except RedisError as e:
            logger.error(f"Redis lrange error for key '{key}': {e}")
            return []

    # ==================== 집합(Set) 작업 ====================

    async def sadd(self, key: str, *values: Any) -> int:
        """집합에 값 추가.

        Args:
            key: 집합 키
            *values: 추가할 값들

        Returns:
            추가된 값 개수
        """
        if not self._initialized:
            await self.initialize()

        try:
            serialized = []
            for value in values:
                if isinstance(value, (str, bytes, int, float)):
                    serialized.append(value)
                else:
                    # ensure_ascii=True로 한글을 유니코드 이스케이프 처리하여 UTF-8 디코딩 문제 방지
                    serialized.append(json.dumps(value, ensure_ascii=True))

            return await self.client.sadd(key, *serialized)

        except RedisError as e:
            logger.error(f"Redis sadd error for key '{key}': {e}")
            return 0

    async def smembers(self, key: str) -> Set[Any]:
        """집합 모든 멤버 조회.

        Args:
            key: 집합 키

        Returns:
            집합 값들
        """
        if not self._initialized:
            await self.initialize()

        try:
            values = await self.client.smembers(key)
            result = set()

            for value in values:
                # bytes를 먼저 UTF-8로 디코딩 시도
                if isinstance(value, bytes):
                    try:
                        value = value.decode('utf-8')
                    except UnicodeDecodeError:
                        result.add(_safe_decode(value))
                        continue

                try:
                    result.add(json.loads(value))
                except (json.JSONDecodeError, TypeError):
                    result.add(value)

            return result

        except RedisError as e:
            logger.error(f"Redis smembers error for key '{key}': {e}")
            return set()

    # ==================== 해시(Hash) 작업 ====================

    async def hset(self, key: str, field: str, value: Any) -> int:
        """해시 필드 설정.

        Args:
            key: 해시 키
            field: 필드 이름
            value: 필드 값

        Returns:
            새로 추가된 필드 수
        """
        if not self._initialized:
            await self.initialize()

        try:
            if isinstance(value, (str, bytes, int, float)):
                serialized = value
            else:
                # ensure_ascii=True로 한글을 유니코드 이스케이프 처리하여 UTF-8 디코딩 문제 방지
                serialized = json.dumps(value, ensure_ascii=True)

            return await self.client.hset(key, field, serialized)

        except RedisError as e:
            logger.error(f"Redis hset error for key '{key}', field '{field}': {e}")
            return 0

    async def hget(self, key: str, field: str) -> Any:
        """해시 필드 조회.

        Args:
            key: 해시 키
            field: 필드 이름

        Returns:
            필드 값
        """
        if not self._initialized:
            await self.initialize()

        try:
            value = await self.client.hget(key, field)
            if value is None:
                return None

            # bytes를 먼저 UTF-8로 디코딩 시도
            if isinstance(value, bytes):
                try:
                    value = value.decode('utf-8')
                except UnicodeDecodeError:
                    return _safe_decode(value)

            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value

        except RedisError as e:
            logger.error(f"Redis hget error for key '{key}', field '{field}': {e}")
            return None

    async def hgetall(self, key: str) -> Dict[str, Any]:
        """해시 모든 필드 조회.

        Args:
            key: 해시 키

        Returns:
            필드-값 매핑
        """
        if not self._initialized:
            await self.initialize()

        try:
            data = await self.client.hgetall(key)
            result = {}

            for field, value in data.items():
                # field를 UTF-8로 디코딩
                if isinstance(field, bytes):
                    field_str = field.decode('utf-8')
                else:
                    field_str = field

                # value를 UTF-8로 디코딩 시도
                if isinstance(value, bytes):
                    try:
                        value = value.decode('utf-8')
                    except UnicodeDecodeError:
                        result[field_str] = _safe_decode(value)
                        continue

                try:
                    result[field_str] = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    result[field_str] = value

            return result

        except RedisError as e:
            logger.error(f"Redis hgetall error for key '{key}': {e}")
            return {}

    # ==================== 통계 및 모니터링 ====================

    async def get_info(self) -> Dict:
        """Redis 서버 정보 조회.

        Returns:
            서버 정보 딕셔너리
        """
        if not self._initialized:
            await self.initialize()

        try:
            return await self.client.info()
        except RedisError as e:
            logger.error(f"Failed to get Redis info: {e}")
            return {}

    async def get_memory_stats(self) -> Dict:
        """메모리 사용 통계 조회.

        Returns:
            메모리 통계 딕셔너리
        """
        if not self._initialized:
            await self.initialize()

        try:
            info = await self.client.info("memory")
            return {
                "used_memory": info.get("used_memory", 0),
                "used_memory_human": info.get("used_memory_human", "0B"),
                "used_memory_peak": info.get("used_memory_peak", 0),
                "used_memory_peak_human": info.get("used_memory_peak_human", "0B"),
                "mem_fragmentation_ratio": info.get("mem_fragmentation_ratio", 0),
            }
        except RedisError as e:
            logger.error(f"Failed to get memory stats: {e}")
            return {}

    async def flush_db(self) -> bool:
        """현재 데이터베이스 모든 키 삭제 (주의!).

        Returns:
            성공 시 True
        """
        if not self._initialized:
            await self.initialize()

        try:
            await self.client.flushdb()
            logger.warning(f"Flushed Redis database {self.db}")
            return True
        except RedisError as e:
            logger.error(f"Failed to flush database: {e}")
            return False