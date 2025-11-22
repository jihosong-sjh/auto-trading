# Implementation Plan: 키움증권 REST API 기반 자동매매 에이전트

**Branch**: `001-kiwoom-auto-trading` | **Date**: 2025-11-22 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-kiwoom-auto-trading/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

사용자가 정의한 투자 전략에 따라 자동으로 주식 매매를 수행하는 서버 기반 자동매매 시스템을 구축한다. 키움증권 REST API를 통해 실시간 시장 데이터를 수집하고, 사전 정의된 매매 로직에 따라 자동으로 주문을 실행하며, 사용자가 HTS 앞에 앉아있지 않아도 24시간 시장을 감시하고 거래할 수 있도록 지원한다.

**기술 접근 방식**: Python 3.10+ 기반의 비동기(async/await) 아키텍처를 사용하여 실시간 데이터 수집과 전략 실행을 병렬 처리하고, 모듈화된 전략 시스템과 방어적 프로그래밍을 통해 안정성과 확장성을 확보한다.

## Technical Context

**Language/Version**: Python 3.10+

**Primary Dependencies**:
  - `aiohttp` - 비동기 HTTP 클라이언트 (키움증권 REST API 통신)
  - `pydantic` - 데이터 검증 및 DTO 모델링
  - NEEDS CLARIFICATION - 실시간 데이터 수신 방식 (WebSocket vs REST Polling)
  - NEEDS CLARIFICATION - 전략 정의 방식 (Python 코드 vs DSL/YAML)
  - NEEDS CLARIFICATION - 알림 전송 라이브러리 (Discord webhook, Email SMTP)

**Storage**:
  - SQLite (주문 내역, 포지션 히스토리, 로그 기록)
  - 인메모리 (실시간 가격 데이터, 활성 포지션)
  - 파일 기반 (전략 설정, 시스템 설정)

**Testing**:
  - pytest (단위 테스트, 통합 테스트)
  - pytest-asyncio (비동기 코드 테스트)
  - pytest-mock (API 모킹)

**Target Platform**:
  - Linux/Windows Server (24시간 구동)
  - Python 3.10+ 런타임

**Project Type**: Single (서버 애플리케이션 - CLI 인터페이스 우선)

**Performance Goals**:
  - 조건 충족 시 5초 이내 주문 실행
  - 최소 50개 종목 동시 모니터링
  - API 재연결 30초 이내 완료

**Constraints**:
  - 키움증권 REST API Rate Limit 준수 (NEEDS CLARIFICATION - 정확한 제한 사항)
  - 장 운영 시간(09:00-15:30) 99% 이상 가용성
  - 메모리 사용량 < 500MB (50개 종목 기준)
  - 오류 방지율 100% (잘못된 주문 방지)

**Scale/Scope**:
  - 초기 버전: 단일 계좌, 최대 100개 종목 모니터링
  - 동시 실행 전략: 5개 이하
  - 예상 코드 규모: ~5,000 LOC

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### ✅ 통과 항목 (Passing Criteria)

1. **안정성 우선 (Safety First)**:
   - ✅ 주문 실행 전 예수금 확인 (FR-011)
   - ✅ 중복 주문 방지 로직 (FR-012)
   - ✅ 일일 손실 한도 강제 중단 (FR-016)
   - ✅ API 통신 실패 시 재시도 및 안전 처리 (FR-014)

2. **명시적 코드 (Explicit over Implicit)**:
   - ✅ Type Hinting 의무화 (constitution: Type Hinting)
   - ✅ Google Style Docstring 의무화
   - ✅ API 응답 즉시 DTO 변환 (Raw Dict 지양)

3. **방어적 프로그래밍 (Defensive Programming)**:
   - ✅ 모든 API 요청에 Exception Handling + Retry 로직
   - ✅ 데이터 수신 타임아웃 감지 및 재연결 (FR-025)

4. **금융/트레이딩 특화 규칙**:
   - ✅ `decimal.Decimal` 사용 (가격, 수량, 손익 계산)
   - ✅ `pytz` 사용 (KST/UTC 명시적 처리)
   - ✅ `logging` 모듈 사용 (`print()` 금지)
   - ✅ 주문 로그 필수 항목 포함 (타임스탬프, 종목코드, 가격, 수량)

5. **테스트 (Testing)**:
   - ✅ 모든 기능에 단위 테스트 작성
   - ✅ 외부 API는 mock 사용 (실제 주문 방지)

### 🚧 확인 필요 (Needs Clarification - Phase 0에서 해결)

- **NEEDS CLARIFICATION**: 키움증권 REST API의 정확한 Rate Limit 및 제한 사항
- **NEEDS CLARIFICATION**: 실시간 데이터 수신 방식 (WebSocket 지원 여부, Polling 주기)
- **NEEDS CLARIFICATION**: 전략 정의 최적 방식 (순수 Python vs YAML/DSL)

### ✅ Phase 0 Research 완료 후 재검토 (Post-Research Re-evaluation)

**모든 NEEDS CLARIFICATION 항목이 research.md에서 해결되었습니다:**

1. **키움증권 REST API Rate Limit** ✅ RESOLVED
   - **결정**: 15 requests/second 보수적 제한 적용 (Token Bucket Algorithm)
   - **근거**: 공식 문서 미공개, 유사 증권사(한국투자증권) 10-20 req/s 참고
   - **구현**: TokenBucketRateLimiter with asyncio.Semaphore

2. **실시간 데이터 수신 방식** ✅ RESOLVED
   - **결정**: REST API Polling (1초 간격, 종목별 staggered)
   - **근거**: 키움증권 REST API WebSocket 미지원 확인
   - **구현**: 50개 종목을 1초 윈도우에 분산하여 부하 분산

