# Project Constitution

이 문서는 프로젝트의 모든 코드 작성, 리팩토링, 문서화 작업 시 반드시 준수해야 할 **불변의 원칙**을 정의합니다.

## 1. 기본 원칙 (Core Principles)
- **안정성 우선 (Safety First):** 속도보다 안정성이 중요하다. 모든 금융 거래 로직은 보수적으로 작성되어야 한다.
- **명시적 코드 (Explicit is better than implicit):** 마법 같은 코드보다는, 누가 읽어도 흐름을 알 수 있는 명시적인 코드를 작성한다.
- **방어적 프로그래밍 (Defensive Programming):** 외부 API(키움증권)는 언제든 실패할 수 있다고 가정한다. 모든 네트워크 요청은 실패에 대비한 로직(Retry, Exception Handling)을 포함해야 한다.

## 2. 기술 스택 및 스타일 (Tech Stack & Style)
- **Language:** Python 3.10+
- **Type Hinting:** 모든 함수와 메서드에는 `typing` 모듈을 사용하여 인자(Arguments)와 반환값(Return Type)의 타입을 명시한다.
- **Docstring:** 모든 클래스와 함수는 Google Style의 Docstring을 포함해야 한다.
- **Naming Convention:**
  - 변수/함수: `snake_case`
  - 클래스: `PascalCase`
  - 상수: `UPPER_CASE`
- **Language:** 주석(Comments)과 문서(Docstrings)는 **한국어(Korean)**로 작성한다.

## 3. 아키텍처 원칙 (Architecture Guidelines)
- **관심사의 분리 (Separation of Concerns):**
  - 비즈니스 로직(전략)과 인프라 로직(API 통신)을 엄격히 분리한다.
  - API 응답 데이터는 즉시 도메인 객체(Domain Object)나 DTO로 변환하여 사용한다. (Raw Dictionary 사용 지양)
- **의존성 주입 (Dependency Injection):** 테스트 용이성을 위해 외부 의존성(API Client 등)은 내부에서 생성하지 않고 외부에서 주입받는다.

## 4. 금융/트레이딩 특화 규칙 (Trading Specific Rules)
- **부동소수점 처리:** 가격, 수량, 수익률 등 금전과 관련된 계산은 `float` 대신 `decimal.Decimal`을 사용하여 부동소수점 오차를 방지한다.
- **시간 처리:** 모든 시간 데이터는 `pytz`를 사용하여 명시적으로 Timezone(KST, UTC)을 처리한다.
- **로그 남기기 (Logging):**
  - `print()` 사용을 금지한다. 반드시 `logging` 모듈을 사용한다.
  - 주문 실행(Buy/Sell)과 관련된 모든 로그는 `INFO` 레벨 이상으로 기록하며, 타임스탬프, 종목코드, 가격, 수량을 반드시 포함한다.

## 5. 테스트 (Testing) - **수정됨**
- **Fakes over Mocks:** 외부 API 의존성 테스트 시 단순 Mocking(`unittest.mock`)보다는 상태를 가진 **Fake Object(Simulator)** 사용을 우선한다.
- **Contract Testing:** 외부 API와 Fake Object의 동작이 일치하는지 검증하는 계약 테스트(Contract Test)를 유지한다.
- **Integration First:** 단위 테스트보다 주요 컴포넌트(전략 <-> 실행기 <-> API)가 유기적으로 연결되는지 확인하는 통합 테스트에 비중을 둔다.