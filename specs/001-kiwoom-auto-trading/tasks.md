# Tasks: 키움증권 REST API 기반 자동매매 에이전트

**Feature Branch**: `001-kiwoom-auto-trading`
**Created**: 2025-11-22
**Input**: `/specs/001-kiwoom-auto-trading/`의 설계 문서
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**테스트 철학**: 본 프로젝트는 **"Fake Object Driven Development"**를 따릅니다. `unittest.mock`을 사용한 Mockist TDD 대신, 실제 매수/매도 로직과 잔고 계산이 메모리 상에서 작동하는 **KiwoomSimulator**(Fake Object)를 먼저 구축하고, 모든 전략 테스트를 이 시뮬레이터 위에서 수행합니다.

**작업 구성**: 작업은 Phase별로 구성되며, 각 Phase는 명확한 Checkpoint를 가집니다.

---

## 형식: `[ID] [P?] [Story] 설명`

- **[P]**: 병렬 실행 가능 (다른 파일, 의존성 없음)
- **[Story]**: 작업이 속한 사용자 스토리 (예: US1, US2, US3)
- 모든 작업 설명에 정확한 파일 경로 포함

## 프로젝트 경로 규칙

본 프로젝트는 단일 프로젝트 구조를 사용합니다:
- 소스 코드: `src/`
- 테스트 코드: `tests/`
- 설정 파일: `config/`
- 데이터: `data/`
- 로그: `logs/`

---

## Phase 1: Setup (프로젝트 초기화)

**목적**: 프로젝트 구조 생성 및 기본 설정

- [ ] T001 프로젝트 디렉토리 구조 생성 (plan.md 구조에 따라)
- [ ] T002 Python 3.10+ 가상 환경 설정 및 requirements.txt 작성
- [ ] T003 [P] Ruff 린터 설정 (.ruff.toml)
- [ ] T004 [P] pytest 및 pytest-asyncio 설정 (pytest.ini)
- [ ] T005 [P] .env 파일 템플릿 생성 (.env.example)
- [ ] T006 [P] .gitignore 파일 생성 (Python, 환경 변수, 로그, 데이터 제외)
- [ ] T007 [P] README.md 기본 내용 작성

**Checkpoint**: 프로젝트 구조 준비 완료, `pytest` 실행 시 테스트 없음 상태

---

## Phase 2: Building the Simulator (시뮬레이터 구축) 🎯 핵심 우선순위

**목적**: 실제 Kiwoom API 없이도 전략을 테스트할 수 있는 In-Memory Fake Object를 구축합니다. 이 시뮬레이터는 실제 거래소처럼 잔고를 관리하고, 호가창을 시뮬레이션하며, 주문을 체결합니다.

**철학**: "Mock it till you make it" ❌ → "Fake it till you make it" ✅

**⚠️ 중요**: Phase 2가 완료되기 전까지 어떤 전략(US1)도 테스트할 수 없습니다. 시뮬레이터가 모든 전략 테스트의 기반입니다.

### 2.1 기본 데이터 모델 (Simulator와 실제 API가 공유)

- [X] T008 [P] Enum 정의 in src/models/__init__.py (OrderType, OrderStatus, PriceType)
- [X] T009 [P] Stock 모델 구현 in src/models/stock.py (종목코드, 현재가, 거래량, 타임스탬프)
- [X] T010 [P] Account 모델 구현 in src/models/account.py (예수금, 총 평가액, 총 손익)
- [X] T011 [P] Order 모델 구현 in src/models/order.py (주문ID, 종목코드, 주문유형, 가격, 수량, 상태, 체결가, 체결수량)
- [X] T012 [P] Position 모델 구현 in src/models/position.py (종목코드, 수량, 평균매수가, 현재가, 손익, 수익률)

### 2.2 FakeExchange (가상 거래소 엔진)

**목적**: 실제 거래소의 호가창과 체결 로직을 메모리 상에서 시뮬레이션합니다.

