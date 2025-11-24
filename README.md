# 키움증권 REST API 기반 자동매매 시스템

사용자가 정의한 투자 전략에 따라 자동으로 주식 매매를 수행하는 고성능 서버 기반 자동매매 시스템입니다.

## 주요 특징

### 핵심 기능
- **자동 매매 실행**: 4가지 전략 (Golden Cross, RSI Divergence, VWAP Deviation, Order Book Imbalance)
- **실시간 모니터링**: 계좌 상태, 보유 종목, 손익 현황 실시간 추적
- **고급 위험 관리**: 일일 손실 한도, 종목별 비중 제한, 자동 손절/익절
- **시뮬레이터**: 실전 투입 전 전략 검증을 위한 In-Memory 시뮬레이터
- **알림 시스템**: Discord 웹훅 및 이메일을 통한 실시간 이벤트 알림

### 성능 최적화
- **Redis 캐싱**: 가격 데이터 캐싱으로 API 호출 최소화
- **분산 레이트 리미터**: Redis 기반 API 호출 제한 관리
- **주문 파이프라인**: 배치 처리 및 워커 풀을 통한 대량 주문 처리
- **시계열 데이터 관리**: 효율적인 틱/분봉 데이터 저장 및 조회
- **WebSocket 프록시**: 실시간 데이터 스트리밍 지원

### 아키텍처 특징
- **이벤트 기반 아키텍처**: 주문/포지션 이벤트 비동기 처리
- **이벤트 소싱**: 모든 거래 이벤트 저장 및 재생 가능
- **마이크로서비스 패턴**: 서비스별 독립적인 책임과 인터페이스
- **헥사고날 아키텍처**: 도메인 로직과 인프라 계층 분리

## 기술 스택

### 핵심 기술
- **Python 3.10+**: 비동기 프로그래밍 지원
- **httpx**: 고성능 비동기 HTTP 클라이언트
- **pydantic**: 타입 안정성을 위한 데이터 검증
- **Redis**: 캐싱 및 분산 레이트 리미팅
- **structlog**: 구조화된 로깅

### 개발/테스트
- **pytest**: 단위/통합/시뮬레이터 테스트
- **ruff**: Python 린터 및 포매터
- **pytest-cov**: 테스트 커버리지 측정

## 프로젝트 구조

```
auto-trading/
├── src/                      # 소스 코드
│   ├── api/                 # API 통신 계층
│   │   ├── kiwoom_client.py # 키움증권 REST API 클라이언트
│   │   ├── rate_limiter.py  # API 호출 제한 관리
│   │   └── exceptions.py    # API 예외 정의
│   ├── cache/               # Redis 캐싱 계층
│   │   ├── redis_manager.py # Redis 연결 관리
│   │   ├── price_cache.py   # 가격 데이터 캐싱
│   │   └── distributed_rate_limiter.py  # 분산 레이트 리미터
│   ├── models/              # 도메인 모델
│   │   ├── order.py        # 주문 모델
│   │   ├── position.py     # 포지션 모델
│   │   ├── account.py      # 계좌 모델
│   │   └── strategy.py     # 전략 기본 클래스
│   ├── strategies/          # 매매 전략
│   │   ├── golden_cross.py # 골든크로스 전략
│   │   ├── rsi_divergence.py # RSI 다이버전스 전략
│   │   ├── vwap_deviation.py # VWAP 편차 전략
│   │   └── order_book_imbalance.py # 호가 불균형 전략
│   ├── services/            # 비즈니스 로직
│   │   ├── strategy_engine.py # 전략 실행 엔진
│   │   ├── order_executor.py  # 주문 실행 서비스
│   │   ├── risk_manager.py    # 위험 관리 서비스
│   │   ├── data_collector.py  # 데이터 수집 서비스
│   │   ├── order_pipeline_optimizer.py # 주문 최적화
│   │   └── order_worker_pool.py # 주문 워커 풀
│   ├── events/              # 이벤트 기반 시스템
│   │   ├── event_bus.py    # 이벤트 버스
│   │   ├── event_store.py  # 이벤트 저장소
│   │   └── event_replay.py # 이벤트 재생
│   ├── monitoring/          # 모니터링
│   │   ├── health_checker.py # 헬스 체크
│   │   ├── metrics_collector.py # 메트릭 수집
│   │   └── performance_analyzer.py # 성능 분석
│   ├── simulator/           # 백테스팅 시뮬레이터
│   │   ├── kiwoom_simulator.py # 키움 API 시뮬레이터
│   │   ├── market_data_simulator.py # 시장 데이터 시뮬레이터
│   │   └── fake_exchange.py # 가짜 거래소
│   ├── timeseries/          # 시계열 데이터 관리
│   │   ├── tick_storage.py # 틱 데이터 저장
│   │   ├── minute_bar_storage.py # 분봉 저장
│   │   └── timeseries_query.py # 시계열 조회
│   ├── websocket_proxy/     # WebSocket 프록시
│   │   └── kiwoom_websocket_proxy.py # 실시간 데이터 프록시
│   ├── config/              # 설정 관리
│   │   └── settings.py     # 환경 설정
│   ├── repositories/        # 데이터 저장소
│   └── utils/              # 유틸리티
├── tests/                   # 테스트 코드
│   ├── unit/               # 단위 테스트
│   ├── integration/        # 통합 테스트
│   ├── simulator/          # 시뮬레이터 테스트
│   ├── contract/           # 계약 테스트
│   ├── events/             # 이벤트 시스템 테스트
│   ├── monitoring/         # 모니터링 테스트
│   └── services/           # 서비스 테스트
├── config/                  # 설정 파일
├── data/                   # 데이터 파일
├── logs/                   # 로그 파일
└── specs/                  # 프로젝트 명세
```

