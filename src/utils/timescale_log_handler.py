"""TimescaleDB 로그 핸들러.

Python logging 핸들러를 확장하여 로그를 TimescaleDB에 저장합니다.
"""

import logging
import asyncio
import json
import traceback
from datetime import datetime
from typing import Optional, List, Dict, Any
from queue import Queue
from threading import Thread, Event


logger = logging.getLogger(__name__)


class TimescaleLogHandler(logging.Handler):
    """TimescaleDB에 로그를 저장하는 비동기 핸들러.

    로그를 버퍼에 모았다가 배치로 TimescaleDB에 저장합니다.
    별도 스레드에서 비동기 작업을 처리하여 메인 프로그램에 영향을 주지 않습니다.
    """

    def __init__(
        self,
        db_pool,
        level: int = logging.INFO,
        buffer_size: int = 50,
        flush_interval: float = 5.0
    ):
        """초기화.

        Args:
            db_pool: asyncpg connection pool.
            level: 로그 레벨 (기본: INFO).
            buffer_size: 버퍼 크기. 이 크기에 도달하면 즉시 flush.
            flush_interval: 주기적 flush 간격 (초).
        """
        super().__init__(level)
        self.db_pool = db_pool
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval

        # 로그 버퍼
        self.buffer: List[Dict[str, Any]] = []
        self.buffer_lock = asyncio.Lock()

        # 백그라운드 플러시 작업
        self.flush_event = Event()
        self.stop_event = Event()
        self.flush_thread: Optional[Thread] = None

        # 통계
        self.stats = {
            "logs_collected": 0,
            "logs_written": 0,
            "errors": 0
        }

    def start(self) -> None:
        """백그라운드 플러시 스레드 시작."""
        if self.flush_thread is None:
            self.flush_thread = Thread(target=self._flush_loop, daemon=True)
            self.flush_thread.start()
            logger.debug("TimescaleLogHandler flush thread started")

    def stop(self) -> None:
        """백그라운드 플러시 스레드 중지."""
        if self.flush_thread:
            self.stop_event.set()
            self.flush_thread.join(timeout=10.0)
            self.flush_thread = None
            logger.debug("TimescaleLogHandler flush thread stopped")

    def emit(self, record: logging.LogRecord) -> None:
        """로그 레코드를 버퍼에 추가.

        Args:
            record: 로그 레코드.
        """
        try:
            log_entry = self._format_log_entry(record)

            # 버퍼에 추가 (동기적으로)
            self.buffer.append(log_entry)
            self.stats["logs_collected"] += 1

            # 버퍼가 가득 차면 플러시 이벤트 발생
            if len(self.buffer) >= self.buffer_size:
                self.flush_event.set()

        except Exception as e:
            # 로그 핸들러에서 예외가 발생하면 안되므로 조용히 처리
            self.handleError(record)
            self.stats["errors"] += 1

    def _format_log_entry(self, record: logging.LogRecord) -> Dict[str, Any]:
        """로그 레코드를 딕셔너리로 변환.

        Args:
            record: 로그 레코드.

        Returns:
            로그 엔트리 딕셔너리.
        """
        # 기본 정보
        log_entry = {
            "time": datetime.fromtimestamp(record.created),
            "log_level": record.levelname,
            "logger_name": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function_name": record.funcName,
            "line_number": record.lineno,
            "exception_info": None,
            "context": {}
        }

        # 예외 정보
        if record.exc_info:
            log_entry["exception_info"] = "".join(
                traceback.format_exception(*record.exc_info)
            )

        # 추가 컨텍스트 (record의 추가 속성)
        context = {}
        for key, value in record.__dict__.items():
            # 표준 속성은 제외
            if key not in [
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "message", "pathname", "process", "processName",
                "relativeCreated", "thread", "threadName", "exc_info",
                "exc_text", "stack_info"
            ]:
                # JSON 직렬화 가능한 값만 추가
                try:
                    json.dumps(value)
                    context[key] = value
                except (TypeError, ValueError):
                    context[key] = str(value)

        if context:
            log_entry["context"] = context

        return log_entry

    def _flush_loop(self) -> None:
        """백그라운드 플러시 루프 (스레드에서 실행)."""
        # 새 이벤트 루프 생성 (새 스레드이므로)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            while not self.stop_event.is_set():
                # 플러시 이벤트 또는 타임아웃 대기
                if self.flush_event.wait(timeout=self.flush_interval):
                    self.flush_event.clear()

                # 버퍼 플러시
                loop.run_until_complete(self._flush_buffer())

            # 종료 전 마지막 플러시
            loop.run_until_complete(self._flush_buffer())

        except Exception as e:
            logger.error(f"Error in flush loop: {e}", exc_info=True)
        finally:
            loop.close()

    async def _flush_buffer(self) -> None:
        """버퍼의 로그를 DB에 저장."""
        if not self.buffer:
            return

        # 버퍼 복사 후 초기화
        logs_to_write = self.buffer.copy()
        self.buffer.clear()

        try:
            async with self.db_pool.acquire() as conn:
                await conn.executemany(
                    """
                    INSERT INTO system_event_logs (
                        time, log_level, logger_name, message,
                        module, function_name, line_number,
                        exception_info, context
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (time, logger_name, log_level) DO NOTHING
                    """,
                    [
                        (
                            log["time"],
                            log["log_level"],
                            log["logger_name"],
                            log["message"],
                            log["module"],
                            log["function_name"],
                            log["line_number"],
                            log["exception_info"],
                            json.dumps(log["context"]) if log["context"] else None
                        )
                        for log in logs_to_write
                    ]
                )

            self.stats["logs_written"] += len(logs_to_write)
            logger.debug(f"Flushed {len(logs_to_write)} logs to TimescaleDB")

        except Exception as e:
            logger.error(f"Error flushing logs to TimescaleDB: {e}", exc_info=True)
            self.stats["errors"] += 1
            # 실패한 로그를 버퍼에 다시 추가
            self.buffer.extend(logs_to_write)

    def flush(self) -> None:
        """버퍼 강제 플러시 (동기 인터페이스)."""
        self.flush_event.set()
        # 짧은 대기 시간을 줘서 플러시가 완료되도록 함
        self.flush_event.wait(timeout=1.0)

    def get_stats(self) -> Dict[str, Any]:
        """통계 정보 반환.

        Returns:
            통계 정보 딕셔너리.
        """
        return {
            **self.stats,
            "buffer_size": len(self.buffer)
        }