- [X] T013 FakeExchange 기본 클래스 구현 in src/simulator/fake_exchange.py
  - 종목별 현재가 관리 (Dict[종목코드, 가격])
  - 호가창 시뮬레이션 (매수호가, 매도호가)
- [X] T014 시장가 주문 체결 로직 구현 in src/simulator/fake_exchange.py
  - 매수 시장가 주문 → 즉시 현재가로 체결
  - 매도 시장가 주문 → 즉시 현재가로 체결
- [X] T015 지정가 주문 체결 로직 구현 in src/simulator/fake_exchange.py
  - 매수 지정가 주문 → 현재가 ≤ 지정가일 때 체결
  - 매도 지정가 주문 → 현재가 ≥ 지정가일 때 체결
- [X] T016 가격 변동 시뮬레이션 기능 추가 in src/simulator/fake_exchange.py
  - `set_price(종목코드, 가격)` 메서드
  - `tick()` 메서드 (시간 경과 시뮬레이션)

### 2.3 KiwoomSimulator (Fake Kiwoom API)

**목적**: 실제 KiwoomClient와 동일한 인터페이스를 가지지만, 모든 동작이 메모리 상에서 이루어지는 Fake Object를 구현합니다.

- [X] T017 KiwoomSimulator 기본 클래스 구현 in src/simulator/kiwoom_simulator.py
  - `__init__(initial_balance: Decimal)` 생성자
  - 내부 상태: 계좌(Account), 포지션(List[Position]), 주문 이력(List[Order])
  - FakeExchange 인스턴스 보유
- [X] T018 `get_account() -> Account` 메서드 구현 in src/simulator/kiwoom_simulator.py
  - 현재 예수금 반환
  - 총 평가액 계산 (예수금 + 모든 포지션 평가액)
  - 총 손익 계산
- [X] T019 `get_positions() -> List[Position]` 메서드 구현 in src/simulator/kiwoom_simulator.py
  - 현재 보유 중인 모든 포지션 반환
  - 각 포지션의 현재가는 FakeExchange에서 조회
- [X] T020 `submit_order(order: Order) -> Order` 메서드 구현 in src/simulator/kiwoom_simulator.py
  - 매수 주문 시 예수금 확인
  - 매도 주문 시 보유 수량 확인
  - FakeExchange에 주문 전달하여 체결
  - 체결 결과에 따라 잔고 및 포지션 업데이트
  - 주문 이력에 저장
- [X] T021 `get_stock_price(stock_code: str) -> Stock` 메서드 구현 in src/simulator/kiwoom_simulator.py
  - FakeExchange에서 현재가 조회
- [X] T022 오류 시나리오 시뮬레이션 기능 추가 in src/simulator/kiwoom_simulator.py
  - `inject_error(error_type: str)` 메서드
  - 예수금 부족 에러 시뮬레이션
  - 잘못된 종목 코드 에러 시뮬레이션
  - API 타임아웃 에러 시뮬레이션

### 2.4 Simulator 자체 테스트

**목적**: Simulator가 정확하게 동작하는지 검증합니다. 전략 테스트 이전에 Simulator 자체의 신뢰성을 확보해야 합니다.

- [X] T023 [P] FakeExchange 시장가 체결 테스트 in tests/simulator/test_fake_exchange.py
  - 매수/매도 시장가 주문이 즉시 체결되는지 확인
- [X] T024 [P] FakeExchange 지정가 체결 테스트 in tests/simulator/test_fake_exchange.py
  - 가격 조건 충족 시에만 체결되는지 확인
- [X] T025 [P] KiwoomSimulator 잔고 관리 테스트 in tests/simulator/test_kiwoom_simulator.py
  - 매수 후 예수금 감소 확인
  - 매도 후 예수금 증가 확인
- [X] T026 [P] KiwoomSimulator 포지션 관리 테스트 in tests/simulator/test_kiwoom_simulator.py
  - 매수 후 포지션 생성 확인
  - 매도 후 포지션 수량 감소 확인
  - 전량 매도 시 포지션 제거 확인
