"""DiscordNotifier 및 EmailNotifier 단위 테스트."""

import pytest
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.notifier import (
    DiscordNotifier,
    EmailNotifier,
    NotificationManager,
)
from src.models.notification import Notification, NotificationType

KST = ZoneInfo("Asia/Seoul")


class TestDiscordNotifier:
    """DiscordNotifier 단위 테스트."""

    def test_is_configured_with_valid_webhook(self):
        """유효한 웹훅 URL이 있을 때 is_configured가 True를 반환하는지 테스트."""
        notifier = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/test")
        assert notifier.is_configured() is True

    def test_is_configured_without_webhook(self):
        """웹훅 URL이 없을 때 is_configured가 False를 반환하는지 테스트."""
        notifier = DiscordNotifier(webhook_url=None)
        assert notifier.is_configured() is False

    def test_is_configured_with_empty_webhook(self):
        """빈 웹훅 URL일 때 is_configured가 False를 반환하는지 테스트."""
        notifier = DiscordNotifier(webhook_url="")
        assert notifier.is_configured() is False

        notifier2 = DiscordNotifier(webhook_url="   ")
        assert notifier2.is_configured() is False

    @pytest.mark.asyncio
    async def test_send_without_configuration(self):
        """웹훅이 설정되지 않았을 때 send가 False를 반환하는지 테스트."""
        notifier = DiscordNotifier(webhook_url=None)
        notification = Notification(
            notification_type=NotificationType.ORDER_FILLED,
            title="Test Notification",
            message="Test message"
        )

        result = await notifier.send(notification)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        """웹훅 전송 성공 시 True를 반환하는지 테스트."""
        notifier = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/test")
        notification = Notification(
            notification_type=NotificationType.ORDER_FILLED,
            title="Order Filled",
            message="Your order has been filled"
        )

        # httpx.AsyncClient.post를 모킹
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_post.return_value = mock_response

            result = await notifier.send(notification)

            assert result is True
            mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_failure_http_error(self):
        """웹훅 전송 실패 시 False를 반환하는지 테스트."""
        notifier = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/test")
        notification = Notification(
            notification_type=NotificationType.ERROR,
            title="Error",
            message="An error occurred"
        )

        # httpx.AsyncClient.post를 모킹하여 에러 응답 시뮬레이션
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_post.return_value = mock_response

            result = await notifier.send(notification)

            assert result is False

    @pytest.mark.asyncio
    async def test_send_with_metadata(self):
        """메타데이터가 포함된 알림을 전송할 수 있는지 테스트."""
        notifier = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/test")
        notification = Notification(
            notification_type=NotificationType.ORDER_FILLED,
            title="Order Filled",
            message="Samsung Electronics order filled",
            metadata={
                "stock_code": "005930",
                "quantity": 100,
                "price": "72000.00"
            }
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_post.return_value = mock_response

            result = await notifier.send(notification)

            assert result is True
            # POST 호출 시 메타데이터가 포함되었는지 확인
            call_args = mock_post.call_args
            json_data = call_args.kwargs.get("json", {})
            embeds = json_data.get("embeds", [])
            assert len(embeds) > 0
            fields = embeds[0].get("fields", [])
            assert len(fields) > 0

    @pytest.mark.asyncio
    async def test_send_timeout_handling(self):
        """타임아웃 발생 시 False를 반환하는지 테스트."""
        notifier = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/test", timeout=0.1)
        notification = Notification(
            notification_type=NotificationType.SYSTEM_STATUS,
            title="System Status",
            message="System is running"
        )

        # httpx.AsyncClient.post를 모킹하여 타임아웃 시뮬레이션
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            import httpx
            mock_post.side_effect = httpx.TimeoutException("Request timed out")

            result = await notifier.send(notification)

            assert result is False


class TestEmailNotifier:
    """EmailNotifier 단위 테스트."""

    def test_is_configured_with_all_settings(self):
        """모든 설정이 있을 때 is_configured가 True를 반환하는지 테스트."""
        notifier = EmailNotifier(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test@example.com",
            smtp_password="password",
            from_addr="test@example.com",
            to_addrs=["recipient@example.com"]
        )
        assert notifier.is_configured() is True

    def test_is_configured_without_host(self):
        """호스트가 없을 때 is_configured가 False를 반환하는지 테스트."""
        notifier = EmailNotifier(
            smtp_host=None,
            smtp_port=587,
            smtp_user="test@example.com",
            smtp_password="password",
            from_addr="test@example.com",
            to_addrs=["recipient@example.com"]
        )
        assert notifier.is_configured() is False

    def test_is_configured_without_recipients(self):
        """수신자가 없을 때 is_configured가 False를 반환하는지 테스트."""
        notifier = EmailNotifier(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test@example.com",
            smtp_password="password",
            from_addr="test@example.com",
            to_addrs=[]
        )
        assert notifier.is_configured() is False

    @pytest.mark.asyncio
    async def test_send_without_configuration(self):
        """설정이 없을 때 send가 False를 반환하는지 테스트."""
        notifier = EmailNotifier(
            smtp_host=None,
            smtp_port=587,
            smtp_user=None,
            smtp_password=None,
            from_addr=None,
            to_addrs=[]
        )
        notification = Notification(
            notification_type=NotificationType.DAILY_REPORT,
            title="Daily Report",
            message="Report content"
        )

        result = await notifier.send(notification)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        """이메일 전송 성공 시 True를 반환하는지 테스트."""
        notifier = EmailNotifier(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test@example.com",
            smtp_password="password",
            from_addr="test@example.com",
            to_addrs=["recipient@example.com"]
        )
        notification = Notification(
            notification_type=NotificationType.DAILY_REPORT,
            title="Daily Trading Report",
            message="Today's trading summary"
        )

        # aiosmtplib.SMTP를 모킹
        with patch("aiosmtplib.SMTP") as mock_smtp_class:
            mock_smtp = AsyncMock()
            mock_smtp_class.return_value = mock_smtp
            mock_smtp.__aenter__.return_value = mock_smtp
            mock_smtp.__aexit__.return_value = None

            result = await notifier.send(notification)

            assert result is True
            mock_smtp.connect.assert_called_once()
            mock_smtp.starttls.assert_called_once()
            mock_smtp.login.assert_called_once_with("test@example.com", "password")
            mock_smtp.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_failure_smtp_error(self):
        """SMTP 에러 발생 시 False를 반환하는지 테스트."""
        notifier = EmailNotifier(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test@example.com",
            smtp_password="wrong_password",
            from_addr="test@example.com",
            to_addrs=["recipient@example.com"]
        )
        notification = Notification(
            notification_type=NotificationType.ERROR,
            title="Error Alert",
            message="An error occurred"
        )

        # aiosmtplib.SMTP를 모킹하여 에러 시뮬레이션
        with patch("aiosmtplib.SMTP") as mock_smtp_class:
            mock_smtp = AsyncMock()
            mock_smtp_class.return_value = mock_smtp
            mock_smtp.__aenter__.return_value = mock_smtp
            mock_smtp.__aexit__.return_value = None
            mock_smtp.login.side_effect = Exception("Authentication failed")

            result = await notifier.send(notification)

            assert result is False

    @pytest.mark.asyncio
    async def test_send_html_email(self):
        """HTML 이메일 전송 테스트."""
        notifier = EmailNotifier(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test@example.com",
            smtp_password="password",
            from_addr="test@example.com",
            to_addrs=["recipient@example.com"]
        )
        notification = Notification(
            notification_type=NotificationType.DAILY_REPORT,
            title="Daily Report",
            message="Plain text report",
            metadata={
                "html_report": "<html><body><h1>Report</h1></body></html>"
            }
        )

        with patch("aiosmtplib.SMTP") as mock_smtp_class:
            mock_smtp = AsyncMock()
            mock_smtp_class.return_value = mock_smtp
            mock_smtp.__aenter__.return_value = mock_smtp
            mock_smtp.__aexit__.return_value = None

            result = await notifier.send(notification)

            assert result is True
            # send_message가 호출되었는지 확인
            mock_smtp.send_message.assert_called_once()
            # 호출된 메시지 확인 (HTML 포함)
            call_args = mock_smtp.send_message.call_args
            message = call_args[0][0]
            assert message.is_multipart()


class TestNotificationManager:
    """NotificationManager 단위 테스트."""

    @pytest.mark.asyncio
    async def test_send_to_all_notifiers(self):
        """모든 알림 전송기로 알림을 전송하는지 테스트."""
        # 모킹된 알림 전송기 생성
        discord_notifier = DiscordNotifier(webhook_url="https://discord.com/webhooks/test")
        email_notifier = EmailNotifier(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test@example.com",
            smtp_password="password",
            from_addr="test@example.com",
            to_addrs=["recipient@example.com"]
        )

        manager = NotificationManager(notifiers=[discord_notifier, email_notifier])

        notification = Notification(
            notification_type=NotificationType.ORDER_FILLED,
            title="Order Filled",
            message="Your order has been filled"
        )

        # 두 알림 전송기 모두 모킹
        with patch.object(discord_notifier, 'send', new_callable=AsyncMock) as mock_discord_send, \
             patch.object(email_notifier, 'send', new_callable=AsyncMock) as mock_email_send:

            mock_discord_send.return_value = True
            mock_email_send.return_value = True

            result = await manager.send_notification(notification)

            assert result is True
            mock_discord_send.assert_called_once_with(notification)
            mock_email_send.assert_called_once_with(notification)

    @pytest.mark.asyncio
    async def test_send_with_partial_failure(self):
        """일부 알림 전송기만 성공했을 때의 동작 테스트."""
        discord_notifier = DiscordNotifier(webhook_url="https://discord.com/webhooks/test")
        email_notifier = EmailNotifier(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test@example.com",
            smtp_password="password",
            from_addr="test@example.com",
            to_addrs=["recipient@example.com"]
        )

        manager = NotificationManager(notifiers=[discord_notifier, email_notifier])

        notification = Notification(
            notification_type=NotificationType.RISK_ALERT,
            title="Risk Alert",
            message="Daily loss limit approaching"
        )

        with patch.object(discord_notifier, 'send', new_callable=AsyncMock) as mock_discord_send, \
             patch.object(email_notifier, 'send', new_callable=AsyncMock) as mock_email_send:

            mock_discord_send.return_value = True
            mock_email_send.return_value = False

            result = await manager.send_notification(notification)

            # 적어도 하나가 성공했으므로 True
            assert result is True

    @pytest.mark.asyncio
    async def test_send_all_failed(self):
        """모든 알림 전송기가 실패했을 때 False를 반환하는지 테스트."""
        discord_notifier = DiscordNotifier(webhook_url="https://discord.com/webhooks/test")
        email_notifier = EmailNotifier(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test@example.com",
            smtp_password="password",
            from_addr="test@example.com",
            to_addrs=["recipient@example.com"]
        )

        manager = NotificationManager(notifiers=[discord_notifier, email_notifier])

        notification = Notification(
            notification_type=NotificationType.ERROR,
            title="Error",
            message="System error"
        )

        with patch.object(discord_notifier, 'send', new_callable=AsyncMock) as mock_discord_send, \
             patch.object(email_notifier, 'send', new_callable=AsyncMock) as mock_email_send:

            mock_discord_send.return_value = False
            mock_email_send.return_value = False

            result = await manager.send_notification(notification)

            assert result is False
