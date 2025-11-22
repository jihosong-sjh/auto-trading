# Implementation Plan: 키움증권 REST API 기반 자동매매 에이전트

**Branch**: `001-kiwoom-auto-trading` | **Date**: 2025-11-22 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-kiwoom-auto-trading/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

사용자가 정의한 투자 전략에 따라 자동으로 주식 매매를 수행하는 서버 기반 자동매매 시스템을 구축한다. 키움증권 REST API를 통해 실시간 시장 데이터를 수집하고, 사전 정의된 매매 로직에 따라 자동으로 주문을 실행하며, 안전성과 신뢰성을 최우선으로 한다.

**핵심 기술 전략**:
- **In-Memory Simulator 기반 테스트**: 단순 Mock 대신, 실제 잔고 계산과 주문 체결 로직을 가진 `KiwoomSimulator`를 구현하여 모든 전략 테스트를 시뮬레이터 위에서 수행한다.
- **Contract Testing**: 실제 Kiwoom API와 Simulator의 응답 형식이 일치하는지 검증하는 계약 테스트를 유지한다.
- **Defensive Programming**: 모든 API 호출은 재시도 로직과 예외 처리를 포함하며, 금전 계산은 `Decimal` 타입을 사용하여 부동소수점 오차를 방지한다.
- **비동기 처리**: 실시간 데이터 수신과 주문 실행을 위해 `asyncio` 기반 비동기 아키텍처를 채택한다.

## Technical Context

**Language/Version**: Python 3.10+

**Primary Dependencies**:
- `httpx` (비동기 HTTP 클라이언트)
- `pydantic` (데이터 검증 및 직렬화)
- `pytest` + `pytest-asyncio` (테스트 프레임워크)
- `pytz` (시간대 처리)
- `python-decimal` (금전 계산)

**Storage**:
- 초기 버전: In-Memory 상태 관리 (계좌, 포지션, 주문)
- 향후 확장: SQLite 또는 PostgreSQL (주문 이력, 백테스팅 데이터)

**Testing**:
- `pytest` (단위 테스트, 통합 테스트)
- `KiwoomSimulator` (In-Memory Fake Object)
- Contract Tests (실제 API vs Simulator 응답 일치성 검증)

**Target Platform**: Linux/Windows 서버 (24시간 구동 가능한 환경)

**Project Type**: Single project (Python 패키지 구조)

**Performance Goals**:
- 조건 충족 시 5초 이내 주문 실행
- 최소 50개 종목 동시 감시
- API 연결 유지율 99% 이상 (장 운영 시간 기준)

**Constraints**:
- 키움증권 API Rate Limit 준수 (초당 요청 제한)
- 장 운영 시간(09:00-15:30) 동작
- 예수금 초과 주문 방지
- 중복 주문 방지

**Scale/Scope**:
- 단일 사용자
- 최대 100개 종목 감시
- 일일 최대 100건 주문

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### 준수 원칙 (Compliant)

[OK] **안정성 우선 (Safety First)**:
- 모든 주문 실행 전 예수금 확인
- 일일 손실 한도 체크
- API 실패 시 재시도 로직

[OK] **명시적 코드 (Explicit is better than implicit)**:
- 모든 함수에 Type Hinting 적용
- Google Style Docstring 작성 (한국어)
- Raw Dictionary 대신 Pydantic 모델 사용

[OK] **방어적 프로그래밍 (Defensive Programming)**:
- 모든 API 호출에 Exception Handling
- 네트워크 실패 시 최대 3회 재시도
- 타임아웃 설정

[OK] **관심사의 분리 (Separation of Concerns)**:
- API 통신 계층 (`KiwoomClient`)
- 비즈니스 로직 계층 (`Strategy`, `OrderExecutor`)
- 도메인 모델 (`Account`, `Position`, `Order`)

[OK] **의존성 주입 (Dependency Injection)**:
- `Strategy`는 `KiwoomClient`를 생성자에서 주입받음
- 테스트 시 실제 클라이언트 대신 `KiwoomSimulator` 주입

[OK] **부동소수점 처리**:
- 가격, 수량, 수익률 계산에 `decimal.Decimal` 사용