- [X] T027 [P] KiwoomSimulator 오류 시나리오 테스트 in tests/simulator/test_kiwoom_simulator.py
  - 예수금 부족 시 주문 거부 확인
  - 보유 수량 부족 시 매도 거부 확인

**Checkpoint**: Simulator 구축 완료 - 이제 전략을 Simulator 위에서 테스트할 수 있습니다.

---

## Phase 3: Foundational (기반 인프라)

**목적**: 로깅, 설정 관리, 유틸리티 등 모든 컴포넌트가 의존하는 기반 인프라를 구축합니다.

**⚠️ 참고**: Phase 2(Simulator)가 완료되었으므로, 이제 전략 개발과 기반 인프라 구축을 병렬로 진행할 수 있습니다.

### 3.1 핵심 유틸리티 및 설정

- [X] T028 [P] 로깅 설정 구현 in src/utils/logger.py (Google Style Docstring, logging 모듈 사용)
- [X] T029 [P] 시간대 처리 유틸리티 구현 in src/utils/time_utils.py (KST 타임존, 장 운영 시간 체크)
- [X] T030 [P] Decimal 계산 헬퍼 함수 구현 in src/utils/decimal_utils.py
- [X] T031 Pydantic Settings 기반 설정 관리 구현 in src/config/settings.py (config.yaml 로드, 환경 변수 처리)

### 3.2 추가 데이터 모델

- [X] T032 [P] ChartData 모델 구현 in src/models/chart_data.py
- [X] T033 [P] Notification 모델 구현 in src/models/notification.py
- [X] T034 [P] SystemStatus 모델 구현 in src/models/system_status.py
- [X] T035 BaseStrategy 추상 클래스 구현 in src/models/strategy.py (evaluate_buy_signal, evaluate_sell_signal, calculate_position_size 추상 메서드)

### 3.3 데이터베이스 및 저장소 (선택 사항, 초기 MVP에서는 생략 가능)

- [X] T036 SQLite 스키마 정의 및 초기화 in src/repositories/database.py
- [X] T037 [P] OrderRepository 구현 in src/repositories/order_repository.py
- [X] T038 [P] PositionRepository 구현 in src/repositories/position_repository.py

**Checkpoint**: 기반 인프라 준비 완료

---

## Phase 4: User Story 1 - 전략 기반 자동 매수/매도 실행 (Priority: P1) 🎯 MVP

**목표**: 사용자가 정의한 전략에 따라 시스템이 자동으로 매수/매도 주문을 실행

**독립 테스트**: 골든크로스 전략을 **Simulator 위에서** 실행하여 조건 충족 시 주문이 정확히 발생하는지 검증

**⚠️ 핵심**: 모든 테스트는 `unittest.mock` 대신 `KiwoomSimulator`를 import하여 사용합니다.

### 4.1 전략 구현 (Strategy)

- [X] T039 [P] [US1] GoldenCrossStrategy 구현 in src/strategies/golden_cross.py (BaseStrategy 상속, SMA 계산 포함)
- [X] T040 [US1] 전략 동적 로딩 시스템 구현 in src/services/strategy_engine.py (YAML에서 전략 로드, importlib 사용)

### 4.2 전략 테스트 (Simulator 기반 - Mock 없음!)

- [X] T041 [P] [US1] GoldenCrossStrategy 매수 시그널 통합 테스트 in tests/integration/test_golden_cross_strategy.py
  - **중요**: `from src.simulator.kiwoom_simulator import KiwoomSimulator` import
  - Simulator에 과거 가격 데이터 주입
  - 골든크로스 발생 시 매수 주문이 생성되는지 확인
- [X] T042 [P] [US1] GoldenCrossStrategy 매도 시그널 통합 테스트 in tests/integration/test_golden_cross_strategy.py
  - 데드크로스 발생 시 매도 주문이 생성되는지 확인
- [X] T043 [P] [US1] GoldenCrossStrategy 전체 시나리오 테스트 in tests/integration/test_golden_cross_strategy.py
  - 매수 → 가격 상승 → 매도 → 손익 확인

### 4.3 주문 실행 (Order Execution)

