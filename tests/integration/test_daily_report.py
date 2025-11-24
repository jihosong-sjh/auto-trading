"""일일 리포트 생성 통합 테스트.

DailyReportGenerator, ScheduledReportSender, Notifiers를 통합하여
전체 일일 리포트 생성 및 전송 플로우를 테스트합니다.
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, MagicMock, patch
import aiosqlite

from src.services.report_generator import DailyReportGenerator, DailyReportData
from src.services.scheduled_report import ScheduledReportSender
from src.services.notifier import DiscordNotifier, EmailNotifier
from src.repositories.order_repository import SQLiteOrderRepository
from src.repositories.database import create_tables
from src.models.account import Account
from src.models.position import Position
from src.models.order import Order, OrderType, OrderStatus, PriceType

KST = ZoneInfo("Asia/Seoul")


@pytest.fixture
async def db_connection():
    """테스트용 인메모리 SQLite 데이터베이스 연결."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await create_tables(conn)
    yield conn
    await conn.close()


@pytest.fixture
async def order_repository(db_connection):
    """테스트용 주문 저장소."""
    return SQLiteOrderRepository(db_connection)


@pytest.fixture
def sample_account():
    """테스트용 샘플 계좌."""
    return Account(
        account_number="12345678",
        name="Test Account",
        cash_balance=Decimal("5000000.00"),
        total_asset_value=Decimal("10000000.00"),
        total_pnl=Decimal("500000.00"),
        daily_pnl=Decimal("100000.00"),
        daily_loss_limit=Decimal("500000.00")
    )


@pytest.fixture
def sample_positions():
    """테스트용 샘플 포지션 목록."""
    return [
        Position(
            account_number="12345678",
            stock_code="005930",
            quantity=100,
            average_buy_price=Decimal("70000.00"),
            current_price=Decimal("72000.00")
        ),
        Position(
            account_number="12345678",
            stock_code="000660",
            quantity=50,
            average_buy_price=Decimal("120000.00"),
            current_price=Decimal("125000.00")
        )
    ]


@pytest.fixture
async def sample_orders(order_repository):
    """테스트용 샘플 주문 목록."""
    today = datetime.now(tz=KST)

    orders = [
        # 매수 주문 (체결됨)
        Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.BUY,
            price_type=PriceType.LIMIT,
            quantity=100,
            limit_price=Decimal("70000.00"),
            status=OrderStatus.FILLED,
            filled_quantity=100,
            filled_price=Decimal("70000.00"),
            created_at=today.replace(hour=10, minute=0),
            submitted_at=today.replace(hour=10, minute=1),
            filled_at=today.replace(hour=10, minute=2)
        ),
        # 매수 주문 (체결됨)
        Order(
            account_number="12345678",
            stock_code="000660",
            order_type=OrderType.BUY,
            price_type=PriceType.LIMIT,
            quantity=50,
            limit_price=Decimal("120000.00"),
            status=OrderStatus.FILLED,
            filled_quantity=50,
            filled_price=Decimal("120000.00"),
            created_at=today.replace(hour=11, minute=0),
            submitted_at=today.replace(hour=11, minute=1),
            filled_at=today.replace(hour=11, minute=2)
        ),
        # 매도 주문 (체결됨) - 수익 거래
        Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.MARKET,
            quantity=50,
            status=OrderStatus.FILLED,
            filled_quantity=50,
            filled_price=Decimal("72000.00"),
            created_at=today.replace(hour=14, minute=0),
            submitted_at=today.replace(hour=14, minute=1),
            filled_at=today.replace(hour=14, minute=2)
        ),
        # 취소된 주문
        Order(
            account_number="12345678",
            stock_code="005930",
            order_type=OrderType.SELL,
            price_type=PriceType.LIMIT,
            quantity=50,
            limit_price=Decimal("75000.00"),
            status=OrderStatus.CANCELLED,
            created_at=today.replace(hour=13, minute=0),
            submitted_at=today.replace(hour=13, minute=1)
        )
    ]

    # 주문 저장
    for order in orders:
        await order_repository.save(order)

    return orders