## 빠른 시작

### 1. 환경 설정

```bash
# Python 3.10+ 설치 확인
python --version

# 프로젝트 클론
git clone <repository-url>
cd auto-trading

# 가상 환경 생성 및 활성화
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt
```

### 2. Redis 설치 및 실행

```bash
# Windows: WSL2를 통한 Redis 설치
wsl --install
wsl
sudo apt update
sudo apt install redis-server
sudo service redis-server start

# macOS: Homebrew를 통한 설치
brew install redis
brew services start redis

# Linux: apt를 통한 설치
sudo apt install redis-server
sudo systemctl start redis
```

### 3. 환경 변수 설정

```bash
# .env.example을 .env로 복사
cp .env.example .env

# .env 파일 편집하여 필수 값 설정
# KIWOOM_API_KEY=your_api_key
# KIWOOM_API_SECRET=your_api_secret
# KIWOOM_ACCOUNT_NUMBER=your_account_number
# DISCORD_WEBHOOK_URL=your_webhook_url (선택)
# REDIS_HOST=localhost
# REDIS_PORT=6379
# REDIS_DB=0
```

### 4. 시뮬레이터로 첫 전략 실행

```python
import asyncio
from decimal import Decimal
from src.simulator.kiwoom_simulator import KiwoomSimulator
from src.strategies.golden_cross import GoldenCrossStrategy

async def main():
    # 시뮬레이터 초기화 (초기 자금 1000만원)
    simulator = KiwoomSimulator(initial_balance=Decimal("10000000"))

    # 전략 생성 및 실행
    strategy = GoldenCrossStrategy(
        short_period=5,
        long_period=20,
        stop_loss_pct=0.03,
        take_profit_pct=0.05
    )

    # 전략 엔진에 등록 및 실행
    await simulator.run_strategy(strategy)

# 실행
asyncio.run(main())
```

### 5. 실전 모드 실행

```python
import asyncio
from src.api.kiwoom_client import KiwoomClient
from src.services.strategy_engine import StrategyEngine
from src.strategies.golden_cross import GoldenCrossStrategy

async def main():
    # API 클라이언트 초기화
    client = KiwoomClient()

    # 전략 엔진 초기화
    engine = StrategyEngine(client=client)

    # 전략 추가
    strategy = GoldenCrossStrategy()
    engine.add_strategy("golden_cross", strategy)

    # 엔진 실행
    await engine.start()

# 실행
asyncio.run(main())
```

## 구현된 전략

### 1. Golden Cross Strategy (골든크로스 전략)
- 단기 이동평균선이 장기 이동평균선을 상향 돌파 시 매수
- 하향 돌파 시 매도
- 자동 손절/익절 기능 포함

### 2. RSI Divergence Strategy (RSI 다이버전스 전략)
- RSI와 가격의 다이버전스 감지
- 과매수/과매도 구간에서 반전 신호 포착
- 볼륨 확인을 통한 신호 필터링

### 3. VWAP Deviation Strategy (VWAP 편차 전략)
- VWAP(거래량 가중 평균가)로부터의 이탈 감지
- 표준편차 기반 진입/청산 신호
- 일중 트레이딩에 최적화