- [X] T044 [P] [US1] OrderValidator 구현 in src/services/order_validator.py (예수금 확인, 수량 검증)
- [X] T045 [P] [US1] DuplicateOrderChecker 구현 in src/services/duplicate_checker.py
- [X] T046 [US1] OrderExecutor 구현 in src/services/order_executor.py (주문 검증 → 제출 → 상태 추적)

### 4.4 주문 실행 테스트 (Simulator 기반)

- [X] T047 [P] [US1] OrderValidator 단위 테스트 in tests/unit/test_order_validator.py
- [X] T048 [P] [US1] DuplicateOrderChecker 단위 테스트 in tests/unit/test_duplicate_checker.py
- [X] T049 [US1] 전략 실행 → 주문 생성 → 체결 통합 테스트 in tests/integration/test_trading_flow.py
  - Simulator 사용
  - 전략 시그널 발생 → OrderExecutor → Simulator 체결 → 포지션 확인

**Checkpoint**: User Story 1 완료 - Simulator 위에서 골든크로스 전략이 정상 작동해야 함

---

## Phase 5: Real API Integration (실제 Kiwoom API 연동)

**목적**: Simulator로 검증된 전략을 실제 Kiwoom API에 연결합니다.

**⚠️ 핵심**: 이 단계에서 **Contract Test**를 추가하여 실제 API와 Simulator의 응답 형식이 일치하는지 검증합니다.

### 5.1 실제 Kiwoom API 클라이언트 구현

- [X] T050 키움증권 API 인증 클라이언트 구현 in src/api/kiwoom_client.py (OAuth2 토큰 발급, 갱신 로직)
- [X] T051 Rate Limiter 구현 in src/api/rate_limiter.py (초당 15 req 제한)
- [X] T052 [P] 실시간 시세 조회 API 구현 in src/api/kiwoom_client.py (GET /market/price)
- [X] T053 [P] 일봉 데이터 조회 API 구현 in src/api/kiwoom_client.py (GET /market/chart/daily)
- [X] T054 [P] 매수 주문 API 구현 in src/api/kiwoom_client.py (POST /order/buy)
- [X] T055 [P] 매도 주문 API 구현 in src/api/kiwoom_client.py (POST /order/sell)
- [X] T056 [P] 주문 상태 조회 API 구현 in src/api/kiwoom_client.py (GET /order/status)
- [X] T057 [P] 계좌 잔고 조회 API 구현 in src/api/kiwoom_client.py (GET /account/balance)
- [X] T058 [P] 보유 종목 조회 API 구현 in src/api/kiwoom_client.py (GET /account/positions)
- [X] T059 키움증권 API 에러 처리 및 재시도 로직 구현 in src/api/kiwoom_client.py (최대 3회 재시도)

### 5.2 Contract Test (실제 API vs Simulator 응답 일치 검증) 🎯 핵심

**목적**: 실제 Kiwoom API와 Simulator가 동일한 Pydantic 모델로 파싱되는지 검증합니다.

- [X] T060 [P] Account 응답 형식 계약 테스트 in tests/contract/test_kiwoom_contract.py
  - 실제 API 응답 → Account 모델 파싱 성공
  - Simulator 응답 → Account 모델 파싱 성공
  - 두 응답의 스키마 일치 검증
- [X] T061 [P] Order 응답 형식 계약 테스트 in tests/contract/test_kiwoom_contract.py
- [X] T062 [P] Position 응답 형식 계약 테스트 in tests/contract/test_kiwoom_contract.py
- [X] T063 [P] Stock 응답 형식 계약 테스트 in tests/contract/test_kiwoom_contract.py
- [X] T064 에러 응답 형식 계약 테스트 in tests/contract/test_kiwoom_contract.py
  - 예수금 부족 에러
  - 잘못된 종목 코드 에러
  - API 타임아웃 에러

**Checkpoint**: 실제 API 연동 완료 - Contract Test가 모두 통과해야 하며, Simulator로 테스트한 전략을 실제 API로 전환 가능

---

