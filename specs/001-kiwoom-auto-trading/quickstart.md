# 키움증권 자동매매 시스템 빠른 시작 가이드

**Feature Branch**: `001-kiwoom-auto-trading`
**Created**: 2025-11-22
**Status**: Draft
**Related**: [spec.md](./spec.md) | [plan.md](./plan.md) | [data-model.md](./data-model.md)

---

## 목차

1. [시스템 개요](#시스템-개요)
2. [사전 요구사항](#사전-요구사항)
3. [설치 및 설정](#설치-및-설정)
4. [프로젝트 구조](#프로젝트-구조)
5. [첫 실행](#첫-실행)
6. [전략 작성](#전략-작성)
7. [실전 운영](#실전-운영)
8. [트러블슈팅](#트러블슈팅)
9. [다음 단계](#다음-단계)

---

## 시스템 개요

키움증권 REST API 기반 자동매매 시스템은 사용자가 정의한 투자 전략에 따라 자동으로 주식 매매를 수행하는 서버 애플리케이션입니다.

### 주요 기능

- **자동 매매 실행**: 사전 정의된 전략에 따라 매수/매도 주문을 자동으로 실행
- **실시간 시장 감시**: 키움증권 REST API를 통해 실시간 체결 데이터 및 차트 데이터 수집
- **위험 관리**: 손절/익절, 일일 손실 한도 등 자동 위험 관리
- **다중 전략 지원**: 여러 전략을 동시에 운영하고 자금 배분 가능
- **알림 기능**: Discord 웹훅 및 이메일을 통한 실시간 알림
- **백테스팅**: 과거 데이터로 전략을 검증하는 시뮬레이션 모드

### 시스템 가치

1. **심리적 요인 배제**: 공포와 탐욕에 의한 뇌동매매 방지
2. **시간적 자유 확보**: 24시간 시장 모니터링으로 투자 기회 극대화
3. **전략 검증 및 고도화**: 데이터 기반 투자 로직 구현 및 개선

---

## 사전 요구사항

### 필수 소프트웨어

- **Python 3.10 이상**: [python.org](https://www.python.org/downloads/)에서 설치
- **Git**: 소스 코드 관리 (선택적)

### 계정 및 인증 정보

#### 1. 키움증권 계좌 및 API 접근

- 키움증권 계좌 개설 (위탁 계좌)
- REST API 사용 신청 및 승인
- API 앱 키(App Key) 및 시크릿(App Secret) 발급

**신청 방법**:
1. 키움증권 홈페이지 로그인
2. [개발자센터] → [API 신청] 메뉴
3. REST API 사용 약관 동의 및 신청서 작성
4. 승인 후 앱 키 발급 (영업일 기준 1-2일 소요)

#### 2. Discord 웹훅 (선택적)

알림을 Discord로 받으려면 웹훅 URL이 필요합니다.

**설정 방법**:
1. Discord 서버 생성 또는 기존 서버 선택
2. 채널 설정 → 연동 → 웹훅 생성
3. 웹훅 URL 복사 (나중에 `.env` 파일에 사용)

#### 3. 이메일 SMTP (선택적)

Gmail을 사용할 경우 앱 비밀번호 발급이 필요합니다.

**설정 방법**:
1. Google 계정 관리 → 보안
2. 2단계 인증 활성화
3. 앱 비밀번호 생성 → "자동매매 시스템" 이름으로 발급
4. 16자리 비밀번호 복사 (나중에 `.env` 파일에 사용)

---

## 설치 및 설정

### 1. 저장소 클론

```bash
# HTTPS 방식
git clone https://github.com/your-username/auto-trading.git
cd auto-trading

# 또는 SSH 방식
git clone git@github.com:your-username/auto-trading.git
cd auto-trading
```

### 2. 가상 환경 생성 및 활성화

**Windows**:
```powershell
# 가상 환경 생성
python -m venv venv

# 가상 환경 활성화
venv\Scripts\activate
```

**Linux/macOS**:
```bash
# 가상 환경 생성
python3 -m venv venv

# 가상 환경 활성화
source venv/bin/activate
```

가상 환경이 활성화되면 프롬프트 앞에 `(venv)`가 표시됩니다.

### 3. 의존성 설치

```bash
# 필수 패키지 설치
pip install -r requirements.txt

# 설치 확인
pip list
```

**주요 패키지**:
- `aiohttp`: 비동기 HTTP 클라이언트 (키움증권 API 통신)
- `pydantic`: 데이터 검증 및 모델링
- `python-dotenv`: 환경 변수 관리
- `pyyaml`: YAML 설정 파일 파싱
- `pytest`: 테스트 프레임워크

### 4. 설정 파일 생성

#### 4.1 디렉토리 구조 확인

```bash
# 필요한 디렉토리 생성
mkdir -p config data logs
```

#### 4.2 환경 변수 파일 (.env) 생성

프로젝트 루트에 `.env` 파일을 생성하고 다음 내용을 입력합니다:

```bash
# 키움증권 API 인증 정보
KIWOOM_APP_KEY=your_app_key_here
KIWOOM_APP_SECRET=your_app_secret_here

# Discord 웹훅 (선택적)
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/your_webhook_url

# 이메일 설정 (선택적)
EMAIL_SENDER=your_email@gmail.com
EMAIL_PASSWORD=your_16_digit_app_password

# 로그 레벨 (선택적)
LOG_LEVEL=INFO
```

**중요**: `.env` 파일은 민감 정보를 포함하므로 절대 Git에 커밋하지 마세요. (`.gitignore`에 이미 포함됨)

#### 4.3 시스템 설정 파일 (config.yaml) 생성

`config/config.yaml` 파일을 생성하고 다음 내용을 입력합니다:

```yaml
# 키움증권 REST API 기반 자동매매 시스템 설정

api:
  app_key: ${KIWOOM_APP_KEY}
  app_secret: ${KIWOOM_APP_SECRET}
  base_url: "https://openapi.kiwoom.com/api/v1"

  rate_limits:
    price_per_second: 5
    chart_per_minute: 20
    order_per_second: 2
    account_per_minute: 10

  retry:
    max_retries: 3
    retry_delay_seconds: 1.0
    exponential_backoff: true

  timeout:
    connect_timeout_seconds: 10
    read_timeout_seconds: 30

account:
  account_number: "12345678"  # 본인의 8자리 계좌번호로 변경
  account_name: "김철수 위탁계좌"  # 본인의 계좌명으로 변경
  initial_capital: 10000000  # 백테스팅 모드 초기 자금 (1천만원)

risk_management:
  daily_loss_limit_rate: 0.05  # 일일 손실 한도 5%
  max_position_concentration: 0.30  # 종목별 최대 집중도 30%
  default_stop_loss_rate: 0.03  # 기본 손절 -3%
  default_take_profit_rate: 0.05  # 기본 익절 +5%
  max_risk_exposure: 0.80  # 총 위험 노출 한도 80%

market_hours:
  pre_market_start: "08:00"
  market_open: "09:00"
  market_close: "15:30"
  after_hours_end: "18:00"
  buy_order_cutoff_minutes: 10  # 15:20부터 신규 매수 차단

trading:
  mode: "backtest"  # 초기에는 backtest 모드로 시작 (실제 주문 없음)
  default_watch_list:
    - "005930"  # 삼성전자
    - "000660"  # SK하이닉스
    - "035720"  # 카카오

  order_execution:
    default_order_type: "LIMIT"
    allow_market_orders: true
    limit_order_validity_minutes: 60
    cancel_unfilled_after_minutes: 120

data_collection:
  realtime_interval_seconds: 1
  chart_cache:
    enabled: true
    ttl_seconds: 300
    max_items: 1000
  data_timeout_minutes: 3

notifications:
  enabled_channels:
    - "discord"

  discord:
    webhook_url: ${DISCORD_WEBHOOK_URL}
    enable_order_notifications: true
    enable_error_notifications: true
    enable_daily_report: true

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
  interval_seconds: 60
  api_check_timeout_seconds: 10
  data_freshness_threshold_minutes: 3

logging:
  level: "INFO"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  file:
    enabled: true
    path: "logs/trading.log"
    max_bytes: 10485760  # 10MB
    backup_count: 10
  console:
    enabled: true

database:
  sqlite_path: "data/trading.db"
  retention_days:
    orders: 365
    chart_data: 180
    notifications: 90
```

#### 4.4 전략 설정 파일 (strategies.yaml) 생성

`config/strategies.yaml` 파일을 생성하고 다음 내용을 입력합니다:

```yaml
# 매매 전략 설정

strategies:
  - strategy_name: "Golden Cross Strategy"
    enabled: true
    capital_allocation: 5000000  # 5백만원
    max_positions: 10

    watched_stocks:
      - "005930"  # 삼성전자
      - "000660"  # SK하이닉스
      - "035720"  # 카카오
      - "051910"  # LG화학
      - "006400"  # 삼성SDI

    parameters:
      short_period: 5  # 5일 이동평균선
      long_period: 20  # 20일 이동평균선
      min_volume: 1000000  # 최소 일일 거래량
      stop_loss_pct: 0.03  # -3% 손절
      take_profit_pct: 0.05  # +5% 익절

      filters:
        min_price: 1000  # 최소 주가 1,000원
        max_price: 500000  # 최대 주가 500,000원
        min_change_rate: -0.10  # 최소 등락률 -10%
        max_change_rate: 0.10  # 최대 등락률 +10%
```

### 5. 설정 검증

설정 파일이 올바르게 작성되었는지 확인합니다:

```bash
# 설정 파일 검증 (구현 후 사용 가능)
python -m src.cli.main validate-config

# 예상 출력:
# ✓ Environment variables loaded
# ✓ config.yaml validated
# ✓ strategies.yaml validated
# ✓ All configurations are valid
```

---

## 프로젝트 구조

```
auto-trading/
├── src/                      # 소스 코드
│   ├── models/               # 도메인 모델 (Account, Order, Position, Stock, Strategy)
│   │   ├── __init__.py
│   │   ├── account.py        # 계좌 모델
│   │   ├── order.py          # 주문 모델
│   │   ├── position.py       # 포지션 모델
│   │   ├── stock.py          # 종목 모델
│   │   └── strategy.py       # 전략 인터페이스
│   │
│   ├── services/             # 비즈니스 로직 및 외부 서비스
│   │   ├── __init__.py
│   │   ├── kiwoom_api.py     # 키움증권 REST API 클라이언트
│   │   ├── data_collector.py # 실시간 데이터 수집 서비스
│   │   ├── strategy_engine.py# 전략 실행 엔진
│   │   ├── order_executor.py # 주문 실행 및 관리
│   │   ├── risk_manager.py   # 위험 관리
│   │   ├── notifier.py       # 알림 전송 (Discord, Email)
│   │   └── health_check.py   # 시스템 헬스 체크
│   │
│   ├── strategies/           # 구체적인 매매 전략 구현
│   │   ├── __init__.py
│   │   ├── base.py           # BaseStrategy 추상 클래스
│   │   ├── golden_cross.py   # 골든크로스 전략
│   │   └── custom/           # 사용자 정의 전략
│   │
│   ├── utils/                # 유틸리티
│   │   ├── __init__.py
│   │   ├── logger.py         # 로깅 설정
│   │   ├── time_utils.py     # 시간대 처리
│   │   └── decimal_utils.py  # Decimal 계산 헬퍼
│   │
│   ├── cli/                  # CLI 인터페이스
│   │   ├── __init__.py
│   │   └── main.py           # CLI 진입점
│   │
│   └── config/               # 설정 관리
│       ├── __init__.py
│       └── settings.py       # Pydantic Settings
│
├── tests/                    # 테스트 코드
│   ├── unit/                 # 단위 테스트
│   ├── integration/          # 통합 테스트
│   └── fixtures/             # 테스트 데이터 및 mock
│
├── config/                   # 설정 파일
│   ├── config.yaml           # 시스템 설정
│   └── strategies.yaml       # 전략 설정
│
├── data/                     # 런타임 데이터
│   ├── trading.db            # SQLite 데이터베이스
│   └── backtest/             # 백테스팅 결과
│
├── logs/                     # 로그 파일
│   └── trading.log
│
├── .env                      # 환경 변수 (민감 정보)
├── requirements.txt          # Python 의존성
├── README.md                 # 프로젝트 소개
└── .gitignore                # Git 제외 파일
```

### 주요 디렉토리 설명

- **src/models/**: 핵심 데이터 모델 (계좌, 주문, 포지션, 종목, 전략)
- **src/services/**: API 통신, 데이터 수집, 전략 실행, 주문 관리 등 핵심 서비스
- **src/strategies/**: 실제 매매 전략 구현체 (골든크로스, RSI, 볼린저밴드 등)
- **src/cli/**: 명령줄 인터페이스 (시스템 시작/중지/상태 확인)
- **config/**: YAML 설정 파일
- **data/**: SQLite 데이터베이스 및 백테스팅 결과
- **logs/**: 시스템 로그 파일

---

## 첫 실행

### 1. 백테스트 모드로 시작

실제 주문을 실행하지 않고 시스템을 테스트합니다.

```bash
# 시스템 시작 (백테스트 모드)
python -m src.cli.main start

# 예상 출력:
# [2025-11-22 09:00:00] INFO - Loading configuration...
# [2025-11-22 09:00:01] INFO - ✓ Environment variables loaded
# [2025-11-22 09:00:01] INFO - ✓ System config validated
# [2025-11-22 09:00:01] INFO - ✓ Strategies config validated
# [2025-11-22 09:00:02] INFO - Starting system in BACKTEST mode
# [2025-11-22 09:00:03] INFO - API connected successfully
# [2025-11-22 09:00:04] INFO - Loaded 1 active strategy: Golden Cross Strategy
# [2025-11-22 09:00:05] INFO - Monitoring 5 stocks
# [2025-11-22 09:00:05] INFO - System started successfully
```

**백테스트 모드 특징**:
- 실제 주문을 전송하지 않음 (시뮬레이션만 수행)
- 전략 조건 충족 시 로그에만 기록
- 실제 API 연결 및 데이터 수집은 정상 수행

### 2. 시스템 상태 확인

별도 터미널에서 시스템 상태를 확인합니다:

```bash
# 시스템 상태 조회
python -m src.cli.main status

# 예상 출력:
# ========================================
# System Status
# ========================================
# Mode: BACKTEST
# Status: RUNNING
# API Connected: Yes
# Last Data Received: 2025-11-22 09:05:30 KST
# Uptime: 5 minutes
#
# ========================================
# Account Status
# ========================================
# Account: 12345678 (김철수 위탁계좌)
# Cash Balance: 10,000,000원
# Total Asset Value: 10,000,000원
# Daily P&L: 0원 (0.00%)
#
# ========================================
# Active Strategies (1)
# ========================================
# 1. Golden Cross Strategy
#    - Status: ENABLED
#    - Capital: 5,000,000원
#    - Positions: 0/10
#    - Watched Stocks: 5
#
# ========================================
# Positions (0)
# ========================================
# No positions
```

### 3. 로그 확인

실시간 로그를 확인하여 시스템 동작을 모니터링합니다:

```bash
# 로그 실시간 출력 (Windows - PowerShell)
Get-Content logs/trading.log -Wait -Tail 50

# 로그 실시간 출력 (Linux/macOS)
tail -f logs/trading.log
```

**로그 예시**:
```
[2025-11-22 09:10:15] INFO - [DataCollector] Updated price for 005930 (삼성전자): 72,000원
[2025-11-22 09:10:15] INFO - [StrategyEngine] Evaluating Golden Cross Strategy for 005930
[2025-11-22 09:10:15] INFO - [StrategyEngine] No buy signal for 005930
[2025-11-22 09:10:20] INFO - [DataCollector] Updated price for 000660 (SK하이닉스): 125,500원
[2025-11-22 09:10:20] INFO - [StrategyEngine] Evaluating Golden Cross Strategy for 000660
[2025-11-22 09:10:20] INFO - [StrategyEngine] ✓ BUY SIGNAL detected for 000660
[2025-11-22 09:10:20] INFO - [OrderExecutor] [BACKTEST MODE] Creating BUY order for 000660
[2025-11-22 09:10:20] INFO - [OrderExecutor] Order created: order_id=abc-123, stock=000660, qty=100, price=125,500
```

### 4. 시스템 중지

```bash
# 시스템 중지
python -m src.cli.main stop

# 예상 출력:
# [2025-11-22 09:30:00] INFO - Stopping system...
# [2025-11-22 09:30:01] INFO - Closing active positions...
# [2025-11-22 09:30:02] INFO - Disconnecting from API...
# [2025-11-22 09:30:03] INFO - Generating daily report...
# [2025-11-22 09:30:04] INFO - System stopped successfully
```

---

## 전략 작성

### 1. 전략 개념 이해

모든 전략은 `BaseStrategy` 추상 클래스를 상속하여 구현합니다.

**필수 메서드**:
- `evaluate_buy_signal(stock)`: 매수 조건 평가
- `evaluate_sell_signal(position, stock)`: 매도 조건 평가

### 2. 단순 이동평균선 크로스오버 전략 예시

`src/strategies/custom/simple_ma_cross.py` 파일을 생성합니다:

```python
"""단순 이동평균선 크로스오버 전략.

5일 이동평균선이 20일 이동평균선을 상향 돌파하면 매수,
손절(-3%) 또는 익절(+5%) 조건 충족 시 매도.
"""

from decimal import Decimal
from typing import Optional
from src.models.stock import Stock
from src.models.position import Position
from src.strategies.base import BaseStrategy
from src.config.settings import StrategyConfig


class SimpleMAStrategy(BaseStrategy):
    """단순 이동평균선 크로스오버 전략.

    Attributes:
        config: 전략 설정.
        short_period: 단기 이동평균선 기간.
        long_period: 장기 이동평균선 기간.
        stop_loss_pct: 손절 비율.
        take_profit_pct: 익절 비율.
    """

    def __init__(self, config: StrategyConfig):
        """전략 초기화.

        Args:
            config: 전략 설정 객체.
        """
        self.config = config
        self.short_period = config.parameters.get("short_period", 5)
        self.long_period = config.parameters.get("long_period", 20)
        self.stop_loss_pct = Decimal(str(config.parameters.get("stop_loss_pct", 0.03)))
        self.take_profit_pct = Decimal(str(config.parameters.get("take_profit_pct", 0.05)))

    async def evaluate_buy_signal(self, stock: Stock) -> bool:
        """매수 시그널 평가.

        골든크로스 발생 시 매수 시그널 생성.

        Args:
            stock: 평가 대상 종목.

        Returns:
            매수 시그널 발생 여부.
        """
        # 1. 차트 데이터 조회 (최근 long_period일)
        chart_data = await self._get_chart_data(
            stock.stock_code,
            days=self.long_period + 1
        )

        if len(chart_data) < self.long_period + 1:
            return False  # 데이터 부족

        # 2. 이동평균선 계산
        short_ma_today = self._calculate_sma(chart_data[-self.short_period:])
        long_ma_today = self._calculate_sma(chart_data[-self.long_period:])

        short_ma_yesterday = self._calculate_sma(chart_data[-(self.short_period+1):-1])
        long_ma_yesterday = self._calculate_sma(chart_data[-(self.long_period+1):-1])

        # 3. 골든크로스 체크 (어제는 아래, 오늘은 위)
        golden_cross = (
            short_ma_yesterday <= long_ma_yesterday and
            short_ma_today > long_ma_today
        )

        # 4. 추가 필터 조건 확인
        if golden_cross:
            min_volume = self.config.parameters.get("min_volume", 0)
            if stock.volume < min_volume:
                return False  # 거래량 부족

        return golden_cross

    async def evaluate_sell_signal(self, position: Position, stock: Stock) -> bool:
        """매도 시그널 평가.

        손절 또는 익절 조건 충족 시 매도 시그널 생성.

        Args:
            position: 보유 포지션.
            stock: 종목 시세.

        Returns:
            매도 시그널 발생 여부.
        """
        return_rate = position.return_rate

        # 손절 조건
        if return_rate <= -self.stop_loss_pct:
            return True

        # 익절 조건
        if return_rate >= self.take_profit_pct:
            return True

        return False

    def _calculate_sma(self, chart_data: list) -> Decimal:
        """단순 이동평균선 계산.

        Args:
            chart_data: 차트 데이터 리스트.

        Returns:
            이동평균선 값.
        """
        if not chart_data:
            return Decimal("0")

        total = sum(candle.close_price for candle in chart_data)
        return total / len(chart_data)

    async def _get_chart_data(self, stock_code: str, days: int) -> list:
        """차트 데이터 조회.

        Args:
            stock_code: 종목 코드.
            days: 조회 일수.

        Returns:
            차트 데이터 리스트.
        """
        # 실제 구현에서는 DataCollector 서비스를 통해 조회
        # 여기서는 예시만 제공
        from src.services.data_collector import DataCollector

        collector = DataCollector()
        return await collector.get_daily_chart(stock_code, days)
```

### 3. 전략을 strategies.yaml에 등록

`config/strategies.yaml`에 새 전략을 추가합니다:

```yaml
strategies:
  # 기존 전략...

  - strategy_name: "Simple MA Cross Strategy"
    enabled: true
    capital_allocation: 3000000  # 3백만원
    max_positions: 5

    watched_stocks:
      - "005930"  # 삼성전자
      - "000660"  # SK하이닉스

    parameters:
      short_period: 5
      long_period: 20
      min_volume: 500000
      stop_loss_pct: 0.03
      take_profit_pct: 0.05
```

### 4. 전략 테스트 (백테스트 모드)

```bash
# 시스템 재시작
python -m src.cli.main stop
python -m src.cli.main start

# 로그에서 새 전략 로드 확인
# [2025-11-22 10:00:05] INFO - Loaded 2 active strategies:
# [2025-11-22 10:00:05] INFO -   1. Golden Cross Strategy
# [2025-11-22 10:00:05] INFO -   2. Simple MA Cross Strategy
```

### 5. 전략 백테스팅

과거 데이터로 전략을 검증합니다:

```bash
# 특정 전략을 과거 1년 데이터로 백테스팅
python -m src.cli.main backtest \
  --strategy "Simple MA Cross Strategy" \
  --start-date 2024-01-01 \
  --end-date 2024-12-31 \
  --initial-capital 5000000

# 예상 출력:
# ========================================
# Backtest Results
# ========================================
# Strategy: Simple MA Cross Strategy
# Period: 2024-01-01 to 2024-12-31
# Initial Capital: 5,000,000원
#
# Performance:
# - Total Trades: 45
# - Win Rate: 62.2%
# - Total P&L: +850,000원 (+17.0%)
# - Max Drawdown: -5.2%
# - Sharpe Ratio: 1.35
#
# Best Trade: +150,000원 (SK하이닉스, 2024-03-15)
# Worst Trade: -85,000원 (카카오, 2024-08-22)
```

---

## 실전 운영

### 1. 실전 운영 전 체크리스트

**필수 확인 사항**:

- [ ] 키움증권 API 인증 정보가 올바르게 설정됨
- [ ] 계좌번호가 정확하게 입력됨
- [ ] 백테스트 모드에서 충분히 테스트 완료
- [ ] 전략이 예상대로 동작함을 확인
- [ ] 위험 관리 설정이 적절함 (손절, 일일 손실 한도)
- [ ] 알림이 정상 작동함 (Discord/Email)
- [ ] 계좌 잔고가 충분함
- [ ] 실제 매매 시간(09:00-15:30) 확인

### 2. 실전 모드로 전환

`config/config.yaml` 파일에서 운영 모드를 변경합니다:

```yaml
trading:
  mode: "live"  # backtest → live로 변경
```

### 3. 실전 운영 시작

```bash
# 시스템 시작 (실전 모드)
python -m src.cli.main start

# 예상 출력:
# [2025-11-22 08:50:00] INFO - Starting system in LIVE mode
# [2025-11-22 08:50:00] WARNING - ⚠️  LIVE MODE: Real orders will be placed!
# [2025-11-22 08:50:01] INFO - API connected successfully
# [2025-11-22 08:50:02] INFO - Account verified: 12345678
# [2025-11-22 08:50:03] INFO - Cash Balance: 10,250,000원
# [2025-11-22 08:50:05] INFO - System started successfully
# [2025-11-22 08:50:05] INFO - Waiting for market open (09:00)...
```

### 4. 실시간 모니터링

#### 4.1 시스템 상태 모니터링

```bash
# 1분마다 상태 확인
watch -n 60 "python -m src.cli.main status"
```

#### 4.2 로그 모니터링

```bash
# 실시간 로그 출력
tail -f logs/trading.log | grep -E "(BUY|SELL|ERROR|ALERT)"
```

#### 4.3 알림 모니터링

Discord 채널에서 실시간 알림을 확인합니다:

- 매수/매도 체결 알림
- 오류 발생 알림
- 일일 손실 한도 경고
- 장 마감 일일 리포트

### 5. 긴급 중단 절차

**상황**: 시스템 오류, 급격한 시장 변동, 손실 확대 등

```bash
# 즉시 시스템 중단 (모든 자동 매매 중지)
python -m src.cli.main emergency-stop

# 예상 출력:
# [2025-11-22 14:25:00] CRITICAL - ⚠️  EMERGENCY STOP initiated
# [2025-11-22 14:25:01] INFO - Cancelling all pending orders...
# [2025-11-22 14:25:02] INFO - Cancelled 3 pending orders
# [2025-11-22 14:25:03] INFO - All auto-trading suspended
# [2025-11-22 14:25:04] INFO - Current positions preserved
# [2025-11-22 14:25:05] INFO - System in PAUSED mode
```

**긴급 중단 후 조치**:
1. 로그 파일 확인하여 문제 원인 파악
2. 필요 시 수동으로 포지션 청산 (HTS 이용)
3. 설정 파일 수정 및 재시작

### 6. 일일 트레이딩 리포트

장 마감 후 자동으로 일일 리포트가 Discord/Email로 전송됩니다:

**리포트 예시**:
```
========================================
일일 트레이딩 리포트
2025-11-22 (금)
========================================

계좌 현황
- 시작 잔고: 10,000,000원
- 종료 잔고: 10,150,000원
- 당일 손익: +150,000원 (+1.5%)

거래 내역
- 총 거래: 4건 (매수 2, 매도 2)
- 승률: 50% (1승 1패)

매수 체결
1. 삼성전자 (005930) 100주 @ 72,000원 - 09:15
2. SK하이닉스 (000660) 50주 @ 125,500원 - 10:30

매도 체결
1. 카카오 (035720) 80주 @ 48,500원 - 13:20 (익절 +5.2%)
2. LG화학 (051910) 40주 @ 380,000원 - 14:10 (손절 -3.1%)

보유 포지션
1. 삼성전자 (005930) 100주 @ 72,000원 (평가손익: +2,000원 +0.3%)
2. SK하이닉스 (000660) 50주 @ 125,500원 (평가손익: -1,500원 -0.2%)

총 평가금액: 13,298,500원
총 손익: +150,000원 (+1.5%)
```

---

## 트러블슈팅

### 1. 일반적인 오류 및 해결 방법

#### 오류: "Environment variable KIWOOM_APP_KEY not set"

**원인**: `.env` 파일이 없거나 환경 변수가 설정되지 않음

**해결**:
```bash
# .env 파일 확인
cat .env

# KIWOOM_APP_KEY 항목이 있는지 확인
# 없으면 추가:
echo "KIWOOM_APP_KEY=your_actual_key" >> .env
```

#### 오류: "Invalid stock code: 05930"

**원인**: 종목 코드가 6자리가 아님

**해결**:
```yaml
# strategies.yaml에서 종목 코드 확인
watched_stocks:
  - "005930"  # ✓ 올바름 (앞에 0 포함)
  # - "05930"  # ✗ 잘못됨 (5자리)
```

#### 오류: "Total strategy allocation exceeds account capital"

**원인**: 전략에 할당된 총 자금이 계좌 잔고를 초과함

**해결**:
```yaml
# config/config.yaml
account:
  initial_capital: 10000000  # 1천만원

# config/strategies.yaml
strategies:
  - strategy_name: "Strategy 1"
    capital_allocation: 5000000  # 5백만원

  - strategy_name: "Strategy 2"
    capital_allocation: 3000000  # 3백만원

# 총합: 8백만원 < 1천만원 (OK)
```

#### 오류: "API connection timeout"

**원인**: 키움증권 API 서버 응답 없음 또는 네트워크 문제

**해결**:
```bash
# 1. 인터넷 연결 확인
ping openapi.kiwoom.com

# 2. API 인증 정보 확인
python -m src.cli.main validate-config

# 3. 방화벽 설정 확인 (포트 443 허용)

# 4. 시스템 재시작
python -m src.cli.main stop
python -m src.cli.main start
```

### 2. API 연결 테스트

```bash
# API 연결 상태 확인
python -m src.cli.main test-api

# 예상 출력:
# Testing Kiwoom API connection...
# ✓ API authentication successful
# ✓ Account info retrieved
# ✓ Price data retrieved for 005930
# ✓ All API endpoints working
```

### 3. 설정 파일 검증

```bash
# 설정 파일 유효성 검증
python -m src.cli.main validate-config

# 예상 출력:
# Validating configuration files...
# ✓ config.yaml: VALID
# ✓ strategies.yaml: VALID
# ✓ Environment variables: VALID
# ✓ Cross-validation: PASSED
```

### 4. 로그 확인 방법

#### 4.1 특정 기간 로그 조회

```bash
# 오늘 로그만 필터링 (Linux/macOS)
grep "2025-11-22" logs/trading.log

# 오늘 로그만 필터링 (Windows PowerShell)
Select-String -Path logs/trading.log -Pattern "2025-11-22"
```

#### 4.2 오류 로그만 조회

```bash
# ERROR 레벨 로그만 조회
grep "ERROR" logs/trading.log

# CRITICAL 레벨 로그만 조회
grep "CRITICAL" logs/trading.log
```

#### 4.3 특정 종목 로그 조회

```bash
# 삼성전자 관련 로그만 조회
grep "005930" logs/trading.log
```

### 5. 데이터베이스 확인

```bash
# SQLite 데이터베이스 접속
sqlite3 data/trading.db

# 주문 내역 조회
SELECT order_id, stock_code, order_type, quantity, status, created_at
FROM orders
WHERE created_at >= date('now')
ORDER BY created_at DESC;

# 포지션 히스토리 조회
SELECT stock_code, quantity, realized_pnl, closed_at
FROM position_history
WHERE closed_at >= date('now', '-7 days')
ORDER BY closed_at DESC;

# 종료
.exit
```

### 6. 자주 묻는 질문 (FAQ)

**Q: 백테스트 모드에서 실제 주문이 실행되나요?**

A: 아니오. 백테스트 모드에서는 주문 시뮬레이션만 수행하며 실제 API 주문 요청을 보내지 않습니다.

**Q: 시스템이 예기치 않게 종료되면 보유 포지션은 어떻게 되나요?**

A: 보유 포지션은 계좌에 그대로 유지됩니다. 시스템 재시작 시 데이터베이스에서 포지션 정보를 복구합니다.

**Q: 여러 전략을 동시에 운영할 수 있나요?**

A: 네, `strategies.yaml`에 여러 전략을 정의하고 각각 `enabled: true`로 설정하면 동시 운영이 가능합니다.

**Q: 실시간 데이터가 수신되지 않습니다.**

A: `data_timeout_minutes` 설정 확인 후, 로그에서 API 연결 상태를 확인하세요. 필요 시 시스템을 재시작합니다.

**Q: 손절이 제대로 작동하지 않습니다.**

A: 전략 파라미터에서 `stop_loss_pct` 값을 확인하고, 로그에서 매도 시그널 평가 로직을 확인하세요.

---

## 다음 단계

### 1. 상세 문서 읽기

- [spec.md](./spec.md): 전체 시스템 요구사항 및 사용자 스토리
- [plan.md](./plan.md): 구현 계획 및 기술 스택
- [data-model.md](./data-model.md): 데이터 모델 명세 및 ER 다이어그램
- [contracts/kiwoom-api.md](./contracts/kiwoom-api.md): 키움증권 API 연동 가이드
- [contracts/configuration-schema.md](./contracts/configuration-schema.md): 설정 파일 상세 가이드

### 2. 고급 기능 활용

#### 2.1 다중 전략 운영

여러 전략을 동시에 운영하고 자금을 배분합니다:

```yaml
# strategies.yaml
strategies:
  - strategy_name: "Golden Cross"
    capital_allocation: 3000000  # 30%

  - strategy_name: "RSI Strategy"
    capital_allocation: 2000000  # 20%

  - strategy_name: "Momentum"
    capital_allocation: 5000000  # 50%
```

#### 2.2 위험 관리 튜닝

포트폴리오 위험을 세밀하게 조정합니다:

```yaml
# config.yaml
risk_management:
  daily_loss_limit_rate: 0.03  # 일일 손실 한도를 3%로 축소
  max_position_concentration: 0.20  # 종목별 최대 집중도 20%로 축소
  max_risk_exposure: 0.60  # 총 위험 노출을 60%로 제한
```

#### 2.3 커스텀 알림 필터

중요한 알림만 받도록 설정합니다:

```yaml
# config.yaml
notifications:
  discord:
    enable_order_notifications: true  # 주문 체결 알림만 활성화
    enable_error_notifications: true
    enable_daily_report: false  # 일일 리포트는 이메일로만 수신
```

#### 2.4 로그 레벨 조정

디버깅 시 상세 로그를 활성화합니다:

```yaml
# config.yaml
logging:
  level: "DEBUG"  # INFO → DEBUG로 변경
```

### 3. 커뮤니티 및 지원

#### GitHub 이슈

버그 리포트 또는 기능 제안:
- [Issues 페이지](https://github.com/your-username/auto-trading/issues)

#### 토론 및 질문

전략 공유 및 기술 질문:
- [Discussions 페이지](https://github.com/your-username/auto-trading/discussions)

#### 기여하기

Pull Request 환영:
1. Fork 저장소
2. Feature 브랜치 생성 (`git checkout -b feature/my-strategy`)
3. 변경 사항 커밋 (`git commit -m 'Add new strategy'`)
4. 브랜치에 Push (`git push origin feature/my-strategy`)
5. Pull Request 생성

### 4. 추가 학습 자료

#### Python 비동기 프로그래밍

- [asyncio 공식 문서](https://docs.python.org/3/library/asyncio.html)
- [aiohttp 가이드](https://docs.aiohttp.org/)

#### 기술적 분석 및 전략

- 이동평균선 (Moving Average)
- RSI (Relative Strength Index)
- 볼린저 밴드 (Bollinger Bands)
- MACD (Moving Average Convergence Divergence)

#### 리스크 관리

- 포지션 사이징 (Position Sizing)
- 켈리 공식 (Kelly Criterion)
- 샤프 비율 (Sharpe Ratio)

---

## 마치며

이 가이드를 통해 키움증권 자동매매 시스템을 성공적으로 시작하셨기를 바랍니다.

**중요한 주의사항**:
- 실전 운영 전 반드시 백테스트 모드에서 충분히 테스트하세요
- 처음에는 소액으로 시작하여 시스템에 익숙해진 후 투자금을 늘리세요
- 자동매매 시스템도 완벽하지 않으므로 정기적인 모니터링이 필요합니다
- 투자의 책임은 본인에게 있으며, 손실 가능성을 항상 염두에 두세요

**행운을 빕니다!** 📈

---

**Last Updated**: 2025-11-22
**Document Version**: 1.0
**Author**: Auto-Trading System Development Team