3. **전략 정의 방식** ✅ RESOLVED
   - **결정**: Hybrid 방식 (Python 로직 + YAML 설정)
   - **근거**: 2025년 업계 표준 (Wolfinch, Hummingbot 참고)
   - **분리**: Python (조건 로직) / YAML (파라미터, 종목, 자금배분)

### ✅ Phase 1 Design 완료 후 최종 검증 (Post-Design Final Verification)

**모든 Constitution 원칙이 설계 산출물에 반영되었음을 확인:**

1. **data-model.md 검증**:
   - ✅ 모든 Entity에 Pydantic BaseModel 사용
   - ✅ 금전 필드(price, balance, pl)는 Decimal 타입
   - ✅ 시간 필드는 datetime with KST timezone
   - ✅ 모든 필드에 타입 힌트 및 검증 규칙 명시

2. **contracts/ 검증**:
   - ✅ kiwoom-api.md: 모든 API 엔드포인트에 재시도 로직 및 에러 처리 명시
   - ✅ internal-interfaces.md: BaseStrategy, OrderExecutor 등 모든 인터페이스에 type hints 및 async 표기
   - ✅ events.md: 이벤트 페이로드 Pydantic 검증
   - ✅ configuration-schema.md: 설정 파일 Pydantic 스키마 검증

3. **quickstart.md 검증**:
   - ✅ 백테스트 모드 우선 안내 (안전성 우선)
   - ✅ 환경 변수로 민감 정보 관리 (API 키, 비밀번호)
   - ✅ 로깅 설정 가이드 (print() 사용 금지)

**최종 판정: 🎯 ALL GATES PASSED - Phase 2 (Task Generation) 진행 가능**

## Project Structure

### Documentation (this feature)

\`\`\`text
specs/001-kiwoom-auto-trading/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
\`\`\`

### Source Code (repository root)

\`\`\`text
src/
├── models/              # 도메인 모델 (Account, Order, Position, Stock, Strategy 등)
│   ├── __init__.py
│   ├── account.py       # Account, Balance DTO
│   ├── order.py         # Order, OrderStatus, OrderType
│   ├── position.py      # Position (보유 종목)
│   ├── stock.py         # Stock, MarketData, ChartData
│   └── strategy.py      # Strategy 추상 클래스 및 인터페이스
│
├── services/            # 비즈니스 로직 및 외부 서비스
│   ├── __init__.py
│   ├── kiwoom_api.py    # 키움증권 REST API 클라이언트 (aiohttp 기반)
│   ├── data_collector.py  # 실시간 데이터 수집 서비스
│   ├── strategy_engine.py # 전략 실행 엔진 (조건 평가, 주문 생성)
│   ├── order_executor.py  # 주문 실행 및 관리 (예수금 확인, 중복 방지)
│   ├── risk_manager.py    # 위험 관리 (손절, 일일 손실 한도)
│   ├── notifier.py        # 알림 전송 (Discord, Email)
│   └── health_check.py    # 시스템 헬스 체크
│
├── strategies/          # 구체적인 매매 전략 구현체
│   ├── __init__.py
│   ├── base.py          # BaseStrategy 추상 클래스
│   ├── golden_cross.py  # 골든크로스 전략 예시
│   └── custom/          # 사용자 정의 전략 디렉토리
│
├── utils/               # 유틸리티 (로깅, 시간, Decimal 헬퍼 등)
│   ├── __init__.py
│   ├── logger.py        # 로깅 설정
│   ├── time_utils.py    # 장 운영 시간 체크, timezone 처리
│   └── decimal_utils.py # Decimal 계산 헬퍼
│
├── cli/                 # CLI 인터페이스
│   ├── __init__.py
│   └── main.py          # CLI 진입점 (start, stop, status, backtest 등)
│
└── config/              # 설정 관리
    ├── __init__.py
    ├── settings.py      # Pydantic Settings (환경변수, 설정 파일 로드)
    └── strategies.yaml  # 전략 설정 파일 (종목, 자금 배분 등)

tests/
├── unit/                # 단위 테스트 (각 모듈별)
│   ├── test_models.py
│   ├── test_strategy_engine.py
│   ├── test_order_executor.py
│   └── test_risk_manager.py
│
├── integration/         # 통합 테스트 (전체 플로우)
│   ├── test_trading_flow.py
│   └── test_api_integration.py
│
└── fixtures/            # 테스트 데이터 및 mock
    ├── mock_api_responses.py
    └── test_strategies.py

data/                    # 런타임 데이터
├── orders.db            # SQLite 데이터베이스
├── logs/                # 로그 파일
└── backtest/            # 백테스팅 결과

config.yaml              # 시스템 설정 파일 (API 키, 계좌번호 등)
requirements.txt         # Python 의존성
README.md
\`\`\`

**Structure Decision**:

단일 프로젝트 구조(Single Project)를 선택했다. 이유는 다음과 같다:

1. **초기 버전은 서버 애플리케이션**으로 CLI 인터페이스만 제공하므로, frontend/backend 분리가 불필요하다.
2. **모듈화된 계층 구조**를 통해 관심사 분리(models/services/strategies/cli)를 명확히 한다.
3. **향후 확장성**: 추후 웹 대시보드가 필요하면 \`src/api/\` 디렉토리를 추가하고 FastAPI로 REST API를 노출할 수 있다.
4. **테스트 용이성**: 단위 테스트/통합 테스트를 명확히 분리하여 CI/CD 파이프라인에서 단계적 검증이 가능하다.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

*해당 사항 없음 (No Violations)* - 모든 Constitution 원칙이 설계에 반영되었으며, NEEDS CLARIFICATION 항목은 Phase 0 Research에서 해결 예정이다.