## Phase 6: User Story 2 - 계좌 상태 및 포지션 모니터링 (Priority: P1)

**목표**: 사용자가 언제든지 계좌 상태, 보유 종목, 손익 현황을 확인 가능

### 6.1 서비스 레이어

- [X] T065 [US2] AccountService 구현 in src/services/account_service.py (계좌 정보 조회, 업데이트, 일일 손익 계산)
- [X] T066 [US2] PositionService 구현 in src/services/position_service.py (포지션 CRUD, 평가 손익 계산)

### 6.2 테스트 (Simulator 기반)

- [X] T067 [P] [US2] AccountService 단위 테스트 in tests/unit/test_account_service.py
- [X] T068 [P] [US2] PositionService 단위 테스트 in tests/unit/test_position_service.py
- [X] T069 [US2] 계좌 상태 조회 통합 테스트 in tests/integration/test_account_status.py

### 6.3 CLI 인터페이스

- [ ] T070 [US2] CLI 'status' 명령 구현 in src/cli/main.py (계좌 현황, 활성 전략, 포지션 출력)
- [ ] T071 [US2] 실시간 상태 업데이트 로직 추가 (주문 체결 시 계좌 자동 업데이트)

**Checkpoint**: User Story 2 완료 - CLI에서 `python -m src.cli.main status` 실행 시 정확한 계좌 정보가 표시되어야 함

---

## Phase 7: User Story 4 - 실시간 시장 데이터 수집 및 처리 (Priority: P1)

**목표**: 키움증권 REST API를 통해 실시간 체결 데이터와 과거 차트 데이터를 수집하고 전략 판단에 활용

### 7.1 데이터 수집기 (DataCollector)

- [X] T072 [US4] DataCollector 인터페이스 구현 in src/services/data_collector.py
- [X] T073 [US4] StaggeredPricePoller 구현 (1초 간격, 종목별 분산 폴링)
- [X] T074 [US4] 차트 데이터 캐싱 로직 구현 (5초 TTL, 최대 1000개 캐시)
- [X] T075 [US4] 데이터 수신 타임아웃 감지 및 재연결 로직 (3분 이상 데이터 없을 시 경고)

### 7.2 테스트 (Simulator 기반)

- [X] T076 [P] [US4] DataCollector 단위 테스트 in tests/unit/test_data_collector.py
- [X] T077 [US4] 데이터 수집 → 전략 평가 통합 테스트 in tests/integration/test_data_flow.py

### 7.3 통합

- [X] T078 [US4] DataCollector를 StrategyEngine에 통합 (asyncio.Queue를 통한 데이터 전달)

**Checkpoint**: User Story 4 완료 - 실시간 데이터가 정상적으로 수집되고 전략 엔진으로 전달되어야 함

---

## Phase 8: User Story 5 - 안전한 주문 실행 및 위험 관리 (Priority: P1)

**목표**: 주문 전 예수금 확인, 중복 주문 방지, API 통신 오류 시 안전 처리, 일일 손실 한도 관리

### 8.1 위험 관리자 (RiskManager)

- [X] T079 [US5] RiskManager 구현 in src/services/risk_manager.py
- [X] T080 [US5] check_daily_loss_limit 메서드 구현 (일일 손실 한도 80% 도달 시 경고)
- [X] T081 [US5] check_position_concentration 메서드 구현 (종목별 최대 30% 집중도 체크)
- [X] T082 [US5] should_stop_trading 메서드 구현 (손실 한도 초과 시 즉시 중단)

### 8.2 테스트 (Simulator 기반)

- [X] T083 [P] [US5] RiskManager 일일 손실 한도 체크 단위 테스트 in tests/unit/test_risk_manager.py
- [X] T084 [P] [US5] RiskManager 포지션 집중도 체크 단위 테스트 in tests/unit/test_risk_manager.py
- [X] T085 [US5] 위험 관리 통합 테스트 (한도 초과 시 자동 매매 중단) in tests/integration/test_risk_management.py

### 8.3 통합

