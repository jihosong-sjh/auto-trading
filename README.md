# 키움증권 REST API 기반 자동매매 에이전트

사용자가 정의한 투자 전략에 따라 자동으로 주식 매매를 수행하는 서버 기반 자동매매 시스템입니다.

## 주요 특징

- **자동 매매 실행**: 사전 정의된 전략에 따라 자동으로 매수/매도 주문 실행
- **실시간 모니터링**: 계좌 상태, 보유 종목, 손익 현황 실시간 확인
- **위험 관리**: 일일 손실 한도, 종목별 비중 제한 등 안전장치 내장
- **시뮬레이터 지원**: 실제 거래 전 전략 검증을 위한 In-Memory 시뮬레이터 제공
- **알림 시스템**: Discord 웹훅 및 이메일을 통한 주요 이벤트 알림

## 기술 스택

- **Python 3.10+**
- **httpx**: 비동기 HTTP 클라이언트
- **pydantic**: 데이터 검증 및 직렬화
- **pytest**: 테스트 프레임워크
- **ruff**: 린터 및 포매터

## 프로젝트 구조

```
auto-trading/
├── src/                    # 소스 코드
│   ├── models/            # 도메인 모델
│   ├── api/               # API 통신 계층
│   ├── strategies/        # 매매 전략
│   ├── services/          # 비즈니스 로직
│   ├── simulator/         # In-Memory 시뮬레이터
│   ├── utils/             # 유틸리티
│   ├── config/            # 설정 관리
│   ├── repositories/      # 데이터 저장소
│   └── cli/               # CLI 인터페이스
├── tests/                 # 테스트 코드
│   ├── contract/          # 계약 테스트
│   ├── integration/       # 통합 테스트
│   ├── simulator/         # 시뮬레이터 테스트
│   └── unit/              # 단위 테스트
├── config/                # 설정 파일
├── data/                  # 데이터
└── logs/                  # 로그
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

### 2. 환경 변수 설정

```bash
# .env.example을 .env로 복사
cp .env.example .env

# .env 파일 편집하여 필수 값 설정
# - KIWOOM_API_KEY: 키움증권 API 키
# - KIWOOM_API_SECRET: 키움증권 API 시크릿
# - KIWOOM_ACCOUNT_NUMBER: 계좌 번호
# - DISCORD_WEBHOOK_URL: Discord 웹훅 URL (선택)
```

### 3. 시뮬레이터로 첫 전략 실행

```python
from decimal import Decimal
from src.simulator.kiwoom_simulator import KiwoomSimulator
from src.strategies.golden_cross import GoldenCrossStrategy

# 시뮬레이터 초기화 (초기 자금 100만원)
simulator = KiwoomSimulator(initial_balance=Decimal("1000000"))

# 전략 생성 및 실행
strategy = GoldenCrossStrategy(client=simulator)
await strategy.run()
```

### 4. 테스트 실행

```bash
# 전체 테스트 실행
pytest

# 특정 카테고리 테스트 실행
pytest -m unit          # 단위 테스트만
pytest -m integration   # 통합 테스트만
pytest -m simulator     # 시뮬레이터 테스트만

# 커버리지 리포트 생성
pytest --cov=src --cov-report=html
```

### 5. 코드 품질 검사

```bash
# Ruff 린터 실행
ruff check .

# 자동 수정
ruff check . --fix

# 코드 포매팅
ruff format .
```

## 개발 철학

### Fake Object Driven Development

이 프로젝트는 **"Fake Object Driven Development"**를 따릅니다:

- `unittest.mock` 대신 **KiwoomSimulator**(Fake Object) 사용
- 실제 매수/매도 로직과 잔고 계산이 메모리에서 작동
- 모든 전략 테스트를 시뮬레이터 위에서 수행
- Contract Test로 실제 API와 시뮬레이터의 응답 형식 일치성 검증

### 핵심 원칙

- **안정성 우선**: 모든 주문 실행 전 예수금 확인, 일일 손실 한도 체크
- **명시적 코드**: Type Hinting, Google Style Docstring, Pydantic 모델 사용
- **방어적 프로그래밍**: 모든 API 호출에 Exception Handling 및 재시도 로직
- **관심사의 분리**: API 통신 / 비즈니스 로직 / 도메인 모델 계층 분리

## 사용자 스토리

### US1: 전략 기반 자동 매수/매도 실행 (P1)
사용자가 정의한 매매 전략에 따라 시스템이 자동으로 시장을 감시하고 조건 충족 시 매수/매도 주문을 실행합니다.

### US2: 계좌 상태 및 포지션 모니터링 (P1)
언제든지 현재 계좌 상태, 보유 종목, 손익 현황을 확인할 수 있습니다.

### US3: 전략 유연성 및 교체 (P2)
운영 중인 전략을 중단하고 새로운 전략으로 교체하거나, 여러 전략을 동시에 운영할 수 있습니다.

### US4: 실시간 시장 데이터 수집 및 처리 (P1)
키움증권 REST API를 통해 실시간 체결 데이터와 과거 차트 데이터를 수집하고 전략 판단에 활용합니다.

### US5: 안전한 주문 실행 및 위험 관리 (P1)
주문 전 예수금 확인, 중복 주문 방지, API 통신 오류 시 안전 처리, 일일 손실 한도 관리를 수행합니다.

## 라이선스

MIT License

## 기여

기여는 언제나 환영합니다! Pull Request를 보내주세요.

## 주의사항

⚠️ **경고**: 이 시스템은 실제 금전이 오가는 자동매매 시스템입니다. 다음 사항을 반드시 숙지하세요:

1. **시뮬레이터로 충분히 테스트**: 실전 전에 반드시 시뮬레이터 모드로 전략을 검증하세요
2. **소액으로 시작**: 처음에는 작은 금액으로 시작하여 시스템을 검증하세요
3. **손실 한도 설정**: 일일 손실 한도를 반드시 설정하세요
4. **지속적인 모니터링**: 완전히 방치하지 말고 주기적으로 확인하세요
5. **투자 책임**: 모든 투자 결과에 대한 책임은 사용자에게 있습니다

## 문서

자세한 문서는 `specs/001-kiwoom-auto-trading/` 디렉토리를 참조하세요:

- `spec.md`: 기능 명세
- `plan.md`: 구현 계획
- `tasks.md`: 작업 목록
- `quickstart.md`: 빠른 시작 가이드 (생성 예정)
- `data-model.md`: 데이터 모델 명세 (생성 예정)

## 문의

이슈가 있거나 질문이 있으시면 GitHub Issues를 이용해주세요.
