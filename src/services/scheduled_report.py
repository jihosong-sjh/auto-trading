"""장 마감 시 일일 리포트 자동 전송 스케줄러.

이 모듈은 매일 15:30 KST에 일일 리포트를 자동으로 생성하고
설정된 알림 채널로 전송합니다.
또한 시스템 로그 분석을 수행하여 운영 상태를 요약합니다.
"""

import asyncio
from datetime import datetime, time
from typing import List, Optional
from zoneinfo import ZoneInfo
from decimal import Decimal

from .report_generator import DailyReportGenerator, DailyReportData
from .market_close_analyzer import MarketCloseAnalyzer, MarketCloseAnalysisData
from .notifier import BaseNotifier
from ..models.notification import Notification, NotificationType
from ..models.account import Account
from ..models.position import Position
from ..config.settings import Settings
from ..utils.logger import get_logger

KST = ZoneInfo("Asia/Seoul")
logger = get_logger(__name__)

# 장 마감 시간 (15:30 KST)
MARKET_CLOSE_TIME = time(15, 30, 0, tzinfo=KST)


class ScheduledReportSender:
    """장 마감 시 일일 리포트 자동 전송 스케줄러.

    매일 15:30 KST에 일일 거래 리포트를 생성하고
    Discord, Email 등의 알림 채널로 전송합니다.
    또한 시스템 로그 분석을 수행하여 운영 상태를 요약합니다.
    """

    def __init__(
        self,
        report_generator: DailyReportGenerator,
        notifiers: List[BaseNotifier],
        enabled: bool = True,
        enable_analysis: bool = True,
        settings: Optional[Settings] = None
    ):
        """ScheduledReportSender 초기화.

        Args:
            report_generator: 리포트 생성기
            notifiers: 알림 전송기 목록
            enabled: 자동 전송 활성화 여부
            enable_analysis: 장 마감 분석 활성화 여부
            settings: 설정 객체 (분석기용)
        """
        self.report_generator = report_generator
        self.notifiers = notifiers
        self.enabled = enabled
        self.enable_analysis = enable_analysis
        self._settings = settings
        self._analyzer: Optional[MarketCloseAnalyzer] = None
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

        # 분석 기능 활성화 시 분석기 초기화
        if enable_analysis:
            self._analyzer = MarketCloseAnalyzer(settings=settings)

        logger.info(
            f"ScheduledReportSender initialized with {len(notifiers)} notifier(s), "
            f"enabled={enabled}, analysis={enable_analysis}"
        )

    async def start(self) -> None:
        """스케줄러 시작.

        백그라운드에서 매일 15:30에 리포트를 전송하는 태스크를 시작합니다.
        """
        if not self.enabled:
            logger.info("Scheduled report is disabled. Skipping start.")
            return

        if self._task is not None and not self._task.done():
            logger.warning("ScheduledReportSender already running.")
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._schedule_loop())
        logger.info("ScheduledReportSender started.")

    async def stop(self) -> None:
        """스케줄러 중지.

        백그라운드 태스크를 정리하고 종료합니다.
        """
        logger.info("Stopping ScheduledReportSender...")
        self._stop_event.set()

        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.info("ScheduledReportSender task cancelled.")

        logger.info("ScheduledReportSender stopped.")

    async def _schedule_loop(self) -> None:
        """스케줄 루프.

        매일 15:30까지 대기하고, 시간이 되면 리포트를 전송합니다.
        """
        while not self._stop_event.is_set():
            try:
                # 다음 실행 시간 계산
                wait_seconds = self._calculate_wait_seconds()
                logger.info(
                    f"Waiting {wait_seconds:.0f} seconds until next report at 15:30 KST"
                )

                # 대기 (또는 stop 이벤트)
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=wait_seconds
                    )
                    # stop 이벤트가 설정되면 루프 종료
                    break
                except asyncio.TimeoutError:
                    # 타임아웃 = 15:30에 도달
                    pass

                # 리포트 전송 (stop 이벤트가 설정되지 않은 경우에만)
                if not self._stop_event.is_set():
                    logger.info("Market close time reached. Triggering daily report.")
                    # 실제 리포트 전송은 외부에서 호출해야 하므로,
                    # 여기서는 로그만 남기고 콜백을 기다립니다.
                    # 또는 Account와 Position을 받는 메서드를 호출해야 합니다.

            except Exception as e:
                logger.error(f"Error in schedule loop: {e}", exc_info=True)
                # 에러 발생 시 1분 대기 후 재시도
                await asyncio.sleep(60)

    def _calculate_wait_seconds(self) -> float:
        """다음 15:30까지 남은 시간(초) 계산.

        Returns:
            남은 시간 (초)
        """
        now = datetime.now(tz=KST)

        # 오늘 15:30
        today_close = datetime.combine(
            now.date(),
            time(15, 30, 0),
            tzinfo=KST
        )

        # 이미 15:30이 지났으면 내일 15:30
        if now >= today_close:
            from datetime import timedelta
            tomorrow = now.date() + timedelta(days=1)
            next_close = datetime.combine(
                tomorrow,
                time(15, 30, 0),
                tzinfo=KST
            )
        else:
            next_close = today_close

        wait_seconds = (next_close - now).total_seconds()
        return max(wait_seconds, 0)

    async def send_daily_report_now(
        self,
        account: Account,
        positions: List[Position],
        target_date: Optional[datetime] = None
    ) -> bool:
        """일일 리포트를 즉시 생성하고 전송.

        Args:
            account: 계좌 정보
            positions: 현재 포지션 목록
            target_date: 리포트 대상 날짜 (기본값: 오늘)

        Returns:
            전송 성공 여부
        """
        try:
            # 리포트 생성
            report_data = await self.report_generator.generate_daily_report(
                account,
                positions,
                target_date
            )

            # 텍스트 및 HTML 형식 생성
            text_report = self.report_generator.format_report_text(report_data)
            html_report = self.report_generator.format_report_html(report_data)

            # 알림 객체 생성
            notification = Notification(
                notification_type=NotificationType.DAILY_REPORT,
                title=f"Daily Trading Report - {report_data.report_date.strftime('%Y-%m-%d')}",
                message=text_report,
                metadata={
                    "report_date": report_data.report_date.isoformat(),
                    "total_pnl": str(report_data.total_pnl),
                    "return_rate": str(report_data.return_rate),
                    "win_rate": str(report_data.win_rate),
                    "html_report": html_report  # HTML 버전도 포함
                }
            )

            # 모든 알림 채널로 전송
            success_count = 0
            for notifier in self.notifiers:
                if notifier.is_configured():
                    try:
                        success = await notifier.send(notification)
                        if success:
                            success_count += 1
                            logger.info(
                                f"Daily report sent successfully via {notifier.__class__.__name__}"
                            )
                        else:
                            logger.warning(
                                f"Failed to send daily report via {notifier.__class__.__name__}"
                            )
                    except Exception as e:
                        logger.error(
                            f"Error sending daily report via {notifier.__class__.__name__}: {e}",
                            exc_info=True
                        )
                else:
                    logger.debug(
                        f"Notifier {notifier.__class__.__name__} not configured, skipping"
                    )

            # 전송 완료 표시
            if success_count > 0:
                notification.mark_as_sent()

            logger.info(
                f"Daily report sent to {success_count}/{len(self.notifiers)} configured notifier(s)"
            )

            return success_count > 0

        except Exception as e:
            logger.error(f"Error generating or sending daily report: {e}", exc_info=True)
            return False

    async def schedule_daily_report(
        self,
        account_provider,
        position_provider
    ) -> None:
        """일일 리포트를 스케줄링하여 자동 전송.

        이 메서드는 매일 15:30에 호출되어 리포트를 생성하고 전송합니다.

        Args:
            account_provider: 계좌 정보를 제공하는 콜러블 (async callable -> Account)
            position_provider: 포지션 목록을 제공하는 콜러블 (async callable -> List[Position])
        """
        while not self._stop_event.is_set():
            try:
                # 다음 15:30까지 대기
                wait_seconds = self._calculate_wait_seconds()
                logger.info(
                    f"Scheduled daily report waiting {wait_seconds:.0f} seconds until 15:30 KST"
                )

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=wait_seconds
                    )
                    # stop 이벤트가 설정되면 루프 종료
                    break
                except asyncio.TimeoutError:
                    # 15:30 도달
                    pass

                # 리포트 및 분석 전송
                if not self._stop_event.is_set():
                    logger.info("Market close time (15:30 KST) reached. Sending daily report and analysis.")

                    # 계좌 및 포지션 정보 가져오기
                    account = await account_provider()
                    positions = await position_provider()

                    # 리포트 전송
                    await self.send_daily_report_now(account, positions)

                    # 시스템 로그 분석 전송 (활성화된 경우)
                    if self.enable_analysis and self._analyzer:
                        await self.send_daily_analysis_now()

            except Exception as e:
                logger.error(f"Error in scheduled daily report: {e}", exc_info=True)
                # 에러 발생 시 1분 대기 후 재시도
                await asyncio.sleep(60)

    async def send_daily_analysis_now(
        self,
        target_date: Optional[datetime] = None
    ) -> bool:
        """시스템 로그 분석을 즉시 실행하고 전송.

        Args:
            target_date: 분석 대상 날짜 (기본값: 오늘)

        Returns:
            전송 성공 여부
        """
        if not self._analyzer:
            logger.warning("MarketCloseAnalyzer not initialized. Skipping analysis.")
            return False

        try:
            # 로그 분석 실행
            analysis_data = await self._analyzer.analyze(target_date)

            # 텍스트 형식 생성
            text_report = self._analyzer.format_analysis_text(analysis_data)
            discord_metadata = self._analyzer.format_analysis_for_discord(analysis_data)

            # 알림 객체 생성
            notification = Notification(
                notification_type=NotificationType.DAILY_REPORT,
                title=f"System Analysis - {analysis_data.analysis_date.strftime('%Y-%m-%d')}",
                message=text_report[:1000],  # Discord 메시지 길이 제한
                metadata=discord_metadata
            )

            # 모든 알림 채널로 전송
            success_count = 0
            for notifier in self.notifiers:
                if notifier.is_configured():
                    try:
                        success = await notifier.send(notification)
                        if success:
                            success_count += 1
                            logger.info(
                                f"Daily analysis sent successfully via {notifier.__class__.__name__}"
                            )
                        else:
                            logger.warning(
                                f"Failed to send daily analysis via {notifier.__class__.__name__}"
                            )
                    except Exception as e:
                        logger.error(
                            f"Error sending daily analysis via {notifier.__class__.__name__}: {e}",
                            exc_info=True
                        )

            if success_count > 0:
                notification.mark_as_sent()

            logger.info(
                f"Daily analysis sent to {success_count}/{len(self.notifiers)} notifier(s)"
            )

            return success_count > 0

        except Exception as e:
            logger.error(f"Error generating or sending daily analysis: {e}", exc_info=True)
            return False

    async def run_analysis_only(
        self,
        target_date: Optional[datetime] = None
    ) -> Optional[MarketCloseAnalysisData]:
        """분석만 실행하고 결과를 반환 (알림 전송 없음).

        수동으로 분석 결과만 확인하고 싶을 때 사용합니다.

        Args:
            target_date: 분석 대상 날짜 (기본값: 오늘)

        Returns:
            분석 결과 데이터 또는 None (실패 시)
        """
        if not self._analyzer:
            logger.warning("MarketCloseAnalyzer not initialized.")
            return None

        try:
            return await self._analyzer.analyze(target_date)
        except Exception as e:
            logger.error(f"Error running analysis: {e}", exc_info=True)
            return None