- [X] T086 [US5] OrderExecutor에 RiskManager 통합 (주문 전 위험 검증)
- [X] T087 [US5] StrategyEngine에 위험 관리 로직 추가 (매 주문 전 위험 체크)

**Checkpoint**: User Story 5 완료 - 위험 관리 로직이 정상 작동하여 안전하게 주문이 실행되어야 함

---

## Phase 9: User Story 3 - 전략 유연성 및 교체 (Priority: P2)

**목표**: 사용자가 운영 중인 전략을 중단하고 새로운 전략으로 교체하거나, 여러 전략을 동시 운영

### 9.1 다중 전략 지원

- [ ] T088 [US3] 전략별 자금 할당 로직 구현 in src/services/strategy_engine.py
- [ ] T089 [US3] 전략 활성화/비활성화 메서드 구현 (enable/disable)
- [ ] T090 [US3] 여러 전략 병렬 실행 로직 구현 (asyncio.gather)

### 9.2 테스트

- [ ] T091 [P] [US3] 전략 동적 로드 단위 테스트 in tests/unit/test_strategy_engine.py
- [ ] T092 [P] [US3] 다중 전략 병렬 실행 단위 테스트 in tests/unit/test_strategy_engine.py
- [ ] T093 [US3] 전략 교체 통합 테스트 in tests/integration/test_strategy_swap.py

### 9.3 CLI 명령 추가

- [ ] T094 [US3] CLI 'enable-strategy' 명령 구현 in src/cli/main.py
- [ ] T095 [US3] CLI 'disable-strategy' 명령 구현 in src/cli/main.py

**Checkpoint**: User Story 3 완료 - 여러 전략을 동시에 운영하거나 교체할 수 있어야 함

---

## Phase 10: User Story 6 - 시스템 헬스 체크 및 자가 진단 (Priority: P2)

**목표**: 시스템이 자신의 상태를 주기적으로 점검하고, API 연결 상태, 데이터 수신 정상 여부를 확인하며 이상 발생 시 사용자에게 알림

### 10.1 헬스 체크 구현

- [ ] T096 [US6] HealthCheck 구현 in src/services/health_check.py
- [ ] T097 [US6] check_api_connection 메서드 구현
- [ ] T098 [US6] check_data_freshness 메서드 구현 (마지막 데이터 수신 시간 확인)
- [ ] T099 [US6] 주기적 헬스 체크 백그라운드 태스크 구현 (1분 간격)

### 10.2 테스트

- [ ] T100 [P] [US6] HealthCheck API 연결 체크 단위 테스트 in tests/unit/test_health_check.py
- [ ] T101 [P] [US6] HealthCheck 데이터 수신 체크 단위 테스트 in tests/unit/test_health_check.py
- [ ] T102 [US6] 헬스 체크 통합 테스트 (연결 끊김 시 알림 전송) in tests/integration/test_health_monitoring.py

### 10.3 통합

- [ ] T103 [US6] 이상 감지 시 자동 재연결 로직 구현
- [ ] T104 [US6] 헬스 체크 결과를 SystemStatus에 반영

**Checkpoint**: User Story 6 완료 - 시스템이 자동으로 상태를 모니터링하고 이상 징후를 감지해야 함

---

## Phase 11: User Story 7 - 알림 및 트레이딩 리포팅 (Priority: P2)

**목표**: 주요 이벤트(주문 체결, 오류 발생, 장 마감 등) 발생 시 사용자에게 알림을 보내고, 일일 트레이딩 결과를 요약하여 제공

### 11.1 알림 구현

- [ ] T105 [P] [US7] DiscordNotifier 구현 in src/services/notifier.py (discord-webhook 사용)
- [ ] T106 [P] [US7] EmailNotifier 구현 in src/services/notifier.py (aiosmtplib 사용)
- [ ] T107 [US7] NotificationManager 구현 (여러 알림 채널 통합 관리)

### 11.2 리포트 생성

- [ ] T108 [US7] DailyReportGenerator 구현 in src/services/report_generator.py (당일 거래 내역, 손익, 승률 계산)
- [ ] T109 [US7] 장 마감 시 자동 리포트 전송 로직 구현 (15:30 KST)

