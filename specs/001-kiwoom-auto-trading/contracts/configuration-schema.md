# 설정 파일 스키마 명세

**Feature Branch**: `001-kiwoom-auto-trading`
**Created**: 2025-11-22
**Status**: Draft
**Related**: [spec.md](../spec.md) | [data-model.md](../data-model.md)

## 개요

본 문서는 자동매매 시스템의 모든 설정 파일 스키마를 정의한다. YAML 형식을 사용하며, Pydantic을 통해 런타임 검증을 수행한다.

## 목차

1. [설정 파일 구조](#설정-파일-구조)
2. [config.yaml - 시스템 설정](#configyaml---시스템-설정)
3. [strategies.yaml - 전략 설정](#strategiesyaml---전략-설정)
4. [스키마 검증](#스키마-검증)
5. [환경 변수](#환경-변수)
6. [설정 로드 구현](#설정-로드-구현)

---

## 설정 파일 구조

```
config/
├── config.yaml          # 시스템 설정 (API 인증, 계좌 정보, 위험 관리)
├── strategies.yaml      # 전략 정의 및 파라미터
├── .env                 # 민감 정보 (API Key, Secret 등)
└── logging.yaml         # 로깅 설정 (선택적)
```

---

## config.yaml - 시스템 설정

### 전체 구조

```yaml
# 키움증권 REST API 기반 자동매매 시스템 설정
# Feature: 001-kiwoom-auto-trading

api:
  # API 인증 정보 (실제 값은 .env에서 로드)
  app_key: ${KIWOOM_APP_KEY}
  app_secret: ${KIWOOM_APP_SECRET}
  base_url: "https://openapi.kiwoom.com/api/v1"

  # Rate Limiting 설정
  rate_limits:
    price_per_second: 5
    chart_per_minute: 20
    order_per_second: 2
    account_per_minute: 10

  # 재시도 정책
  retry:
    max_retries: 3
    retry_delay_seconds: 1.0
    exponential_backoff: true

  # 타임아웃 설정
  timeout:
    connect_timeout_seconds: 10
    read_timeout_seconds: 30

account:
  # 거래 계좌 정보
  account_number: "12345678"
  account_name: "김철수 위탁계좌"

  # 초기 자금 (백테스팅 모드 시 사용)
  initial_capital: 10000000

risk_management:
  # 일일 손실 한도 (계좌 총 자산 대비 비율)
  daily_loss_limit_rate: 0.05  # 5%

  # 종목별 최대 집중도 (전체 포트폴리오 대비 비율)
  max_position_concentration: 0.30  # 30%

  # 손절/익절 기본 설정 (전략에서 오버라이드 가능)
  default_stop_loss_rate: 0.03  # -3%
  default_take_profit_rate: 0.05  # +5%

  # 총 위험 노출 한도 (투자 가능 금액 대비 실제 투자 금액 비율)
  max_risk_exposure: 0.80  # 80%

market_hours:
  # 한국 주식 시장 운영 시간 (KST)
  pre_market_start: "08:00"
  market_open: "09:00"
  market_close: "15:30"
  after_hours_end: "18:00"

  # 신규 매수 차단 시간 (장 마감 전)
  buy_order_cutoff_minutes: 10  # 15:20부터 신규 매수 차단

trading:
  # 운영 모드
  mode: "live"  # live, backtest, paper (paper는 향후 구현)

  # 감시 대상 종목 목록 (기본값, 전략에서 오버라이드 가능)
  default_watch_list:
    - "005930"  # 삼성전자
    - "000660"  # SK하이닉스
    - "035720"  # 카카오

  # 주문 실행 설정
  order_execution:
    # 기본 주문 유형 (MARKET, LIMIT)
    default_order_type: "LIMIT"

    # 시장가 주문 허용 여부
    allow_market_orders: true

    # 지정가 주문 유효 기간 (분)
    limit_order_validity_minutes: 60

    # 미체결 주문 자동 취소 시간 (분)
    cancel_unfilled_after_minutes: 120

data_collection:
  # 실시간 데이터 수집 간격 (초)
  realtime_interval_seconds: 1

  # 차트 데이터 캐시 설정
  chart_cache:
    enabled: true
    ttl_seconds: 300  # 5분
    max_items: 1000

  # 데이터 수신 타임아웃 (분)
  data_timeout_minutes: 3

notifications:
  # 알림 전송 채널
  enabled_channels:
    - "discord"
    - "email"

  # Discord 웹훅 설정
  discord:
    webhook_url: ${DISCORD_WEBHOOK_URL}
    enable_order_notifications: true
    enable_error_notifications: true
    enable_daily_report: true

  # 이메일 설정
  email:
    smtp_server: "smtp.gmail.com"
    smtp_port: 587
    sender_email: ${EMAIL_SENDER}
    sender_password: ${EMAIL_PASSWORD}
    recipient_emails:
      - "user@example.com"
    enable_order_notifications: false
    enable_error_notifications: true
    enable_daily_report: true

health_check:
  # 헬스 체크 실행 간격 (초)
  interval_seconds: 60

  # API 연결 체크 타임아웃 (초)
  api_check_timeout_seconds: 10

  # 데이터 신선도 체크 임계값 (분)
  data_freshness_threshold_minutes: 3

logging:
  # 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  level: "INFO"

  # 로그 출력 형식
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

  # 로그 파일 설정
  file:
    enabled: true
    path: "logs/trading.log"
    max_bytes: 10485760  # 10MB
    backup_count: 10

  # 콘솔 출력
  console:
    enabled: true

database:
  # SQLite 데이터베이스 경로
  sqlite_path: "data/trading.db"

  # 데이터 보관 기간 (일)
  retention_days:
    orders: 365
    chart_data: 180
    notifications: 90
```

### 스키마 정의 (Pydantic)

```python
from pydantic import BaseModel, Field, field_validator, HttpUrl
from typing import List, Optional
from decimal import Decimal

class APIConfig(BaseModel):
    """API configuration.

    Attributes:
        app_key: Kiwoom API app key.
        app_secret: Kiwoom API app secret.
        base_url: API base URL.
        rate_limits: Rate limit configuration.
        retry: Retry policy configuration.
        timeout: Timeout configuration.
    """
    app_key: str = Field(..., min_length=1, description="API app key")
    app_secret: str = Field(..., min_length=1, description="API app secret")
    base_url: HttpUrl = Field(default="https://openapi.kiwoom.com/api/v1")

    rate_limits: dict = Field(
        default_factory=lambda: {
            "price_per_second": 5,
            "chart_per_minute": 20,
            "order_per_second": 2,
            "account_per_minute": 10
        }
    )

    retry: dict = Field(
        default_factory=lambda: {
            "max_retries": 3,
            "retry_delay_seconds": 1.0,
            "exponential_backoff": True
        }
    )

    timeout: dict = Field(
        default_factory=lambda: {
            "connect_timeout_seconds": 10,
            "read_timeout_seconds": 30
        }
    )

class AccountConfig(BaseModel):
    """Account configuration.

    Attributes:
        account_number: 8-digit account number.
        account_name: Account display name.
        initial_capital: Initial capital for backtest mode.
    """
    account_number: str = Field(..., pattern=r"^\d{8}$")
    account_name: str = Field(..., min_length=1, max_length=50)
    initial_capital: Decimal = Field(default=Decimal("10000000"), gt=0)

class RiskManagementConfig(BaseModel):
    """Risk management configuration.

    Attributes:
        daily_loss_limit_rate: Daily loss limit as % of total assets.
        max_position_concentration: Max position size as % of portfolio.
        default_stop_loss_rate: Default stop-loss rate.
        default_take_profit_rate: Default take-profit rate.
        max_risk_exposure: Max risk exposure rate.
    """
    daily_loss_limit_rate: Decimal = Field(default=Decimal("0.05"), gt=0, le=1)
    max_position_concentration: Decimal = Field(default=Decimal("0.30"), gt=0, le=1)
    default_stop_loss_rate: Decimal = Field(default=Decimal("0.03"), gt=0, le=1)
    default_take_profit_rate: Decimal = Field(default=Decimal("0.05"), gt=0, le=1)
    max_risk_exposure: Decimal = Field(default=Decimal("0.80"), gt=0, le=1)

class MarketHoursConfig(BaseModel):
    """Market hours configuration.

    Attributes:
        pre_market_start: Pre-market start time (HH:MM).
        market_open: Market open time.
        market_close: Market close time.
        after_hours_end: After-hours end time.
        buy_order_cutoff_minutes: Minutes before close to stop buy orders.
    """
    pre_market_start: str = Field(default="08:00", pattern=r"^\d{2}:\d{2}$")
    market_open: str = Field(default="09:00", pattern=r"^\d{2}:\d{2}$")
    market_close: str = Field(default="15:30", pattern=r"^\d{2}:\d{2}$")
    after_hours_end: str = Field(default="18:00", pattern=r"^\d{2}:\d{2}$")
    buy_order_cutoff_minutes: int = Field(default=10, ge=0, le=60)

class TradingConfig(BaseModel):
    """Trading configuration.

    Attributes:
        mode: Trading mode (live, backtest, paper).
        default_watch_list: Default stock codes to monitor.
        order_execution: Order execution settings.
    """
    mode: str = Field(default="live", pattern=r"^(live|backtest|paper)$")
    default_watch_list: List[str] = Field(default_factory=list)
    order_execution: dict = Field(
        default_factory=lambda: {
            "default_order_type": "LIMIT",
            "allow_market_orders": True,
            "limit_order_validity_minutes": 60,
            "cancel_unfilled_after_minutes": 120
        }
    )

    @field_validator("default_watch_list")
    @classmethod
    def validate_stock_codes(cls, v: List[str]) -> List[str]:
        """Validate stock codes are 6 digits.

        Args:
            v: List of stock codes.

        Returns:
            Validated stock codes.

        Raises:
            ValueError: If any stock code is invalid.
        """
        import re
        pattern = re.compile(r"^\d{6}$")
        for code in v:
            if not pattern.match(code):
                raise ValueError(f"Invalid stock code: {code}")
        return v

class NotificationsConfig(BaseModel):
    """Notifications configuration.

    Attributes:
        enabled_channels: List of enabled notification channels.
        discord: Discord webhook settings.
        email: Email settings.
    """
    enabled_channels: List[str] = Field(default_factory=lambda: ["discord"])
    discord: dict = Field(default_factory=dict)
    email: dict = Field(default_factory=dict)

class SystemConfig(BaseModel):
    """Complete system configuration.

    Attributes:
        api: API configuration.
        account: Account configuration.
        risk_management: Risk management settings.
        market_hours: Market hours configuration.
        trading: Trading settings.
        data_collection: Data collection settings.
        notifications: Notification settings.
        health_check: Health check settings.
        logging: Logging configuration.
        database: Database configuration.
    """
    api: APIConfig
    account: AccountConfig
    risk_management: RiskManagementConfig = Field(default_factory=RiskManagementConfig)
    market_hours: MarketHoursConfig = Field(default_factory=MarketHoursConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    data_collection: dict = Field(default_factory=dict)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    health_check: dict = Field(default_factory=dict)
    logging: dict = Field(default_factory=dict)
    database: dict = Field(default_factory=dict)

    class Config:
        """Pydantic configuration."""
        json_encoders = {
            Decimal: str
        }
```

---

## strategies.yaml - 전략 설정

### 전체 구조

```yaml
# 매매 전략 설정
# 여러 전략을 동시에 운영할 수 있으며, 각 전략은 독립적으로 동작

strategies:
  - strategy_name: "Golden Cross Strategy"
    # 전략 활성화 여부
    enabled: true

    # 전략에 할당된 자금
    capital_allocation: 5000000  # 5백만원

    # 최대 동시 보유 종목 수
    max_positions: 10

    # 감시 대상 종목 (개별 전략이 오버라이드 가능)
    watched_stocks:
      - "005930"  # 삼성전자
      - "000660"  # SK하이닉스
      - "035720"  # 카카오
      - "051910"  # LG화학
      - "006400"  # 삼성SDI

    # 전략별 파라미터
    parameters:
      # 이동평균선 기간
      short_period: 5
      long_period: 20

      # 최소 거래량 필터 (일일 거래량)
      min_volume: 1000000

      # 손절/익절 설정
      stop_loss_pct: 0.03  # -3%
      take_profit_pct: 0.05  # +5%

      # 추가 필터 조건
      filters:
        # 최소 주가 (너무 저가 종목 제외)
        min_price: 1000

        # 최대 주가
        max_price: 500000

        # 등락률 필터 (-10% ~ +10%)
        min_change_rate: -0.10
        max_change_rate: 0.10

  - strategy_name: "Mean Reversion Strategy"
    enabled: false  # 비활성화 상태

    capital_allocation: 3000000  # 3백만원

    max_positions: 5

    watched_stocks:
      - "005930"  # 삼성전자
      - "035420"  # NAVER

    parameters:
      # 볼린저 밴드 설정
      bollinger_period: 20
      bollinger_std_dev: 2.0

      # RSI 설정
      rsi_period: 14
      rsi_oversold: 30
      rsi_overbought: 70

      # 손절/익절
      stop_loss_pct: 0.05
      take_profit_pct: 0.03

  - strategy_name: "Momentum Strategy"
    enabled: false

    capital_allocation: 2000000  # 2백만원

    max_positions: 3

    watched_stocks:
      - "373220"  # LG에너지솔루션
      - "207940"  # 삼성바이오로직스

    parameters:
      # 모멘텀 기간
      momentum_period: 10

      # 상승 추세 최소 요구 수익률
      min_momentum_rate: 0.05  # 5%

      # 거래량 급증 배수
      volume_surge_multiplier: 2.0

      # 손절/익절
      stop_loss_pct: 0.04
      take_profit_pct: 0.08
```

### 스키마 정의 (Pydantic)

```python
from typing import Dict, List, Any

class StrategyConfig(BaseModel):
    """Strategy configuration model.

    Attributes:
        strategy_name: Unique strategy identifier.
        enabled: Whether strategy is active.
        capital_allocation: Allocated capital for this strategy.
        max_positions: Maximum concurrent positions.
        watched_stocks: List of stock codes to monitor.
        parameters: Strategy-specific parameters.
    """
    strategy_name: str = Field(..., min_length=1, max_length=100)
    enabled: bool = Field(default=True)
    capital_allocation: Decimal = Field(..., gt=0)
    max_positions: int = Field(..., gt=0)
    watched_stocks: List[str] = Field(..., min_items=1)
    parameters: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("watched_stocks")
    @classmethod
    def validate_stock_codes(cls, v: List[str]) -> List[str]:
        """Validate all stock codes are 6 digits."""
        import re
        pattern = re.compile(r"^\d{6}$")
        for code in v:
            if not pattern.match(code):
                raise ValueError(f"Invalid stock code: {code}")
        return v

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, v: Dict[str, Any], info) -> Dict[str, Any]:
        """Validate strategy parameters based on strategy type.

        Args:
            v: Parameters dictionary.
            info: Validation info.

        Returns:
            Validated parameters.
        """
        # Convert numeric parameters to Decimal
        for key, value in v.items():
            if isinstance(value, (int, float)) and "pct" in key.lower():
                v[key] = Decimal(str(value))

        return v

class StrategiesConfig(BaseModel):
    """Collection of all strategies.

    Attributes:
        strategies: List of strategy configurations.
    """
    strategies: List[StrategyConfig]

    @field_validator("strategies")
    @classmethod
    def validate_unique_names(cls, v: List[StrategyConfig]) -> List[StrategyConfig]:
        """Ensure all strategy names are unique.

        Args:
            v: List of strategies.

        Returns:
            Validated strategies list.

        Raises:
            ValueError: If duplicate strategy names found.
        """
        names = [s.strategy_name for s in v]
        if len(names) != len(set(names)):
            raise ValueError("Strategy names must be unique")
        return v

    def get_enabled_strategies(self) -> List[StrategyConfig]:
        """Get list of enabled strategies.

        Returns:
            List of enabled strategy configs.
        """
        return [s for s in self.strategies if s.enabled]

    def get_strategy_by_name(self, name: str) -> Optional[StrategyConfig]:
        """Get strategy config by name.

        Args:
            name: Strategy name.

        Returns:
            Strategy config if found, None otherwise.
        """
        for strategy in self.strategies:
            if strategy.strategy_name == name:
                return strategy
        return None
```

---

## 스키마 검증

### 검증 규칙 요약

| 필드 | 검증 규칙 | 에러 메시지 |
|-----|----------|-----------|
| `account_number` | 8자리 숫자 | "Account number must be 8 digits" |
| `stock_code` | 6자리 숫자 | "Stock code must be 6 digits" |
| `daily_loss_limit_rate` | 0 < x ≤ 1 | "Loss limit must be between 0 and 1" |
| `capital_allocation` | > 0 | "Capital must be positive" |
| `max_positions` | > 0 | "Max positions must be positive" |
| `strategy_name` | 고유 값 | "Strategy names must be unique" |
| `market_hours` | HH:MM 형식 | "Invalid time format" |
| `mode` | live/backtest/paper | "Invalid trading mode" |

### 검증 실행 예시

```python
import yaml
from pathlib import Path

def load_and_validate_config(config_path: Path) -> SystemConfig:
    """Load and validate system configuration.

    Args:
        config_path: Path to config.yaml file.

    Returns:
        Validated SystemConfig object.

    Raises:
        ValidationError: If configuration is invalid.
    """
    with open(config_path) as f:
        config_data = yaml.safe_load(f)

    # Substitute environment variables
    config_data = substitute_env_vars(config_data)

    # Validate with Pydantic
    config = SystemConfig(**config_data)

    return config

def substitute_env_vars(config_data: dict) -> dict:
    """Substitute environment variables in config.

    Args:
        config_data: Raw config dictionary.

    Returns:
        Config with env vars substituted.
    """
    import os
    import re

    def replace_env_var(value):
        if isinstance(value, str):
            # Match ${VAR_NAME} pattern
            pattern = r"\$\{([A-Z_]+)\}"
            matches = re.findall(pattern, value)
            for var_name in matches:
                env_value = os.getenv(var_name)
                if env_value is None:
                    raise ValueError(f"Environment variable {var_name} not set")
                value = value.replace(f"${{{var_name}}}", env_value)
        elif isinstance(value, dict):
            return {k: replace_env_var(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [replace_env_var(item) for item in value]

        return value

    return replace_env_var(config_data)
```

---

## 환경 변수

### .env 파일 구조

```bash
# 키움증권 API 인증 정보
KIWOOM_APP_KEY=your_app_key_here
KIWOOM_APP_SECRET=your_app_secret_here

# Discord 웹훅 URL
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# 이메일 설정
EMAIL_SENDER=your_email@gmail.com
EMAIL_PASSWORD=your_app_password

# 데이터베이스 (선택적)
DATABASE_URL=sqlite:///data/trading.db

# 로그 레벨 (선택적)
LOG_LEVEL=INFO
```

### 환경 변수 로드

```python
from dotenv import load_dotenv
import os

def load_environment() -> None:
    """Load environment variables from .env file.

    Raises:
        FileNotFoundError: If .env file not found.
    """
    env_path = Path(".env")

    if not env_path.exists():
        raise FileNotFoundError(".env file not found")

    load_dotenv(env_path)

    # Verify required variables
    required_vars = [
        "KIWOOM_APP_KEY",
        "KIWOOM_APP_SECRET"
    ]

    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)

    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
```

---

## 설정 로드 구현

### ConfigManager 클래스

```python
from typing import Optional
from pathlib import Path
import yaml
from pydantic import ValidationError

class ConfigManager:
    """Manages system configuration loading and validation.

    Attributes:
        system_config: Loaded system configuration.
        strategies_config: Loaded strategies configuration.
    """

    def __init__(
        self,
        config_path: Path = Path("config/config.yaml"),
        strategies_path: Path = Path("config/strategies.yaml")
    ):
        """Initialize config manager.

        Args:
            config_path: Path to config.yaml.
            strategies_path: Path to strategies.yaml.
        """
        self.config_path = config_path
        self.strategies_path = strategies_path
        self.system_config: Optional[SystemConfig] = None
        self.strategies_config: Optional[StrategiesConfig] = None

    def load_all(self) -> None:
        """Load and validate all configuration files.

        Raises:
            FileNotFoundError: If config files not found.
            ValidationError: If configuration is invalid.
        """
        # Load environment variables
        load_environment()

        # Load system config
        self.system_config = self._load_system_config()

        # Load strategies config
        self.strategies_config = self._load_strategies_config()

        # Cross-validate
        self._validate_cross_config()

    def _load_system_config(self) -> SystemConfig:
        """Load system configuration.

        Returns:
            Validated SystemConfig.
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(self.config_path) as f:
            config_data = yaml.safe_load(f)

        # Substitute env vars
        config_data = substitute_env_vars(config_data)

        # Validate
        return SystemConfig(**config_data)

    def _load_strategies_config(self) -> StrategiesConfig:
        """Load strategies configuration.

        Returns:
            Validated StrategiesConfig.
        """
        if not self.strategies_path.exists():
            raise FileNotFoundError(f"Strategies file not found: {self.strategies_path}")

        with open(self.strategies_path) as f:
            strategies_data = yaml.safe_load(f)

        return StrategiesConfig(**strategies_data)

    def _validate_cross_config(self) -> None:
        """Validate cross-configuration constraints.

        Raises:
            ValueError: If cross-validation fails.
        """
        # Validate total capital allocation doesn't exceed account
        total_allocation = sum(
            s.capital_allocation
            for s in self.strategies_config.strategies
            if s.enabled
        )

        if total_allocation > self.system_config.account.initial_capital:
            raise ValueError(
                f"Total strategy allocation ({total_allocation}) exceeds "
                f"account capital ({self.system_config.account.initial_capital})"
            )

    def get_system_config(self) -> SystemConfig:
        """Get system configuration.

        Returns:
            System config.

        Raises:
            RuntimeError: If config not loaded.
        """
        if self.system_config is None:
            raise RuntimeError("Configuration not loaded. Call load_all() first.")
        return self.system_config

    def get_strategies_config(self) -> StrategiesConfig:
        """Get strategies configuration.

        Returns:
            Strategies config.

        Raises:
            RuntimeError: If config not loaded.
        """
        if self.strategies_config is None:
            raise RuntimeError("Configuration not loaded. Call load_all() first.")
        return self.strategies_config

    def reload(self) -> None:
        """Reload configuration from disk.

        Useful for dynamic config updates without restarting the system.
        """
        self.load_all()

# 사용 예시
config_manager = ConfigManager()
config_manager.load_all()

system_config = config_manager.get_system_config()
strategies_config = config_manager.get_strategies_config()

print(f"Account: {system_config.account.account_number}")
print(f"Daily loss limit: {system_config.risk_management.daily_loss_limit_rate * 100}%")
print(f"Enabled strategies: {len(strategies_config.get_enabled_strategies())}")
```

---

## 설정 변경 및 핫 리로드

### 런타임 설정 변경

```python
class RuntimeConfigUpdater:
    """Manages runtime configuration updates."""

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus
    ):
        """Initialize runtime config updater.

        Args:
            config_manager: Config manager instance.
            event_bus: Event bus for publishing config change events.
        """
        self.config_manager = config_manager
        self.event_bus = event_bus

    async def update_strategy_enabled(
        self,
        strategy_name: str,
        enabled: bool
    ) -> None:
        """Enable or disable a strategy at runtime.

        Args:
            strategy_name: Strategy to update.
            enabled: New enabled status.

        Raises:
            ValueError: If strategy not found.
        """
        strategies_config = self.config_manager.get_strategies_config()
        strategy = strategies_config.get_strategy_by_name(strategy_name)

        if not strategy:
            raise ValueError(f"Strategy not found: {strategy_name}")

        # Update config
        strategy.enabled = enabled

        # Persist to disk
        await self._save_strategies_config(strategies_config)

        # Publish event
        await self.event_bus.publish(
            ConfigChangedEvent(
                source="RuntimeConfigUpdater",
                config_type="strategy_enabled",
                strategy_name=strategy_name,
                new_value=enabled
            )
        )

    async def _save_strategies_config(
        self,
        config: StrategiesConfig
    ) -> None:
        """Save strategies config to disk.

        Args:
            config: Config to save.
        """
        with open(self.config_manager.strategies_path, "w") as f:
            yaml.dump(
                {"strategies": [s.model_dump() for s in config.strategies]},
                f,
                default_flow_style=False
            )
```

---

## 요약

본 문서는 자동매매 시스템의 설정 파일 스키마를 정의하였다:

1. **config.yaml**: API 인증, 계좌 정보, 위험 관리, 시장 시간, 알림 설정
2. **strategies.yaml**: 전략 정의, 감시 종목, 전략별 파라미터
3. **Pydantic 검증**: 모든 설정은 런타임에 타입 및 값 검증
4. **환경 변수**: 민감 정보는 .env 파일에서 로드
5. **ConfigManager**: 설정 로드 및 검증을 담당하는 중앙 관리 클래스
6. **핫 리로드**: 시스템 재시작 없이 설정 변경 가능

모든 설정 파일은 YAML 형식을 사용하며, 명확한 주석과 예시 값을 포함한다.

---

**End of Configuration Schema Specification**
