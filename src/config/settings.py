"""Pydantic Settings 기반 설정 관리.

환경 변수와 YAML 파일을 통한 설정을 관리합니다.
"""

from pathlib import Path
from typing import List, Optional
from decimal import Decimal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """애플리케이션 설정.

    환경 변수(.env) 및 기본값을 통해 설정을 로드합니다.

    Attributes:
        app_name: 애플리케이션 이름.
        debug: 디버그 모드 활성화 여부.
        log_level: 로그 레벨.
        log_dir: 로그 디렉토리 경로.
        data_dir: 데이터 디렉토리 경로.
        db_path: SQLite 데이터베이스 파일 경로.
        kiwoom_api_url: 키움증권 API URL.
        kiwoom_api_key: 키움증권 API 키.
        kiwoom_account_number: 계좌번호.
        initial_balance: 초기 예수금 (시뮬레이터용).
        daily_loss_limit: 일일 손실 한도.
        max_position_concentration: 종목별 최대 집중도.
        discord_webhook_url: 디스코드 웹훅 URL (선택).
        email_smtp_server: SMTP 서버 주소 (선택).
        email_smtp_port: SMTP 포트 (선택).
        email_sender: 발신 이메일 주소 (선택).
        email_password: 이메일 비밀번호 (선택).
        email_recipients: 수신자 이메일 목록 (선택).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 애플리케이션 기본 설정
    app_name: str = Field(default="Kiwoom Auto Trading", description="애플리케이션 이름")
    debug: bool = Field(default=False, description="디버그 모드")
    log_level: str = Field(default="INFO", description="로그 레벨")
    log_dir: Path = Field(default=Path("logs"), description="로그 디렉토리")
    data_dir: Path = Field(default=Path("data"), description="데이터 디렉토리")
    db_path: Path = Field(
        default=Path("data/trading.db"), description="SQLite DB 경로"
    )

    # 키움증권 API 설정
    kiwoom_api_url: str = Field(
        default="https://openapi.kiwoom.com", description="키움증권 API URL"
    )
    kiwoom_api_key: Optional[str] = Field(
        default=None, description="키움증권 API 키"
    )
    kiwoom_account_number: Optional[str] = Field(
        default=None, description="계좌번호 (8자리)"
    )

    # 시뮬레이터 설정
    initial_balance: Decimal = Field(
        default=Decimal("10000000"), description="초기 예수금 (시뮬레이터용)"
    )

    # 위험 관리 설정
    daily_loss_limit: Decimal = Field(
        default=Decimal("500000"), description="일일 손실 한도 (원)"
    )
    max_position_concentration: Decimal = Field(
        default=Decimal("0.3"), description="종목별 최대 집중도 (30%)"
    )

    # 알림 설정 (Discord)
    discord_webhook_url: Optional[str] = Field(
        default=None, description="디스코드 웹훅 URL"
    )

    # 알림 설정 (Email)
    email_smtp_server: Optional[str] = Field(
        default=None, description="SMTP 서버 주소 (예: smtp.gmail.com)"
    )
    email_smtp_port: Optional[int] = Field(
        default=587, description="SMTP 포트"
    )
    email_sender: Optional[str] = Field(
        default=None, description="발신 이메일 주소"
    )
    email_password: Optional[str] = Field(
        default=None, description="이메일 비밀번호"
    )
    email_recipients: List[str] = Field(
        default_factory=list, description="수신자 이메일 목록"
    )

    def is_production_mode(self) -> bool:
        """프로덕션 모드 여부 확인.

        Returns:
            Kiwoom API 키와 계좌번호가 설정되어 있으면 True.
        """
        return self.kiwoom_api_key is not None and self.kiwoom_account_number is not None

    def is_simulator_mode(self) -> bool:
        """시뮬레이터 모드 여부 확인.

        Returns:
            프로덕션 모드가 아니면 True.
        """
        return not self.is_production_mode()

    def is_discord_enabled(self) -> bool:
        """디스코드 알림 활성화 여부 확인.

        Returns:
            디스코드 웹훅 URL이 설정되어 있으면 True.
        """
        return self.discord_webhook_url is not None

    def is_email_enabled(self) -> bool:
        """이메일 알림 활성화 여부 확인.

        Returns:
            SMTP 서버와 발신 이메일이 설정되어 있으면 True.
        """
        return (
            self.email_smtp_server is not None
            and self.email_sender is not None
            and self.email_password is not None
            and len(self.email_recipients) > 0
        )

    def ensure_directories(self) -> None:
        """필요한 디렉토리 생성.

        로그 및 데이터 디렉토리를 생성합니다.
        """
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)


# 싱글톤 인스턴스
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """설정 싱글톤 인스턴스를 반환.

    Returns:
        설정 인스턴스.

    Example:
        >>> settings = get_settings()
        >>> print(settings.app_name)
        Kiwoom Auto Trading
    """
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.ensure_directories()
    return _settings