### 11.3 테스트

- [ ] T110 [P] [US7] DiscordNotifier 단위 테스트 in tests/unit/test_notifier.py
- [ ] T111 [P] [US7] EmailNotifier 단위 테스트 in tests/unit/test_notifier.py
- [ ] T112 [US7] 일일 리포트 생성 통합 테스트 in tests/integration/test_daily_report.py

### 11.4 통합

- [ ] T113 [US7] OrderExecutor에 알림 통합 (주문 체결 시 알림 전송)
- [ ] T114 [US7] HealthCheck에 알림 통합 (오류 발생 시 긴급 알림)
- [ ] T115 [US7] RiskManager에 알림 통합 (손실 한도 경고 알림)

**Checkpoint**: User Story 7 완료 - 주요 이벤트 발생 시 Discord/Email 알림이 정상 전송되어야 함

---

## Phase 12: CLI 및 시스템 통합 (필수)

**목적**: 모든 컴포넌트를 통합하여 실행 가능한 시스템 구축

### 12.1 메인 애플리케이션

- [ ] T116 TradingSystem 메인 클래스 구현 in src/cli/main.py (모든 서비스 통합, asyncio event loop 관리)
- [X] T117 CLI 명령 파서 구현 (start, stop, status, backtest, validate-config, test-api 등)
- [X] T118 Graceful shutdown 로직 구현 (SIGINT 핸들러, 모든 태스크 정리)

### 12.2 CLI 명령 구현

- [X] T119 [P] CLI 'start' 명령 구현 (시스템 시작, 시뮬레이터/실전 모드 선택)
- [X] T120 [P] CLI 'stop' 명령 구현 (시스템 중지, 포지션 보존)
- [X] T121 [P] CLI 'emergency-stop' 명령 구현 (긴급 중단, 모든 주문 취소)
- [X] T122 [P] CLI 'validate-config' 명령 구현 (설정 파일 검증)
- [X] T123 [P] CLI 'test-api' 명령 구현 (API 연결 테스트)

### 12.3 백테스팅 모드

- [X] T124 BacktestEngine 구현 in src/services/backtest_engine.py (과거 데이터 기반 시뮬레이션)
- [X] T125 CLI 'backtest' 명령 구현 (전략, 기간, 초기 자금 지정)
- [X] T126 백테스팅 결과 리포트 생성 (총 손익, 승률, Sharpe Ratio, 최대 낙폭)

### 12.4 통합 테스트

- [X] T127 전체 시스템 통합 테스트 in tests/integration/test_full_system.py (시작 → 데이터 수집 → 전략 실행 → 주문 → 중지)
- [X] T128 백테스트 모드 통합 테스트 in tests/integration/test_backtest.py

**Checkpoint**: 시스템 통합 완료 - CLI로 시스템을 시작/중지하고 전체 플로우가 정상 작동해야 함

---

## Phase 13: Polish & Cross-Cutting Concerns (마무리)

**목적**: 여러 사용자 스토리에 걸친 개선 사항 및 최종 검증

### 13.1 문서화

- [ ] T129 [P] API 문서 업데이트 및 보완
- [ ] T130 [P] quickstart.md 검증 및 업데이트 (실제 실행 가능 여부 확인)
- [ ] T131 [P] 코드 주석 및 Docstring 검토 (Google Style 준수)

### 13.2 코드 품질

- [ ] T132 [P] Ruff 린터 실행 및 모든 경고 해결
- [ ] T133 코드 리뷰 및 리팩토링 (중복 코드 제거, 함수 분리)

### 13.3 보안 및 성능

- [ ] T134 [P] 민감 정보 하드코딩 체크 (API 키, 비밀번호 등)
- [ ] T135 성능 최적화 (asyncio 이벤트 루프 지연 모니터링, 불필요한 API 호출 제거)

### 13.4 최종 검증

