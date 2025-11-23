"""SystemStatus 모델 정의."""

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, List
from zoneinfo import ZoneInfo

from . import SystemMode, MarketPhase

KST = ZoneInfo("Asia/Seoul")


class SystemStatus(BaseModel):
    """시스템 상태.

    시스템의 운영 상태 및 헬스 체크 정보를 관리합니다.

    Attributes:
        system_mode: 시스템 운영 모드.
        market_phase: 현재 시장 상태.
        api_connected: API 연결 상태.
        last_data_received_at: 마지막 데이터 수신 시간.
        active_strategies: 활성 전략 목록.
        error_count: 오류 발생 횟수 (누적).
        last_error_message: 마지막 오류 메시지.
        uptime_seconds: 시스템 가동 시간 (초).
        updated_at: 마지막 업데이트 시간.
    """

    system_mode: SystemMode = Field(
        default=SystemMode.STARTING, description="시스템 모드"
    )
    market_phase: MarketPhase = Field(
        default=MarketPhase.PRE_MARKET, description="시장 상태"
    )
    api_connected: bool = Field(default=False, description="API 연결 상태")
    last_data_received_at: Optional[datetime] = Field(
        None, description="마지막 데이터 수신 시간"
    )
    active_strategies: List[str] = Field(
        default_factory=list, description="활성 전략 목록"
    )
    error_count: int = Field(default=0, ge=0, description="오류 발생 횟수")
    last_error_message: Optional[str] = Field(
        None, max_length=500, description="마지막 오류 메시지"
    )
    uptime_seconds: int = Field(default=0, ge=0, description="가동 시간 (초)")
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=KST), description="업데이트 시간"
    )

    def is_healthy(self) -> bool:
        """시스템 정상 상태 확인.

        Returns:
            API 연결, RUNNING 모드, 최근 데이터 수신 확인 시 True.
        """
        if not self.api_connected:
            return False

        if self.system_mode != SystemMode.RUNNING:
            return False

        if self.last_data_received_at:
            time_since_data = datetime.now(tz=KST) - self.last_data_received_at
            if time_since_data.total_seconds() > 300:
                return False

        return True

    def record_error(self, error_message: str) -> None:
        """오류 발생 기록.

        Args:
            error_message: 오류 메시지.
        """
        self.error_count += 1
        self.last_error_message = error_message[:500]
        self.updated_at = datetime.now(tz=KST)

    def update_data_received(self) -> None:
        """마지막 데이터 수신 시간 업데이트."""
        self.last_data_received_at = datetime.now(tz=KST)
        self.updated_at = datetime.now(tz=KST)

    class Config:
        """Pydantic 설정."""

        frozen = False
        use_enum_values = True
        json_encoders = {datetime: lambda v: v.isoformat()}