### 4. Order Book Imbalance Strategy (호가 불균형 전략)
- 매수/매도 호가 불균형 분석
- 대량 매수/매도 벽 감지
- 단기 가격 움직임 예측

## 테스트 실행

```bash
# 전체 테스트 실행
pytest

# 특정 카테고리 테스트
pytest tests/unit/              # 단위 테스트
pytest tests/integration/        # 통합 테스트
pytest tests/simulator/          # 시뮬레이터 테스트
pytest tests/contract/           # API 계약 테스트

# 커버리지 리포트
pytest --cov=src --cov-report=html
open htmlcov/index.html  # 브라우저에서 확인

# 특정 마커로 테스트 필터링
pytest -m "not slow"     # 빠른 테스트만
pytest -m redis          # Redis 관련 테스트만
```

## 코드 품질 관리

```bash
# Ruff 린터 실행
ruff check .

# 자동 수정
ruff check . --fix

# 코드 포매팅
ruff format .

# 타입 체크 (mypy 사용 시)
mypy src/
```

## 성능 모니터링

### 대시보드 실행
```bash
# 모니터링 대시보드 실행
python -m src.monitoring.dashboard

# 브라우저에서 http://localhost:8080 접속
```

### 메트릭 확인
- **주문 처리 성능**: 평균 처리 시간, 처리량, 실패율
- **전략 성능**: 승률, 평균 수익률, 샤프 비율
- **시스템 리소스**: CPU, 메모리, Redis 사용률
- **API 호출**: 호출 횟수, 레이트 리밋 상태

## 위험 관리

### 자동 안전장치
- **일일 손실 한도**: 설정된 한도 도달 시 자동 거래 중지
- **종목별 비중 제한**: 단일 종목 최대 투자 비중 제한
- **주문 검증**: 모든 주문 실행 전 잔고 및 리스크 확인
- **서킷 브레이커**: 급격한 시장 변동 시 자동 중지

### 수동 제어
```python
# 긴급 모든 포지션 청산
await engine.emergency_liquidate_all()

# 특정 전략 중지
await engine.stop_strategy("golden_cross")

# 일시 정지
await engine.pause_trading()
```

## 개발 철학

### Event-Driven Architecture
- 모든 주요 액션은 이벤트로 처리
- 이벤트 소싱으로 완전한 감사 추적
- 비동기 이벤트 처리로 높은 처리량 달성

### Fake Object Driven Development
- `unittest.mock` 대신 실제 동작하는 시뮬레이터 사용
- 모든 전략을 시뮬레이터에서 먼저 검증
- Contract Test로 실제 API와 일치성 보장

### Clean Architecture
- 도메인 로직과 인프라 완전 분리
- 의존성 역전 원칙 준수
- 테스트 가능한 코드 구조

## 라이선스

MIT License

## 기여 방법

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 주의사항

⚠️ **실전 투자 경고**

1. **충분한 테스트**: 최소 3개월 이상 시뮬레이터로 검증
2. **소액 시작**: 초기에는 최소 금액으로 시작
3. **손실 한도 설정**: 반드시 일일/월간 손실 한도 설정
4. **정기 모니터링**: 완전 자동화 후에도 주기적 확인 필수
5. **투자 책임**: 모든 투자 손실은 사용자 본인 책임

⚠️ **시스템 요구사항**

- Python 3.10 이상
- Redis 5.0 이상
- 메모리 최소 4GB (권장 8GB)
- 안정적인 인터넷 연결

## 문서

상세 문서는 `specs/` 디렉토리 참조:

- [기능 명세](specs/001-kiwoom-auto-trading/spec.md)
- [구현 계획](specs/001-kiwoom-auto-trading/plan.md)
- [작업 목록](specs/001-kiwoom-auto-trading/tasks.md)
- [API 문서](docs/api.md) (준비 중)
- [전략 가이드](docs/strategies.md) (준비 중)

## 지원

- **이슈**: [GitHub Issues](https://github.com/your-repo/issues)
- **이메일**: support@example.com
- **디스코드**: [커뮤니티 서버](https://discord.gg/example)

## 업데이트 로그

### v1.0.0 (2025-11-25)
- 초기 릴리즈
- 4가지 기본 전략 구현
- Redis 캐싱 레이어 추가
- 이벤트 기반 아키텍처 구현
- WebSocket 프록시 추가
- 주문 파이프라인 최적화