class TestDailyReportGeneration:
    """일일 리포트 생성 통합 테스트."""

    @pytest.mark.asyncio
    async def test_generate_daily_report_with_orders_and_positions(
        self,
        order_repository,
        sample_account,
        sample_positions,
        sample_orders
    ):
        """주문 및 포지션 데이터로 일일 리포트를 생성하는 테스트."""
        # Given: 리포트 생성기 초기화
        initial_balance = Decimal("9500000.00")
        generator = DailyReportGenerator(
            order_repository=order_repository,
            initial_balance=initial_balance
        )

        # When: 일일 리포트 생성
        report_data = await generator.generate_daily_report(
            account=sample_account,
            positions=sample_positions
        )

        # Then: 리포트 데이터 검증
        assert isinstance(report_data, DailyReportData)
        assert report_data.total_orders == 4
        assert report_data.buy_orders == 2
        assert report_data.sell_orders == 2
        assert report_data.filled_orders == 3
        assert report_data.cancelled_orders == 1

        # 매수 금액: 100 * 70000 + 50 * 120000 = 13,000,000
        assert report_data.total_buy_amount == Decimal("13000000.00")

        # 매도 금액: 50 * 72000 = 3,600,000
        assert report_data.total_sell_amount == Decimal("3600000.00")

        # 실현 손익: 매도 - 매수 = 3,600,000 - 13,000,000 = -9,400,000
        # (이 계산은 간단한 구현이므로, 실제로는 포지션별로 계산되어야 함)
        assert report_data.realized_pnl == Decimal("-9400000.00")

        # 미실현 손익: (72000 - 70000) * 100 + (125000 - 120000) * 50 = 200,000 + 250,000 = 450,000
        assert report_data.unrealized_pnl == Decimal("450000.00")

        # 승률 계산 (매도 주문 1개, 모두 수익)
        assert report_data.win_count == 1
        assert report_data.loss_count == 0
        assert report_data.win_rate == Decimal("100")

        # 수익률: (10,000,000 - 9,500,000) / 9,500,000 * 100 = 5.26%
        assert abs(report_data.return_rate - Decimal("5.26")) < Decimal("0.01")

    @pytest.mark.asyncio
    async def test_generate_empty_report_with_no_orders(
        self,
        order_repository,
        sample_account
    ):
        """주문이 없을 때 빈 리포트를 생성하는 테스트."""
        # Given: 리포트 생성기
        generator = DailyReportGenerator(order_repository=order_repository)

        # When: 주문이 없는 상태에서 리포트 생성
        report_data = await generator.generate_daily_report(
            account=sample_account,
            positions=[]
        )

        # Then: 모든 값이 0이어야 함
        assert report_data.total_orders == 0
        assert report_data.buy_orders == 0
        assert report_data.sell_orders == 0
        assert report_data.filled_orders == 0
        assert report_data.total_buy_amount == Decimal("0")
        assert report_data.total_sell_amount == Decimal("0")
        assert report_data.realized_pnl == Decimal("0")
        assert report_data.unrealized_pnl == Decimal("0")
        assert report_data.win_count == 0
        assert report_data.loss_count == 0
        assert report_data.win_rate == Decimal("0")

    @pytest.mark.asyncio
    async def test_format_report_text(
        self,
        order_repository,
        sample_account,
        sample_positions,
        sample_orders
    ):
        """리포트를 텍스트 형식으로 포맷팅하는 테스트."""
        # Given
        generator = DailyReportGenerator(order_repository=order_repository)
        report_data = await generator.generate_daily_report(
            account=sample_account,
            positions=sample_positions
        )

        # When
        text_report = generator.format_report_text(report_data)

        # Then
        assert "Daily Trading Report" in text_report
        assert "Total Orders:" in text_report
        assert "Buy:" in text_report
        assert "Sell:" in text_report
        assert "Filled:" in text_report
        assert "Cancelled:" in text_report
        assert "Realized PnL:" in text_report
        assert "Unrealized PnL:" in text_report
        assert "Win Rate:" in text_report
        assert "Active Positions:" in text_report

    @pytest.mark.asyncio
    async def test_format_report_html(
        self,
        order_repository,
        sample_account,
        sample_positions,
        sample_orders
    ):
        """리포트를 HTML 형식으로 포맷팅하는 테스트."""
        # Given
        generator = DailyReportGenerator(order_repository=order_repository)
        report_data = await generator.generate_daily_report(
            account=sample_account,
            positions=sample_positions
        )

        # When
        html_report = generator.format_report_html(report_data)

        # Then
        assert "<html>" in html_report
        assert "<table>" in html_report
        assert "Daily Trading Report" in html_report
        assert "Order Statistics" in html_report
        assert "PnL Summary" in html_report
        assert "Performance" in html_report
        assert "Account Status" in html_report