[OK] **시간 처리**:
- `pytz`를 사용하여 KST 기준 시간 처리
- 장 운영 시간 체크 로직

[OK] **로그 남기기 (Logging)**:
- `logging` 모듈 사용 (print 금지)
- 주문 실행 로그는 INFO 레벨 이상
- 타임스탬프, 종목코드, 가격, 수량 포함

[OK] **Fakes over Mocks (NEW)**:
- **KiwoomSimulator**: 상태를 가진 In-Memory Fake Object
  - 잔고(balance) 관리
  - 포지션(positions) 관리
  - 주문 체결 시뮬레이션 (시장가/지정가)
  - 오류 시나리오 시뮬레이션 (예수금 부족, API 실패 등)
- **모든 전략 테스트는 Simulator 위에서 수행**

[OK] **Contract Testing**:
- 실제 Kiwoom API 응답과 Simulator 응답의 스키마 일치 검증
- Pydantic 모델을 사용하여 타입 안정성 보장

[OK] **Integration First**:
- 전략 <-> OrderExecutor <-> KiwoomClient 전체 플로우 테스트
- 단위 테스트보다 통합 테스트에 비중

### 잠재적 복잡성 (Potential Complexity)

[WARN] **비동기 프로그래밍 (asyncio)**:
- 실시간 데이터 스트리밍을 위해 필요
- 팀이 비동기 패턴에 익숙하지 않을 경우 학습 곡선 존재
- **정당화**: 키움 API의 실시간 데이터 수신과 주문 실행을 동시에 처리하려면 비동기 처리가 필수적

## Project Structure

### Documentation (this feature)

```text
specs/001-kiwoom-auto-trading/
├── plan.md              # 이 파일 (/speckit.plan 명령 출력)
├── research.md          # Phase 0 출력 (/speckit.plan 명령)
├── data-model.md        # Phase 1 출력 (/speckit.plan 명령)
├── quickstart.md        # Phase 1 출력 (/speckit.plan 명령)
├── contracts/           # Phase 1 출력 (/speckit.plan 명령)
│   ├── kiwoom-api.md    # Kiwoom API 계약 명세
│   └── simulator.md     # KiwoomSimulator 계약 명세
└── tasks.md             # Phase 2 출력 (/speckit.tasks 명령 - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/
├── models/              # 도메인 모델
│   ├── account.py       # Account, Balance
│   ├── stock.py         # Stock, ChartData
│   ├── order.py         # Order, OrderType, OrderStatus
│   └── position.py      # Position
├── api/                 # API 통신 계층
│   ├── client.py        # KiwoomClient (실제 API)
│   └── simulator.py     # KiwoomSimulator (Fake Object)
├── strategy/            # 전략 엔진
│   ├── base.py          # Strategy 추상 클래스
│   └── simple_ma.py     # 예제: 단순 이동평균 전략
├── executor/            # 주문 실행 및 관리
│   ├── order_executor.py  # 주문 실행기
│   └── risk_manager.py    # 위험 관리 (예수금 체크, 손실 한도)
├── data/                # 데이터 수집 및 처리
│   └── collector.py     # 실시간 데이터 수집기
├── notification/        # 알림 시스템
│   ├── discord.py       # 디스코드 웹훅
│   └── email.py         # 이메일 알림
└── main.py              # 진입점

tests/
├── contract/            # 계약 테스트 (API vs Simulator)
│   └── test_kiwoom_contract.py
├── integration/         # 통합 테스트 (Simulator 기반)
│   ├── test_strategy_execution.py
│   └── test_order_flow.py
├── simulator/           # Simulator 자체 테스트
│   └── test_simulator.py
└── unit/                # 단위 테스트
    ├── test_models.py
    └── test_risk_manager.py
```

