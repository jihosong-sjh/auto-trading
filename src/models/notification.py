"""Notification 모델 정의."""

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from . import NotificationType

KST = ZoneInfo("Asia/Seoul")


class Notification(BaseModel):
    """알림 메시지.

    사용자에게 전송되는 알림을 관리합니다.

    Attributes:
        notification_id: 알림 고유 ID (UUID).
        notification_type: 알림 유형.
        title: 알림 제목.
        message: 알림 내용.
        metadata: 추가 메타데이터.
        sent: 전송 완료 여부.
        created_at: 알림 생성 시간 (KST).
        sent_at: 전송 완료 시간 (KST).
    """

    notification_id: str = Field(
        default_factory=lambda: str(uuid4()), description="알림 ID"
    )
    notification_type: NotificationType = Field(..., description="알림 유형")
    title: str = Field(..., min_length=1, max_length=100, description="알림 제목")
    message: str = Field(..., min_length=1, max_length=1000, description="알림 내용")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="메타데이터")
    sent: bool = Field(default=False, description="전송 여부")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=KST), description="생성 시간"
    )
    sent_at: Optional[datetime] = Field(None, description="전송 시간")

    def mark_as_sent(self) -> None:
        """알림을 전송 완료 상태로 표시."""
        self.sent = True
        self.sent_at = datetime.now(tz=KST)

    class Config:
        """Pydantic 설정."""

        frozen = False
        use_enum_values = True
        json_encoders = {datetime: lambda v: v.isoformat()}