- [ ] T136 전체 테스트 스위트 실행 및 100% 통과 확인
- [ ] T137 Simulator 모드로 1년 데이터 백테스팅 (전략이 정상 작동하는지 확인)
- [ ] T138 실전 모드 체크리스트 검증 (quickstart.md 기준)

---

## 의존성 및 실행 순서

### Phase 의존성

- **Phase 1 (Setup)**: 의존성 없음 - 즉시 시작 가능
- **Phase 2 (Simulator)**: Setup 완료 후 시작 - **모든 전략 테스트를 차단**
- **Phase 3 (Foundational)**: Setup 완료 후 시작 가능 - Phase 2와 병렬 가능
- **Phase 4 (US1 - 전략)**: Phase 2 완료 필수 - Simulator 없이는 테스트 불가
- **Phase 5 (Real API)**: Phase 4 완료 후 시작 권장 - Simulator로 검증된 전략을 실제 API에 연결
- **Phase 6-11 (기타 US)**: Phase 2, 3 완료 후 병렬 시작 가능
- **Phase 12 (CLI 통합)**: 원하는 US가 완료된 후 시작
- **Phase 13 (Polish)**: 모든 핵심 기능 완료 후 시작

### 핵심 차이점: Simulator First!

**기존 Mockist TDD 순서**:
1. Setup → Foundational → 전략 구현 → Mock 작성 → 테스트 → 실제 API 구현

**새로운 Fake Object 순서**:
1. Setup → **Simulator 구축** → Simulator 테스트 → 전략 구현 → Simulator로 전략 테스트 → 실제 API 구현 → Contract Test

**왜 이렇게 하나요?**
- Mock은 "행동"만 흉내내지만, Fake는 "상태"를 가집니다.
- Simulator는 실제 잔고 계산과 체결 로직을 가지므로, 전략 테스트가 E2E 동작과 훨씬 가깝습니다.
- Contract Test로 실제 API와 Simulator의 응답 일치를 보장하므로, Simulator 테스트가 곧 실전 신뢰성을 의미합니다.

---

## 작업 통계

- **총 작업 수**: 138개
- **Phase별 작업 수**:
  - Setup: 7개
  - **Simulator: 20개** 🎯 (기존 Mockist TDD에는 없었던 단계)
  - Foundational: 11개
  - User Story 1 (P1): 11개
  - Real API Integration: 15개 (Contract Test 포함)
  - User Story 2-7: 약 50개
  - CLI 통합: 13개
  - Polish: 10개

- **MVP 범위** (Setup + Simulator + Foundational + US1 + Real API): 약 60개 작업

---

## 권장 MVP 범위

**초기 MVP** (약 3-4주 작업):
- Phase 1: Setup (7개 작업)
- **Phase 2: Simulator 구축 (20개 작업)** 🎯 최우선
- Phase 3: Foundational (11개 작업 중 필수만)
- Phase 4: User Story 1 - 전략 기반 자동 매수/매도 (11개 작업)
- Phase 5: Real API Integration (15개 작업)
- Phase 12: CLI 통합 (13개 작업 중 필수만)

**총 약 65-70개 작업**으로 핵심 가치를 제공하는 동작하는 자동매매 시스템을 구축할 수 있습니다.

**핵심 철학**: Simulator를 먼저 구축하고, 그 위에서 모든 전략을 테스트하고, 마지막에 실제 API를 붙인다. Contract Test로 양쪽 일치성을 보장한다.

---

## 참고 사항

- [P] 작업 = 다른 파일, 의존성 없음
- [Story] 레이블은 작업을 특정 사용자 스토리에 매핑하여 추적성 확보
- **Simulator 먼저, 전략은 그 다음!**
- **Mock 대신 Fake Object를 사용하여 실전과 유사한 테스트 환경 구축**
- **Contract Test로 실제 API와 Simulator의 일치성 보장**
- 각 작업 또는 논리적 그룹 후 커밋
- 어느 체크포인트에서든 중지하여 독립적으로 검증

---

**다음 단계**: `/speckit.implement` 명령으로 tasks.md의 작업을 순차적으로 실행하거나, 수동으로 작업을 진행하세요.
