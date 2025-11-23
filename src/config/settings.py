"""Pydantic Settings 기반 설정 관리.

환경 변수와 YAML 파일을 통한 설정을 관리합니다.
"""

import yaml
from pathlib import Path
from typing import List, Optional
from decimal import Decimal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StrategyConfig(BaseModel):
    """전략 설정 모델.

    Attributes:
        strategy_name: 전략 고유 이름.
        strategy_class: 전략 클래스 경로 (예: src.strategies.golden_cross.GoldenCrossStrategy).
        enabled: 전략 활성화 여부.
        symbols: 전략이 감시할 종목 코드 목록.
        params: 전략별 파라미터.
    """
    strategy_name: str = Field(..., description="전략 이름")
    strategy_class: str = Field(..., description="전략 클래스 경로")
    enabled: bool = Field(default=True, description="전략 활성화 여부")
    symbols: List[str] = Field(default_factory=list, description="감시 종목 코드")
    params: dict = Field(default_factory=dict, description="전략 파라미터")


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
    kiwoom_trading_mode: str = Field(
        default="virtual", description="투자 구분 (real: 실전투자, virtual: 모의투자)"
    )
    kiwoom_api_base_url: Optional[str] = Field(
        default=None, description="키움증권 API Base URL (미지정 시 trading_mode에 따라 자동 선택)",
        alias="kiwoom_api_url"  # Backward compatibility
    )
    kiwoom_api_key: Optional[str] = Field(
        default=None, description="키움증권 API 키"
    )
    kiwoom_api_secret: Optional[str] = Field(
        default=None, description="키움증권 API 시크릿"
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

    # 전략 및 종목 설정
    watch_symbols: List[str] = Field(
        default_factory=lambda: ["005930", "000660", "035420", "051910"],
        description="감시 대상 종목 코드 목록"
    )
    strategies: List[StrategyConfig] = Field(
        default_factory=list, description="전략 설정 목록"
    )

    def get_kiwoom_api_url(self) -> str:
        """투자 구분에 따른 Kiwoom API URL 반환.

        Returns:
            Kiwoom API URL.
        """
        if self.kiwoom_api_base_url:
            return self.kiwoom_api_base_url

        # trading_mode에 따라 자동 선택
        if self.kiwoom_trading_mode == "real":
            return "https://api.kiwoom.com"
        else:  # virtual (default)
            return "https://mockapi.kiwoom.com"

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

    @classmethod
    def from_yaml(cls, config_path: str) -> "Settings":
        """YAML 파일에서 설정을 로드합니다.

        Args:
            config_path: YAML 설정 파일 경로.

        Returns:
            Settings 인스턴스.

        Raises:
            FileNotFoundError: 설정 파일이 없는 경우.
        """
        path = Path(config_path)

        # YAML 파일이 없으면 .env에서 기본 설정 로드
        if not path.exists():
            settings = cls()
            # 기본 전략 설정 추가 (골든크로스 전략)
            if not settings.strategies:
                settings.strategies = [
                    StrategyConfig(
                        strategy_name="golden_cross",
                        strategy_class="src.strategies.golden_cross.GoldenCrossStrategy",
                        enabled=True,
                        symbols=settings.watch_symbols,
                        params={
                            "short_period": 5,
                            "long_period": 20,
                            "position_size_ratio": 0.2
                        }
                    )
                ]
            return settings

        # YAML 파일에서 설정 로드
        with open(path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}

        # 전략 설정 파싱
        strategies = []
        if "strategies" in config_data:
            for strategy_data in config_data["strategies"]:
                strategies.append(StrategyConfig(**strategy_data))

        # .env에서 기본 설정 로드 후 YAML 값으로 오버라이드
        settings = cls()
        for key, value in config_data.items():
            if key != "strategies" and hasattr(settings, key):
                setattr(settings, key, value)

        if strategies:
            settings.strategies = strategies

        return settings


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