class TestScheduledReportSender:
    """스케줄 리포트 전송 통합 테스트."""

    @pytest.mark.asyncio
    async def test_send_daily_report_now(
        self,
        order_repository,
        sample_account,
        sample_positions,
        sample_orders
    ):
        """일일 리포트를 즉시 전송하는 테스트."""
        # Given: 리포트 생성기 및 알림 전송기
        generator = DailyReportGenerator(
            order_repository=order_repository,
            initial_balance=Decimal("9500000.00")
        )

        discord_notifier = DiscordNotifier(webhook_url="https://discord.com/webhooks/test")
        email_notifier = EmailNotifier(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test@example.com",
            smtp_password="password",
            from_addr="test@example.com",
            to_addrs=["recipient@example.com"]
        )

        sender = ScheduledReportSender(
            report_generator=generator,
            notifiers=[discord_notifier, email_notifier]
        )

        # When: 리포트 전송 (알림 전송 모킹)
        with patch.object(discord_notifier, 'send', new_callable=AsyncMock) as mock_discord, \
             patch.object(email_notifier, 'send', new_callable=AsyncMock) as mock_email:

            mock_discord.return_value = True
            mock_email.return_value = True

            result = await sender.send_daily_report_now(
                account=sample_account,
                positions=sample_positions
            )

        # Then: 전송 성공 확인
        assert result is True
        mock_discord.assert_called_once()
        mock_email.assert_called_once()

        # 알림 객체 검증
        discord_call_arg = mock_discord.call_args[0][0]
        assert "Daily Trading Report" in discord_call_arg.title
        assert "Total Orders:" in discord_call_arg.message

    @pytest.mark.asyncio
    async def test_send_daily_report_with_no_notifiers(
        self,
        order_repository,
        sample_account,
        sample_positions
    ):
        """알림 전송기가 없을 때 리포트 전송 테스트."""
        # Given: 알림 전송기가 없는 리포트 전송기
        generator = DailyReportGenerator(order_repository=order_repository)
        sender = ScheduledReportSender(
            report_generator=generator,
            notifiers=[]
        )

        # When
        result = await sender.send_daily_report_now(
            account=sample_account,
            positions=sample_positions
        )

        # Then: 전송 실패 (알림 전송기가 없으므로)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_daily_report_with_unconfigured_notifiers(
        self,
        order_repository,
        sample_account,
        sample_positions
    ):
        """설정되지 않은 알림 전송기가 있을 때 테스트."""
        # Given: 설정되지 않은 알림 전송기
        generator = DailyReportGenerator(order_repository=order_repository)
        discord_notifier = DiscordNotifier(webhook_url=None)  # 설정 안됨

        sender = ScheduledReportSender(
            report_generator=generator,
            notifiers=[discord_notifier]
        )

        # When
        result = await sender.send_daily_report_now(
            account=sample_account,
            positions=sample_positions
        )

        # Then: 전송 실패 (설정되지 않은 알림 전송기)
        assert result is False


class TestFullReportingFlow:
    """전체 리포트 생성 및 전송 플로우 통합 테스트."""

    @pytest.mark.asyncio
    async def test_complete_daily_report_workflow(
        self,
        order_repository,
        sample_account,
        sample_positions,
        sample_orders
    ):
        """일일 리포트 생성부터 전송까지 전체 플로우 테스트."""
        # Given: 모든 컴포넌트 설정
        initial_balance = Decimal("9500000.00")
        generator = DailyReportGenerator(
            order_repository=order_repository,
            initial_balance=initial_balance
        )

        discord_notifier = DiscordNotifier(webhook_url="https://discord.com/webhooks/test")
        email_notifier = EmailNotifier(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test@example.com",
            smtp_password="password",
            from_addr="test@example.com",
            to_addrs=["recipient@example.com"]
        )

        sender = ScheduledReportSender(
            report_generator=generator,
            notifiers=[discord_notifier, email_notifier]
        )

        # When: 전체 플로우 실행
        with patch.object(discord_notifier, 'send', new_callable=AsyncMock) as mock_discord, \
             patch.object(email_notifier, 'send', new_callable=AsyncMock) as mock_email:

            mock_discord.return_value = True
            mock_email.return_value = True

            # 1. 리포트 생성
            report_data = await generator.generate_daily_report(
                account=sample_account,
                positions=sample_positions
            )

            # 2. 리포트 포맷팅
            text_report = generator.format_report_text(report_data)
            html_report = generator.format_report_html(report_data)

            # 3. 리포트 전송
            result = await sender.send_daily_report_now(
                account=sample_account,
                positions=sample_positions
            )

        # Then: 전체 플로우 검증
        # 리포트 데이터 생성 확인
        assert report_data.total_orders == 4
        assert report_data.filled_orders == 3

        # 포맷팅 확인
        assert "Daily Trading Report" in text_report
        assert "<html>" in html_report

        # 전송 확인
        assert result is True
        assert mock_discord.call_count == 1
        assert mock_email.call_count == 1

    @pytest.mark.asyncio
    async def test_scheduler_start_and_stop(
        self,
        order_repository
    ):
        """스케줄러 시작 및 중지 테스트."""
        # Given
        generator = DailyReportGenerator(order_repository=order_repository)
        notifier = DiscordNotifier(webhook_url="https://discord.com/webhooks/test")
        sender = ScheduledReportSender(
            report_generator=generator,
            notifiers=[notifier],
            enabled=True
        )

        # When: 스케줄러 시작
        await sender.start()

        # Then: 스케줄러가 실행 중이어야 함
        assert sender._task is not None
        assert not sender._task.done()

        # When: 스케줄러 중지
        await sender.stop()

        # Then: 스케줄러가 중지되어야 함
        assert sender._task.done() or sender._task.cancelled()
