"""장 마감 자동 분석 서비스.

매일 15:30 KST 장 마감 시 시스템 로그를 분석하여
운영 상태를 요약하고 Discord로 전송합니다.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from zoneinfo import ZoneInfo

from ..config.settings import Settings
from ..timeseries.database import TimeSeriesDB
from ..utils.logger import get_logger

KST = ZoneInfo("Asia/Seoul")
logger = get_logger(__name__)


@dataclass
class LogLevelStats:
    """로그 레벨별 통계."""
    level: str
    count: int


@dataclass
class ModuleStats:
    """모듈별 로그 통계."""
    module_name: str
    count: int


@dataclass
class ErrorLogEntry:
    """에러 로그 항목."""
    time: datetime
    logger_name: str
    message: str


@dataclass
class MarketCloseAnalysisData:
    """장 마감 분석 결과 데이터.

    Attributes:
        analysis_date: 분석 대상 날짜
        total_logs: 전체 로그 수
        log_level_stats: 로그 레벨별 통계
        top_modules: 상위 10개 활성 모듈
        error_logs: 최근 에러 로그 (최대 10개)
        error_count: 총 에러 수
        warning_count: 총 경고 수
        strategy_signals: 전략 신호 수
        order_executions: 주문 실행 수
        important_events: 주요 이벤트 목록
    """
    analysis_date: datetime
    total_logs: int = 0
    log_level_stats: List[LogLevelStats] = field(default_factory=list)
    top_modules: List[ModuleStats] = field(default_factory=list)
    error_logs: List[ErrorLogEntry] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    strategy_signals: int = 0
    order_executions: int = 0
    important_events: List[str] = field(default_factory=list)


class MarketCloseAnalyzer:
    """장 마감 시스템 로그 분석기.

    TimescaleDB에 저장된 로그를 분석하여 당일 시스템 운영 상태를 요약합니다.
    """

    def __init__(self, settings: Optional[Settings] = None):
        """MarketCloseAnalyzer 초기화.

        Args:
            settings: 설정 객체. None이면 기본 Settings 사용.
        """
        self.settings = settings or Settings()
        self._db: Optional[TimeSeriesDB] = None
        logger.info("MarketCloseAnalyzer initialized")

    async def connect(self) -> None:
        """TimescaleDB 연결."""
        if self._db is None:
            self._db = TimeSeriesDB(
                host=self.settings.timescaledb_host,
                port=self.settings.timescaledb_port,
                database=self.settings.timescaledb_database,
                user=self.settings.timescaledb_user,
                password=self.settings.timescaledb_password
            )
        await self._db.connect()
        logger.info("MarketCloseAnalyzer connected to TimescaleDB")

    async def disconnect(self) -> None:
        """TimescaleDB 연결 해제."""
        if self._db is not None:
            await self._db.disconnect()
            logger.info("MarketCloseAnalyzer disconnected from TimescaleDB")

    async def analyze(
        self,
        target_date: Optional[datetime] = None
    ) -> MarketCloseAnalysisData:
        """당일 로그 분석 실행.

        Args:
            target_date: 분석 대상 날짜. None이면 오늘.

        Returns:
            MarketCloseAnalysisData: 분석 결과
        """
        if target_date is None:
            target_date = datetime.now(tz=KST)

        # 날짜 범위 설정 (00:00:00 ~ 23:59:59)
        start_of_day = target_date.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end_of_day = start_of_day + timedelta(days=1)

        logger.info(f"Analyzing logs for {start_of_day.strftime('%Y-%m-%d')}")

        analysis = MarketCloseAnalysisData(analysis_date=target_date)

        try:
            await self.connect()

            async with self._db.pool.acquire() as conn:
                # 1. 전체 로그 수
                analysis.total_logs = await conn.fetchval(
                    "SELECT COUNT(*) FROM system_event_logs WHERE time >= $1 AND time < $2",
                    start_of_day, end_of_day
                ) or 0

                # 2. 로그 레벨별 통계
                level_rows = await conn.fetch("""
                    SELECT log_level, COUNT(*) as count
                    FROM system_event_logs
                    WHERE time >= $1 AND time < $2
                    GROUP BY log_level
                    ORDER BY count DESC
                """, start_of_day, end_of_day)

                for row in level_rows:
                    analysis.log_level_stats.append(
                        LogLevelStats(level=row['log_level'], count=row['count'])
                    )
                    if row['log_level'] == 'ERROR':
                        analysis.error_count = row['count']
                    elif row['log_level'] == 'WARNING':
                        analysis.warning_count = row['count']

                # 3. 상위 10개 모듈
                module_rows = await conn.fetch("""
                    SELECT logger_name, COUNT(*) as count
                    FROM system_event_logs
                    WHERE time >= $1 AND time < $2
                    GROUP BY logger_name
                    ORDER BY count DESC
                    LIMIT 10
                """, start_of_day, end_of_day)

                for row in module_rows:
                    analysis.top_modules.append(
                        ModuleStats(module_name=row['logger_name'], count=row['count'])
                    )

                # 4. 에러 로그 (최근 10개)
                error_rows = await conn.fetch("""
                    SELECT time, logger_name, message
                    FROM system_event_logs
                    WHERE time >= $1 AND time < $2 AND log_level = 'ERROR'
                    ORDER BY time DESC
                    LIMIT 10
                """, start_of_day, end_of_day)

                for row in error_rows:
                    analysis.error_logs.append(
                        ErrorLogEntry(
                            time=row['time'],
                            logger_name=row['logger_name'],
                            message=row['message'][:200] if row['message'] else ""
                        )
                    )

                # 5. 전략 신호 수 (message에 'signal' 포함)
                analysis.strategy_signals = await conn.fetchval("""
                    SELECT COUNT(*)
                    FROM system_event_logs
                    WHERE time >= $1 AND time < $2
                    AND (
                        LOWER(message) LIKE '%signal%'
                        OR LOWER(logger_name) LIKE '%strategy%'
                    )
                """, start_of_day, end_of_day) or 0

                # 6. 주문 실행 수
                analysis.order_executions = await conn.fetchval("""
                    SELECT COUNT(*)
                    FROM system_event_logs
                    WHERE time >= $1 AND time < $2
                    AND (
                        LOWER(message) LIKE '%order%executed%'
                        OR LOWER(message) LIKE '%order%filled%'
                        OR LOWER(message) LIKE '%order%submitted%'
                    )
                """, start_of_day, end_of_day) or 0

                # 7. 주요 이벤트 (시작/종료/연결 등)
                event_rows = await conn.fetch("""
                    SELECT time, message
                    FROM system_event_logs
                    WHERE time >= $1 AND time < $2
                    AND log_level = 'INFO'
                    AND (
                        LOWER(message) LIKE '%started%'
                        OR LOWER(message) LIKE '%stopped%'
                        OR LOWER(message) LIKE '%connected%'
                        OR LOWER(message) LIKE '%disconnected%'
                        OR LOWER(message) LIKE '%initialized%'
                        OR LOWER(message) LIKE '%shutdown%'
                    )
                    ORDER BY time DESC
                    LIMIT 15
                """, start_of_day, end_of_day)

                for row in event_rows:
                    timestamp = row['time'].strftime("%H:%M:%S")
                    msg = row['message'][:80] if row['message'] else ""
                    analysis.important_events.append(f"[{timestamp}] {msg}")

            logger.info(
                f"Analysis complete: {analysis.total_logs} logs, "
                f"{analysis.error_count} errors, {analysis.strategy_signals} signals"
            )

        except Exception as e:
            logger.error(f"Error during log analysis: {e}", exc_info=True)
            raise
        finally:
            await self.disconnect()

        return analysis

    def format_analysis_text(self, data: MarketCloseAnalysisData) -> str:
        """분석 결과를 텍스트 형식으로 포맷팅.

        Args:
            data: 분석 결과 데이터

        Returns:
            포맷팅된 텍스트
        """
        date_str = data.analysis_date.strftime("%Y-%m-%d")

        lines = [
            f"## Daily System Analysis - {date_str}",
            "",
            "### Overview",
            f"- Total Logs: {data.total_logs:,}",
            f"- Errors: {data.error_count}",
            f"- Warnings: {data.warning_count}",
            f"- Strategy Signals: {data.strategy_signals}",
            f"- Order Executions: {data.order_executions}",
            "",
        ]

        # 로그 레벨 분포
        if data.log_level_stats:
            lines.append("### Log Level Distribution")
            for stat in data.log_level_stats:
                lines.append(f"- {stat.level}: {stat.count:,}")
            lines.append("")

        # 활성 모듈
        if data.top_modules:
            lines.append("### Top Active Modules")
            for i, mod in enumerate(data.top_modules[:5], 1):
                lines.append(f"{i}. {mod.module_name}: {mod.count:,}")
            lines.append("")

        # 에러 로그
        if data.error_logs:
            lines.append("### Recent Errors")
            for err in data.error_logs[:5]:
                time_str = err.time.strftime("%H:%M:%S")
                lines.append(f"- [{time_str}] {err.message[:100]}")
            lines.append("")
        else:
            lines.append("### Errors")
            lines.append("- No errors today!")
            lines.append("")

        # 주요 이벤트
        if data.important_events:
            lines.append("### Important Events")
            for event in data.important_events[:7]:
                lines.append(f"- {event}")

        return "\n".join(lines)

    def format_analysis_for_discord(self, data: MarketCloseAnalysisData) -> Dict[str, Any]:
        """분석 결과를 Discord embed용 메타데이터로 포맷팅.

        Args:
            data: 분석 결과 데이터

        Returns:
            Discord embed에 사용할 메타데이터 딕셔너리
        """
        # 상태 판정 (에러 수에 따라)
        if data.error_count == 0:
            status = "Healthy"
            status_emoji = "[OK]"
        elif data.error_count < 10:
            status = "Minor Issues"
            status_emoji = "[!]"
        else:
            status = "Needs Attention"
            status_emoji = "[!!]"

        return {
            "status": f"{status_emoji} {status}",
            "total_logs": f"{data.total_logs:,}",
            "errors": str(data.error_count),
            "warnings": str(data.warning_count),
            "strategy_signals": str(data.strategy_signals),
            "order_executions": str(data.order_executions),
            "top_module": data.top_modules[0].module_name if data.top_modules else "N/A",
        }
