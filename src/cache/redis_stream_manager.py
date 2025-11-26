"""Redis Streams 기반 메시지 버퍼 관리자.

WebSocket에서 들어오는 시장 데이터를 버퍼링하고
Conflation(종목별 최신 데이터만 유지)을 제공합니다.
"""

import asyncio
import json
import time
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from redis.exceptions import RedisError

from ..models.stock import Stock, KST
from ..models import MarketType
from ..utils.logger import get_logger
from .redis_manager import RedisManager

logger = get_logger(__name__)


class RedisStreamManager:
    """Redis Streams 버퍼 관리자.

    WebSocket 데이터 수집기와 전략 엔진 사이의 버퍼 역할을 합니다.
    Conflation을 통해 종목별 최신 데이터만 효율적으로 처리할 수 있습니다.

    Features:
    - XADD로 고속 데이터 추가 (MAXLEN으로 메모리 관리)
    - Conflation: 종목별 최신 데이터만 반환
    - 시간 기반 데이터 정리 (retention)
    - Consumer Group 불필요 (단일 인스턴스 최적화)

    Usage:
        ```python
        manager = RedisStreamManager(redis_manager, retention_hours=1)

        # Producer (WebSocketDataCollector)
        await manager.xadd("market_data", {"stock_code": "005930", ...})

        # Consumer (StrategyEngine) - Conflation
        latest = await manager.get_latest_by_stock("market_data")
        for stock_code, stock in latest.items():
            await process(stock)
        ```
    """

    def __init__(
        self,
        redis_manager: RedisManager,
        stream_prefix: str = "trading:",
        max_len: int = 100000,
        retention_hours: int = 1,
    ):
        """RedisStreamManager 초기화.

        Args:
            redis_manager: Redis 매니저 인스턴스.
            stream_prefix: Stream 키 접두사. 기본값 "trading:".
            max_len: 최대 Stream 길이 (approximate). 기본값 100000.
            retention_hours: 데이터 보존 시간 (시간). 기본값 1시간.
        """
        self.redis = redis_manager
        self.stream_prefix = stream_prefix
        self.max_len = max_len
        self.retention_hours = retention_hours

        # 마지막으로 읽은 ID 추적 (Conflation용)
        self._last_read_ids: Dict[str, str] = {}

        # 통계
        self._stats = {
            "xadd_count": 0,
            "xread_count": 0,
            "conflation_count": 0,
            "trim_count": 0,
            "errors": 0,
        }

    def _get_stream_key(self, stream_name: str) -> str:
        """Stream 키 생성.

        Args:
            stream_name: Stream 이름 (예: "market_data").

        Returns:
            전체 키 (예: "trading:market_data").
        """
        return f"{self.stream_prefix}{stream_name}"

    # === Producer Methods ===

    async def xadd(
        self,
        stream_name: str,
        data: Dict[str, Any],
        maxlen: Optional[int] = None,
    ) -> Optional[str]:
        """Stream에 메시지 추가 (XADD).

        Args:
            stream_name: Stream 이름.
            data: 메시지 데이터 딕셔너리.
            maxlen: 최대 길이 (None이면 self.max_len 사용).

        Returns:
            메시지 ID (예: "1234567890123-0"). 실패 시 None.
        """
        stream_key = self._get_stream_key(stream_name)
        maxlen = maxlen or self.max_len

        # 직렬화: 복잡한 값은 JSON으로
        serialized = {}
        for key, value in data.items():
            if isinstance(value, (str, int, float, bytes)):
                serialized[key] = str(value) if not isinstance(value, bytes) else value
            elif isinstance(value, Decimal):
                serialized[key] = str(value)
            elif isinstance(value, datetime):
                serialized[key] = value.isoformat()
            else:
                serialized[key] = json.dumps(value, ensure_ascii=True)

        try:
            msg_id = await self.redis.client.xadd(
                stream_key,
                serialized,
                maxlen=maxlen,
                approximate=True,  # ~ 사용으로 효율적 트리밍
            )

            # bytes인 경우 디코드
            if isinstance(msg_id, bytes):
                msg_id = msg_id.decode("utf-8")

            self._stats["xadd_count"] += 1
            return msg_id

        except RedisError as e:
            logger.error(f"XADD failed for {stream_name}: {e}")
            self._stats["errors"] += 1
            return None

    # === Consumer Methods (단일 인스턴스) ===

    async def xread_latest(
        self,
        stream_name: str,
        count: int = 100,
        block_ms: int = 0,
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """최신 메시지 읽기 (마지막 읽은 위치부터).

        Args:
            stream_name: Stream 이름.
            count: 최대 읽을 메시지 수.
            block_ms: 블로킹 타임아웃 (ms). 0이면 non-blocking.

        Returns:
            (message_id, data) 튜플 리스트.
        """
        stream_key = self._get_stream_key(stream_name)
        last_id = self._last_read_ids.get(stream_name, "0")

        try:
            if block_ms > 0:
                result = await self.redis.client.xread(
                    {stream_key: last_id},
                    count=count,
                    block=block_ms,
                )
            else:
                result = await self.redis.client.xread(
                    {stream_key: last_id},
                    count=count,
                )

            if not result:
                return []

            messages = []
            for stream_data in result:
                _, msg_list = stream_data
                for msg_id, fields in msg_list:
                    # 디코드
                    if isinstance(msg_id, bytes):
                        msg_id = msg_id.decode("utf-8")

                    decoded = self._decode_fields(fields)
                    messages.append((msg_id, decoded))

                    # 마지막 ID 업데이트
                    self._last_read_ids[stream_name] = msg_id

            self._stats["xread_count"] += 1
            return messages

        except RedisError as e:
            logger.error(f"XREAD failed for {stream_name}: {e}")
            self._stats["errors"] += 1
            return []

    async def get_latest_by_stock(
        self,
        stream_name: str,
        count: int = 1000,
    ) -> Dict[str, Stock]:
        """종목별 최신 데이터만 반환 (Conflation).

        Stream에서 최신 메시지들을 읽고, 종목별로 가장 최신 데이터만 반환합니다.
        이를 통해 처리할 데이터 양을 대폭 줄입니다.

        Args:
            stream_name: Stream 이름.
            count: 읽을 최대 메시지 수.

        Returns:
            {stock_code: Stock} 딕셔너리.
        """
        messages = await self.xread_latest(stream_name, count=count)

        if not messages:
            return {}

        # 종목별 최신 데이터만 유지
        latest: Dict[str, Dict[str, Any]] = {}
        for msg_id, data in messages:
            stock_code = data.get("stock_code")
            if stock_code:
                latest[stock_code] = data

        # Stock 객체로 변환
        result: Dict[str, Stock] = {}
        for stock_code, data in latest.items():
            try:
                stock = self._data_to_stock(data)
                result[stock_code] = stock
            except Exception as e:
                logger.warning(f"Failed to convert data to Stock: {e}")

        self._stats["conflation_count"] += 1
        logger.debug(
            f"Conflation: {len(messages)} messages -> "
            f"{len(result)} stocks"
        )

        return result

    # === Retention ===

    async def trim_by_time(
        self,
        stream_name: str,
        retention_hours: Optional[int] = None,
    ) -> int:
        """시간 기반 트리밍 (오래된 메시지 삭제).

        Args:
            stream_name: Stream 이름.
            retention_hours: 보존 시간 (시간). None이면 self.retention_hours.

        Returns:
            삭제된 메시지 수.
        """
        stream_key = self._get_stream_key(stream_name)
        retention = retention_hours or self.retention_hours

        # MINID 계산 (retention 시간 전의 타임스탬프)
        min_timestamp = int((time.time() - retention * 3600) * 1000)
        min_id = f"{min_timestamp}-0"

        try:
            # XTRIM MINID
            trimmed = await self.redis.client.xtrim(
                stream_key,
                minid=min_id,
            )

            if trimmed > 0:
                self._stats["trim_count"] += trimmed
                logger.info(
                    f"Trimmed {trimmed} messages from {stream_name} "
                    f"(retention: {retention}h)"
                )

            return trimmed

        except RedisError as e:
            logger.error(f"XTRIM failed for {stream_name}: {e}")
            self._stats["errors"] += 1
            return 0

    async def get_stream_info(self, stream_name: str) -> Dict[str, Any]:
        """Stream 정보 조회.

        Args:
            stream_name: Stream 이름.

        Returns:
            Stream 정보 딕셔너리.
        """
        stream_key = self._get_stream_key(stream_name)

        try:
            info = await self.redis.client.xinfo_stream(stream_key)
            return {
                "length": info.get("length", 0),
                "first_entry": info.get("first-entry"),
                "last_entry": info.get("last-entry"),
            }
        except RedisError as e:
            logger.debug(f"XINFO STREAM failed for {stream_name}: {e}")
            return {"length": 0}

    def get_stats(self) -> dict:
        """통계 반환."""
        return {
            **self._stats,
            "stream_prefix": self.stream_prefix,
            "max_len": self.max_len,
            "retention_hours": self.retention_hours,
        }

    def reset_read_position(self, stream_name: str, position: str = "0") -> None:
        """읽기 위치 리셋.

        Args:
            stream_name: Stream 이름.
            position: 새 위치. "0"이면 처음부터, "$"이면 최신부터.
        """
        self._last_read_ids[stream_name] = position
        logger.debug(f"Reset read position for {stream_name} to {position}")

    # === Private Methods ===

    def _decode_fields(self, fields: Dict[bytes, bytes]) -> Dict[str, Any]:
        """필드 디코드.

        Args:
            fields: 바이트 키-값 딕셔너리.

        Returns:
            디코드된 딕셔너리.
        """
        decoded = {}
        for k, v in fields.items():
            key = k.decode("utf-8") if isinstance(k, bytes) else k
            value = v.decode("utf-8") if isinstance(v, bytes) else v

            # JSON 파싱 시도
            if isinstance(value, str):
                try:
                    decoded[key] = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    decoded[key] = value
            else:
                decoded[key] = value

        return decoded

    def _data_to_stock(self, data: Dict[str, Any]) -> Stock:
        """딕셔너리를 Stock으로 변환.

        Args:
            data: 데이터 딕셔너리.

        Returns:
            Stock 객체.
        """
        # timestamp 처리
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=KST)

        # market 처리 (기본값: KOSPI)
        market_str = data.get("market", "KOSPI")
        try:
            market = MarketType(market_str)
        except ValueError:
            market = MarketType.KOSPI

        return Stock(
            stock_code=data.get("stock_code", ""),
            stock_name=data.get("stock_name", ""),
            market=market,
            current_price=Decimal(str(data.get("current_price", "0"))),
            volume=int(data.get("volume", 0)),
        )
