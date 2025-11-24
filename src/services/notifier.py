"""알림 전송 서비스.

Discord, Email 등 다양한 채널을 통해 알림을 전송합니다.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional
import httpx
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from ..models.notification import Notification

logger = logging.getLogger(__name__)


class BaseNotifier(ABC):
    """알림 전송기의 기본 추상 클래스.

    모든 알림 전송기는 이 클래스를 상속받아 구현해야 합니다.
    """

    @abstractmethod
    async def send(self, notification: Notification) -> bool:
        """알림을 전송합니다.

        Args:
            notification: 전송할 알림 객체.

        Returns:
            전송 성공 여부 (True: 성공, False: 실패).
        """
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """알림 전송기가 올바르게 설정되었는지 확인합니다.

        Returns:
            설정 완료 여부 (True: 설정됨, False: 미설정).
        """
        pass


class DiscordNotifier(BaseNotifier):
    """Discord 웹훅을 통한 알림 전송기.

    Discord 채널에 웹훅을 통해 알림 메시지를 전송합니다.

    Attributes:
        webhook_url: Discord 웹훅 URL.
        timeout: HTTP 요청 타임아웃 (초).
    """

    def __init__(self, webhook_url: Optional[str] = None, timeout: float = 10.0):
        """Discord 알림 전송기를 초기화합니다.

        Args:
            webhook_url: Discord 웹훅 URL. None인 경우 알림 전송이 비활성화됩니다.
            timeout: HTTP 요청 타임아웃 (초). 기본값: 10.0초.
        """
        self.webhook_url = webhook_url
        self.timeout = timeout

    def is_configured(self) -> bool:
        """Discord 웹훅이 설정되어 있는지 확인합니다.

        Returns:
            webhook_url이 설정된 경우 True, 그렇지 않으면 False.
        """
        return self.webhook_url is not None and len(self.webhook_url.strip()) > 0

    async def send(self, notification: Notification) -> bool:
        """Discord 웹훅으로 알림을 전송합니다.

        Discord Embed 형식으로 메시지를 구성하여 전송합니다.

        Args:
            notification: 전송할 알림 객체.

        Returns:
            전송 성공 시 True, 실패 시 False.
        """
        if not self.is_configured():
            logger.warning("Discord 웹훅이 설정되지 않았습니다. 알림을 전송하지 않습니다.")
            return False

        # Discord Embed 형식으로 메시지 구성
        embed = {
            "title": notification.title,
            "description": notification.message,
            "color": self._get_color_for_type(notification.notification_type),
            "timestamp": notification.created_at.isoformat(),
            "footer": {"text": f"알림 ID: {notification.notification_id}"},
        }

        # 메타데이터가 있으면 필드로 추가
        if notification.metadata:
            fields = []
            for key, value in notification.metadata.items():
                fields.append({"name": key, "value": str(value), "inline": True})
            embed["fields"] = fields

        payload = {"embeds": [embed]}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.webhook_url, json=payload)
                response.raise_for_status()

            logger.info(
                f"Discord 알림 전송 성공: {notification.title} "
                f"(ID: {notification.notification_id})"
            )
            return True

        except httpx.HTTPError as e:
            logger.error(
                f"Discord 알림 전송 실패: {notification.title} "
                f"(ID: {notification.notification_id}), 오류: {e}"
            )
            return False

        except Exception as e:
            logger.error(
                f"Discord 알림 전송 중 예기치 않은 오류 발생: {e}",
                exc_info=True,
            )
            return False

    def _get_color_for_type(self, notification_type: str) -> int:
        """알림 유형에 따른 Embed 색상을 반환합니다.

        Args:
            notification_type: 알림 유형.

        Returns:
            Discord Embed 색상 코드 (정수).
        """
        color_map = {
            "ORDER_FILLED": 0x00FF00,  # 녹색 (주문 체결)
            "ERROR": 0xFF0000,  # 빨간색 (오류)
            "DAILY_REPORT": 0x0099FF,  # 파란색 (일일 리포트)
            "SYSTEM_STATUS": 0xFFFF00,  # 노란색 (시스템 상태)
            "RISK_ALERT": 0xFF6600,  # 주황색 (위험 경고)
        }
        return color_map.get(notification_type, 0x808080)  # 기본값: 회색


class EmailNotifier(BaseNotifier):
    """이메일을 통한 알림 전송기.

    SMTP를 사용하여 이메일로 알림을 전송합니다.

    Attributes:
        smtp_host: SMTP 서버 호스트.
        smtp_port: SMTP 서버 포트.
        smtp_user: SMTP 사용자명.
        smtp_password: SMTP 비밀번호.
        from_email: 발신자 이메일 주소.
        to_emails: 수신자 이메일 주소 리스트.
        use_tls: TLS 사용 여부.
        timeout: SMTP 연결 타임아웃 (초).
    """

    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: int = 587,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
        from_email: Optional[str] = None,
        to_emails: Optional[list[str]] = None,
        use_tls: bool = True,
        timeout: float = 30.0,
    ):
        """이메일 알림 전송기를 초기화합니다.

        Args:
            smtp_host: SMTP 서버 호스트.
            smtp_port: SMTP 서버 포트. 기본값: 587 (TLS).
            smtp_user: SMTP 사용자명.
            smtp_password: SMTP 비밀번호.
            from_email: 발신자 이메일 주소.
            to_emails: 수신자 이메일 주소 리스트.
            use_tls: TLS 사용 여부. 기본값: True.
            timeout: SMTP 연결 타임아웃 (초). 기본값: 30.0초.
        """
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.from_email = from_email
        self.to_emails = to_emails or []
        self.use_tls = use_tls
        self.timeout = timeout

    def is_configured(self) -> bool:
        """이메일 설정이 완료되었는지 확인합니다.

        Returns:
            모든 필수 설정이 완료된 경우 True, 그렇지 않으면 False.
        """
        return (
            self.smtp_host is not None
            and self.smtp_user is not None
            and self.smtp_password is not None
            and self.from_email is not None
            and len(self.to_emails) > 0
        )

    async def send(self, notification: Notification) -> bool:
        """이메일로 알림을 전송합니다.

        HTML 형식의 이메일을 생성하여 전송합니다.

        Args:
            notification: 전송할 알림 객체.

        Returns:
            전송 성공 시 True, 실패 시 False.
        """
        if not self.is_configured():
            logger.warning("이메일 설정이 완료되지 않았습니다. 알림을 전송하지 않습니다.")
            return False

        try:
            # 이메일 메시지 생성
            message = MIMEMultipart("alternative")
            message["Subject"] = notification.title
            message["From"] = self.from_email
            message["To"] = ", ".join(self.to_emails)

            # HTML 본문 생성
            html_body = self._create_html_body(notification)
            html_part = MIMEText(html_body, "html", "utf-8")
            message.attach(html_part)

            # SMTP 서버로 전송
            await aiosmtplib.send(
                message,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user,
                password=self.smtp_password,
                use_tls=self.use_tls,
                timeout=self.timeout,
            )

            logger.info(
                f"이메일 알림 전송 성공: {notification.title} "
                f"(ID: {notification.notification_id})"
            )
            return True

        except aiosmtplib.SMTPException as e:
            logger.error(
                f"이메일 알림 전송 실패: {notification.title} "
                f"(ID: {notification.notification_id}), 오류: {e}"
            )
            return False

        except Exception as e:
            logger.error(
                f"이메일 알림 전송 중 예기치 않은 오류 발생: {e}",
                exc_info=True,
            )
            return False

    def _create_html_body(self, notification: Notification) -> str:
        """알림 객체로부터 HTML 이메일 본문을 생성합니다.

        Args:
            notification: 알림 객체.

        Returns:
            HTML 형식의 이메일 본문.
        """
        # 기본 HTML 템플릿
        html = f"""
        <html>
        <head>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                    border: 1px solid #ddd;
                    border-radius: 5px;
                }}
                .header {{
                    background-color: {self._get_bg_color_for_type(notification.notification_type)};
                    color: white;
                    padding: 10px;
                    border-radius: 5px 5px 0 0;
                }}
                .content {{
                    padding: 20px;
                    background-color: #f9f9f9;
                }}
                .metadata {{
                    margin-top: 20px;
                    padding: 10px;
                    background-color: #e9e9e9;
                    border-radius: 5px;
                }}
                .footer {{
                    margin-top: 20px;
                    padding: 10px;
                    text-align: center;
                    color: #666;
                    font-size: 12px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>{notification.title}</h2>
                </div>
                <div class="content">
                    <p>{notification.message}</p>
        """

        # 메타데이터가 있으면 추가
        if notification.metadata:
            html += '<div class="metadata"><h3>상세 정보</h3><ul>'
            for key, value in notification.metadata.items():
                html += f"<li><strong>{key}:</strong> {value}</li>"
            html += "</ul></div>"

        # 푸터 추가
        html += f"""
                </div>
                <div class="footer">
                    <p>알림 ID: {notification.notification_id}</p>
                    <p>생성 시간: {notification.created_at.strftime('%Y-%m-%d %H:%M:%S KST')}</p>
                </div>
            </div>
        </body>
        </html>
        """

        return html

    def _get_bg_color_for_type(self, notification_type: str) -> str:
        """알림 유형에 따른 배경색을 반환합니다.

        Args:
            notification_type: 알림 유형.

        Returns:
            CSS 색상 코드.
        """
        color_map = {
            "ORDER_FILLED": "#28a745",  # 녹색 (주문 체결)
            "ERROR": "#dc3545",  # 빨간색 (오류)
            "DAILY_REPORT": "#007bff",  # 파란색 (일일 리포트)
            "SYSTEM_STATUS": "#ffc107",  # 노란색 (시스템 상태)
            "RISK_ALERT": "#fd7e14",  # 주황색 (위험 경고)
        }
        return color_map.get(notification_type, "#6c757d")  # 기본값: 회색


class NotificationManager:
    """여러 알림 채널을 통합 관리하는 매니저.

    Discord, Email 등 여러 알림 채널을 한 번에 관리하고 전송합니다.

    Attributes:
        notifiers: 등록된 알림 전송기 리스트.
    """

    def __init__(self):
        """알림 매니저를 초기화합니다."""
        self.notifiers: list[BaseNotifier] = []

    def add_notifier(self, notifier: BaseNotifier) -> None:
        """알림 전송기를 추가합니다.

        Args:
            notifier: 추가할 알림 전송기.
        """
        if notifier.is_configured():
            self.notifiers.append(notifier)
            logger.info(f"{notifier.__class__.__name__} 알림 전송기가 추가되었습니다.")
        else:
            logger.warning(
                f"{notifier.__class__.__name__} 알림 전송기가 설정되지 않아 "
                f"추가되지 않았습니다."
            )

    async def send(self, notification: Notification) -> dict[str, bool]:
        """등록된 모든 알림 전송기로 알림을 전송합니다.

        Args:
            notification: 전송할 알림 객체.

        Returns:
            각 알림 전송기의 전송 결과를 담은 딕셔너리.
            키: 알림 전송기 클래스명, 값: 전송 성공 여부.
        """
        if not self.notifiers:
            logger.warning("등록된 알림 전송기가 없습니다. 알림을 전송하지 않습니다.")
            return {}

        results = {}

        for notifier in self.notifiers:
            notifier_name = notifier.__class__.__name__
            try:
                success = await notifier.send(notification)
                results[notifier_name] = success
            except Exception as e:
                logger.error(
                    f"{notifier_name} 알림 전송 중 오류 발생: {e}",
                    exc_info=True,
                )
                results[notifier_name] = False

        # 전송 완료 여부 판단 (하나라도 성공하면 sent=True)
        if any(results.values()):
            notification.mark_as_sent()

        return results

    async def send_order_filled(
        self,
        stock_name: str,
        order_type: str,
        quantity: int,
        price: str,
        order_id: str,
    ) -> dict[str, bool]:
        """주문 체결 알림을 전송합니다.

        Args:
            stock_name: 종목명.
            order_type: 주문 유형 (BUY/SELL).
            quantity: 체결 수량.
            price: 체결 가격.
            order_id: 주문 ID.

        Returns:
            각 알림 전송기의 전송 결과.
        """
        notification = Notification(
            notification_type="ORDER_FILLED",
            title=f"{'매수' if order_type == 'BUY' else '매도'} 주문 체결",
            message=f"{stock_name} {quantity}주가 {price}원에 {order_type.lower()} 체결되었습니다.",
            metadata={
                "종목명": stock_name,
                "주문유형": order_type,
                "수량": quantity,
                "가격": price,
                "주문ID": order_id,
            },
        )
        return await self.send(notification)

    async def send_error_alert(self, error_message: str, context: str) -> dict[str, bool]:
        """오류 경고 알림을 전송합니다.

        Args:
            error_message: 오류 메시지.
            context: 오류 발생 컨텍스트.

        Returns:
            각 알림 전송기의 전송 결과.
        """
        notification = Notification(
            notification_type="ERROR",
            title="시스템 오류 발생",
            message=f"오류가 발생했습니다: {error_message}",
            metadata={"오류메시지": error_message, "컨텍스트": context},
        )
        return await self.send(notification)

    async def send_risk_alert(
        self, alert_type: str, message: str, metadata: dict
    ) -> dict[str, bool]:
        """위험 경고 알림을 전송합니다.

        Args:
            alert_type: 경고 유형.
            message: 경고 메시지.
            metadata: 추가 메타데이터.

        Returns:
            각 알림 전송기의 전송 결과.
        """
        notification = Notification(
            notification_type="RISK_ALERT",
            title=f"위험 경고: {alert_type}",
            message=message,
            metadata=metadata,
        )
        return await self.send(notification)

    async def send_daily_report(self, report_content: str, metadata: dict) -> dict[str, bool]:
        """일일 트레이딩 리포트를 전송합니다.

        Args:
            report_content: 리포트 내용.
            metadata: 리포트 메타데이터.

        Returns:
            각 알림 전송기의 전송 결과.
        """
        notification = Notification(
            notification_type="DAILY_REPORT",
            title="일일 트레이딩 리포트",
            message=report_content,
            metadata=metadata,
        )
        return await self.send(notification)

    async def send_system_status(self, status: str, message: str) -> dict[str, bool]:
        """시스템 상태 알림을 전송합니다.

        Args:
            status: 시스템 상태.
            message: 상태 메시지.

        Returns:
            각 알림 전송기의 전송 결과.
        """
        notification = Notification(
            notification_type="SYSTEM_STATUS",
            title=f"시스템 상태: {status}",
            message=message,
            metadata={"상태": status},
        )
        return await self.send(notification)