class AsyncTimescaleLogHandler(logging.Handler):
    """비동기 전용 TimescaleDB 로그 핸들러.

    asyncio 이벤트 루프를 사용하는 환경에서 사용합니다.
    """

    def __init__(
        self,
        db_pool,
        level: int = logging.INFO,
        buffer_size: int = 50
    ):
        """초기화.

        Args:
            db_pool: asyncpg connection pool.
            level: 로그 레벨.
            buffer_size: 버퍼 크기.
        """
        super().__init__(level)
        self.db_pool = db_pool
        self.buffer_size = buffer_size
        self.buffer: List[Dict[str, Any]] = []
        self.stats = {
            "logs_collected": 0,
            "logs_written": 0,
            "errors": 0
        }

    def emit(self, record: logging.LogRecord) -> None:
        """로그 레코드를 버퍼에 추가.

        Args:
            record: 로그 레코드.
        """
        try:
            log_entry = self._format_log_entry(record)
            self.buffer.append(log_entry)
            self.stats["logs_collected"] += 1

            # 버퍼가 가득 차면 비동기 플러시 스케줄링
            if len(self.buffer) >= self.buffer_size:
                asyncio.create_task(self._flush_buffer())

        except Exception:
            self.handleError(record)
            self.stats["errors"] += 1

    def _format_log_entry(self, record: logging.LogRecord) -> Dict[str, Any]:
        """로그 레코드를 딕셔너리로 변환."""
        log_entry = {
            "time": datetime.fromtimestamp(record.created),
            "log_level": record.levelname,
            "logger_name": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function_name": record.funcName,
            "line_number": record.lineno,
            "exception_info": None,
            "context": {}
        }

        if record.exc_info:
            log_entry["exception_info"] = "".join(
                traceback.format_exception(*record.exc_info)
            )

        return log_entry

    async def _flush_buffer(self) -> None:
        """버퍼의 로그를 DB에 저장."""
        if not self.buffer:
            return

        logs_to_write = self.buffer.copy()
        self.buffer.clear()

        try:
            async with self.db_pool.acquire() as conn:
                await conn.executemany(
                    """
                    INSERT INTO system_event_logs (
                        time, log_level, logger_name, message,
                        module, function_name, line_number,
                        exception_info, context
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (time, logger_name, log_level) DO NOTHING
                    """,
                    [
                        (
                            log["time"],
                            log["log_level"],
                            log["logger_name"],
                            log["message"],
                            log["module"],
                            log["function_name"],
                            log["line_number"],
                            log["exception_info"],
                            json.dumps(log["context"]) if log["context"] else None
                        )
                        for log in logs_to_write
                    ]
                )

            self.stats["logs_written"] += len(logs_to_write)

        except Exception as e:
            logger.error(f"Error flushing logs: {e}")
            self.stats["errors"] += 1
            self.buffer.extend(logs_to_write)

    async def close_async(self) -> None:
        """비동기 종료 처리."""
        await self._flush_buffer()