**Structure Decision**: Single project 구조를 선택했다. 이 시스템은 백엔드 API 서버가 아니라 독립 실행 Python 애플리케이션이므로, `src/` 하나로 충분하다. 테스트는 4계층으로 구분한다:
1. **contract/**: 실제 API와 Simulator의 응답 일치성 검증
2. **integration/**: 전략 <-> 실행기 <-> Simulator 전체 플로우 테스트
3. **simulator/**: Simulator 자체의 상태 관리 및 체결 로직 검증
4. **unit/**: 개별 컴포넌트 단위 테스트

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| asyncio (비동기 프로그래밍) | 키움 API의 실시간 데이터 스트리밍과 주문 실행을 동시 처리 필요 | 동기 방식으로는 실시간 데이터 수신 중 주문 실행이 블로킹되어 타이밍 손실 발생 |

---

## Phase 0: Research Tasks

> **목적**: 구현 전 기술적 불확실성을 해소하고 명확한 설계 근거를 확보한다.

### 0.1 키움증권 REST API 조사

**목표**: 키움증권 REST API의 인증 방식, 주요 엔드포인트, Rate Limit, 응답 형식을 파악한다.

**조사 항목**:
1. **인증 및 토큰 관리**
   - OAuth 2.0 또는 API Key 방식 확인
   - 토큰 갱신 주기 및 방법
   - 토큰 만료 시 재인증 플로우

2. **주요 엔드포인트**
   - 계좌 조회 (예수금, 보유 종목)
   - 실시간 체결 데이터 수신 (WebSocket or Long Polling)
   - 과거 차트 데이터 조회 (일봉, 분봉)
   - 주문 실행 (매수, 매도)
   - 주문 체결 확인 및 취소

3. **Rate Limit 및 제약 사항**
   - 초당 요청 제한
   - 일일 요청 제한
   - 동시 연결 수 제한

4. **응답 형식 및 에러 코드**
   - 성공 응답 구조 (JSON 스키마)
   - 에러 응답 코드 및 의미
   - 일반적인 에러 시나리오 (예수금 부족, 종목 코드 오류 등)

**산출물**: `research.md` 섹션 "1. Kiwoom API 명세"

---

### 0.2 실시간 데이터 수신 방식 조사

**목표**: 실시간 주식 체결 데이터를 어떻게 수신할지 결정한다.

**조사 항목**:
1. **WebSocket vs Long Polling vs Server-Sent Events**
   - 키움 API가 지원하는 방식 확인
   - 각 방식의 장단점 (연결 안정성, 지연 시간, 구현 복잡도)

2. **데이터 스트림 구조**
   - 실시간 체결 데이터 형식 (종목코드, 현재가, 거래량, 시간)
   - 여러 종목 동시 구독 방법
   - 구독 해제 및 재구독 방법

3. **연결 끊김 처리**
   - 재연결 전략 (Exponential Backoff)
   - 데이터 누락 감지 및 복구 방법

**산출물**: `research.md` 섹션 "2. 실시간 데이터 수신 전략"

---

### 0.3 주문 실행 안전성 조사

**목표**: 주문 실행 시 발생할 수 있는 모든 엣지 케이스를 파악하고 대응 방안을 수립한다.

**조사 항목**:
1. **주문 상태 전이**
   - 주문 전송 → 접수 → 체결 → 완료
   - 부분 체결 처리
   - 미체결 주문 타임아웃

2. **중복 주문 방지**
   - 동일 종목 동시 주문 방지 메커니즘
   - Idempotency Key 사용 여부

3. **예수금 초과 방지**
   - 주문 전 예수금 확인 타이밍
   - 동시 다발 주문 시 예수금 동기화 이슈

4. **API 실패 시나리오**
   - 네트워크 타임아웃
   - 키움 서버 오류 (5xx)
   - 재시도 전략 (최대 횟수, 대기 시간)

**산출물**: `research.md` 섹션 "3. 주문 실행 안전성 설계"

---

### 0.4 In-Memory Simulator 설계 조사

**목표**: `KiwoomSimulator`가 어떤 상태를 가지고, 어떤 로직을 구현해야 하는지 명확히 한다.

**조사 항목**:
1. **Simulator가 관리할 상태**
   - 계좌 잔고 (예수금)
   - 보유 포지션 (종목별 수량, 평균 매수가)
   - 주문 이력 (전송된 주문, 체결된 주문, 취소된 주문)
   - 현재 시장 가격 (시뮬레이션용 가격 데이터)

2. **체결 로직 구현**
   - 시장가 주문: 즉시 체결 (현재가 기준)
   - 지정가 주문: 현재가 ≤ 매수 지정가 or 현재가 ≥ 매도 지정가일 때 체결
   - 부분 체결 시뮬레이션 (선택 사항)

3. **오류 시나리오 시뮬레이션**
   - 예수금 부족 시 주문 거부
   - 잘못된 종목 코드
   - API 타임아웃 (인위적 지연)

4. **실제 API와의 인터페이스 일치**
   - 메서드 시그니처 동일
   - 응답 형식 동일 (Pydantic 모델 공유)

**산출물**: `research.md` 섹션 "4. KiwoomSimulator 상세 설계"

---

### 0.5 비동기 Python 패턴 조사

**목표**: `asyncio` 기반 실시간 데이터 수신과 주문 실행을 동시에 처리하는 아키텍처를 설계한다.

**조사 항목**:
1. **asyncio 기본 패턴**
   - `async def`, `await` 사용법
   - `asyncio.create_task()` vs `asyncio.gather()`
   - `asyncio.Queue`를 사용한 생산자-소비자 패턴

2. **실시간 데이터 처리**
   - WebSocket 연결을 `async for` 루프로 처리
   - 데이터 수신과 전략 실행을 병렬 처리

3. **에러 처리 및 취소**
   - `try-except` in async context
   - `asyncio.CancelledError` 처리
   - Task 취소 및 정리 (shutdown)

4. **httpx 비동기 클라이언트**
   - `httpx.AsyncClient` 사용법
   - 재시도 및 타임아웃 설정

**산출물**: `research.md` 섹션 "5. 비동기 아키텍처 설계"

---

### 0.6 알림 시스템 조사

**목표**: 디스코드 웹훅과 이메일 알림을 어떻게 구현할지 결정한다.

**조사 항목**:
1. **디스코드 웹훅**
   - Webhook URL 설정
   - 메시지 형식 (Embed vs Plain Text)
   - Rate Limit 및 에러 처리

2. **이메일 알림**
   - SMTP 서버 설정 (Gmail, SendGrid 등)
   - 비동기 이메일 전송 라이브러리 (`aiosmtplib`)
   - 템플릿 엔진 (Jinja2)

3. **알림 우선순위**
   - 긴급 알림 (시스템 오류, 손실 한도 초과) → 즉시 전송
   - 일반 알림 (주문 체결) → 배치 전송 (1분 단위)

**산출물**: `research.md` 섹션 "6. 알림 시스템 설계"

---

## Phase 1: Design Tasks

> **목적**: Phase 0 조사 결과를 바탕으로 구현 가능한 명세를 작성한다.

### 1.1 데이터 모델 설계

**목표**: 모든 도메인 객체의 Pydantic 모델을 정의한다.

**작업 내용**:
1. **Account 모델**
   ```python
   class Account(BaseModel):
       account_number: str
       balance: Decimal
       total_value: Decimal
       total_pnl: Decimal
   ```

2. **Stock 모델**
   ```python
   class Stock(BaseModel):
       code: str
       name: str
       current_price: Decimal
       volume: int
       timestamp: datetime
   ```

3. **Order 모델**
   ```python
   class OrderType(str, Enum):
       BUY = "buy"
       SELL = "sell"

   class OrderStatus(str, Enum):
       PENDING = "pending"
       SUBMITTED = "submitted"
       FILLED = "filled"
       CANCELLED = "cancelled"
       FAILED = "failed"

   class Order(BaseModel):
       order_id: str
       stock_code: str
       order_type: OrderType
       price: Decimal
       quantity: int
       status: OrderStatus
       filled_quantity: int = 0
       filled_price: Decimal = Decimal("0")
       timestamp: datetime
   ```

4. **Position 모델**
   ```python
   class Position(BaseModel):
       stock_code: str
       quantity: int
       average_price: Decimal
       current_price: Decimal
       pnl: Decimal
       pnl_percent: Decimal
   ```

**산출물**: `data-model.md`

---

### 1.2 API 계약 명세 작성

**목표**: 실제 Kiwoom API와 KiwoomSimulator가 준수해야 할 인터페이스를 문서화한다.

**작업 내용**:
1. **KiwoomClient 추상 인터페이스**
   ```python
   class KiwoomClientProtocol(Protocol):
       async def get_account(self) -> Account:
           pass

       async def get_positions(self) -> list[Position]:
           pass

       async def submit_order(self, order: Order) -> Order:
           pass

       async def get_stock_price(self, stock_code: str) -> Stock:
           pass
   ```

2. **실제 KiwoomClient 구현 요구사항**
   - httpx.AsyncClient 사용
   - 재시도 로직 (최대 3회)
   - 타임아웃 설정 (10초)
   - 에러 응답 파싱 및 예외 발생

3. **KiwoomSimulator 구현 요구사항**
   - 위와 동일한 인터페이스
   - In-Memory 상태 관리
   - 체결 로직 구현
   - 오류 시나리오 주입 기능

**산출물**: `contracts/kiwoom-api.md`

---

### 1.3 Simulator 계약 테스트 작성

**목표**: 실제 API와 Simulator의 응답 형식이 일치하는지 검증하는 테스트를 설계한다.

**작업 내용**:
1. **테스트 케이스**
   - `test_get_account_returns_account_model`: 응답이 `Account` 모델로 파싱되는지 확인
   - `test_submit_order_returns_order_model`: 응답이 `Order` 모델로 파싱되는지 확인
   - `test_error_response_raises_exception`: 에러 응답 시 적절한 예외 발생

2. **테스트 전략**
   - 실제 API 호출 시 응답을 JSON으로 저장
   - Simulator가 동일한 JSON 응답을 반환하는지 검증

**산출물**: `contracts/simulator.md` (테스트 케이스 명세)

---

### 1.4 퀵스타트 가이드 작성

**목표**: 개발자가 프로젝트를 클론하고 30분 내에 첫 전략을 실행할 수 있도록 안내한다.

**작업 내용**:
1. **환경 설정**
   ```bash
   # Python 3.10+ 설치 확인
   python --version

   # 의존성 설치
   pip install -r requirements.txt

   # 환경 변수 설정
   cp .env.example .env
   # KIWOOM_API_KEY, DISCORD_WEBHOOK_URL 등 설정
   ```

2. **Simulator로 첫 전략 실행**
   ```python
   from src.api.simulator import KiwoomSimulator
   from src.strategy.simple_ma import SimpleMovingAverageStrategy

   # Simulator initialization
   simulator = KiwoomSimulator(initial_balance=Decimal("1000000"))

   # Execute strategy
   strategy = SimpleMovingAverageStrategy(client=simulator)
   await strategy.run()
   ```

3. **테스트 실행**
   ```bash
   # Run all tests
   pytest

   # Run integration tests only
   pytest tests/integration/
   ```

**산출물**: `quickstart.md`

---

## Phase 2: Task Generation (NOT in this plan)

> **Phase 2는 `/speckit.tasks` 명령으로 별도 실행된다.**

`tasks.md` 파일은 이 plan.md를 기반으로 `/speckit.tasks` 명령을 실행할 때 생성된다. 이 명령은 Phase 0, Phase 1의 산출물을 바탕으로 구체적인 구현 작업을 의존성 순서대로 나열한다.

---

## Success Criteria for This Plan

이 plan.md가 성공적으로 작성되었다고 판단하는 기준:

[OK] **명확성**: Phase 0의 각 조사 항목이 구체적이고, 무엇을 조사해야 하는지 명확하다.
[OK] **완전성**: Phase 1의 설계 작업이 Phase 0 조사 결과를 모두 반영한다.
[OK] **추적 가능성**: Constitution의 모든 원칙이 어떻게 준수되는지 명시되어 있다.
[OK] **실행 가능성**: 개발자가 이 문서만 읽고 Phase 0 조사를 시작할 수 있다.
[OK] **Simulator 중심**: In-Memory Simulator가 핵심 테스트 전략임을 강조하고, 설계 섹션에 명시되어 있다.

---

## Next Steps

1. **Phase 0 실행**: `/speckit.plan` 명령이 자동으로 `research.md`를 생성한다.
2. **Phase 1 실행**: 조사 결과를 바탕으로 `data-model.md`, `contracts/`, `quickstart.md`를 생성한다.
3. **Constitution 재확인**: Phase 1 완료 후 설계가 모든 원칙을 준수하는지 검토한다.
4. **Task 생성**: `/speckit.tasks` 명령으로 `tasks.md`를 생성하여 구현 단계로 진입한다.
