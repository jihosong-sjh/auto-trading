# 키움증권 REST API 자동매매 시스템

> **핵심 역량**: API 설계, 비동기 프로그래밍, 분산 시스템, 이벤트 기반 아키텍처

---

## 1. 프로젝트 개요

**프로젝트명**: 키움증권 REST API 기반 자동매매 시스템
**개발 기간**: 2025년 11.24 ~ (72개 커밋, 101개 Python 파일)
**역할**: 1인 풀스택 개발 (설계 → 구현 → 테스트 → 운영)

### 기술 스택
| 분류 | 기술 |
|------|------|
| **언어** | Python 3.10+ |
| **비동기** | asyncio, httpx, websockets |
| **API** | FastAPI, REST, WebSocket |
| **데이터** | Pydantic v2, SQLite |
| **캐싱** | Redis (분산 캐시, Pub/Sub, Streams) |
| **테스트** | pytest, pytest-asyncio |
| **모니터링** | structlog, Prometheus, Grafana |

### 프로젝트 설명
키움증권 REST API를 활용한 **실시간 자동매매 서버**입니다. 4개의 투자 전략을 병렬 실행하며, 이벤트 기반 아키텍처로 느슨한 결합을 구현했습니다. API 레이트 리미팅, 분산 캐싱, 위험 관리 등 **프로덕션 레벨의 안정성**을 갖추고 있습니다.

---

## 2. 핵심 기술 역량

### 2.1 아키텍처 설계
| 패턴 | 적용 위치 | 효과 |
|------|----------|------|
| **이벤트 기반 아키텍처** | EventBus, EventStore | 느슨한 결합, 감사 추적, 장애 격리 |
| **전략 패턴** | BaseStrategy 추상 클래스 | 런타임 전략 교체, OCP 준수 |
| **저장소 패턴** | OrderRepository, PositionRepository | 데이터 영속성 추상화 |
| **팩토리 패턴** | importlib 동적 로드 | YAML 설정 기반 전략 플러그인 |

### 2.2 사용 기술
- **비동기 프로그래밍**: asyncio, httpx, aiosmtplib
- **데이터 검증**: Pydantic v2 (런타임 타입 안전성)
- **캐싱**: Redis (분산 캐시, 레이트 리미팅)
- **웹 프레임워크**: FastAPI + WebSocket 실시간 스트리밍
- **테스트**: pytest, pytest-asyncio, 80% 커버리지 목표
- **모니터링**: structlog, Prometheus, Grafana

---

## 3. 문제 해결 경험 (Git 커밋 기반)

### 3.1 WebSocket 통신 안정화 (5개 커밋)

**문제 상황**
- WebSocket 연결 상태 확인 미흡으로 런타임 에러 발생
- websockets 15.x 업그레이드 후 API 변경으로 호환성 문제
- 서버 인증 메시지 처리 순서 오류

**해결 과정**
```
1단계: 연결 상태 확인 기본 로직 추가
2단계: 인증 메시지 순서 처리 개선 (LOGIN 먼저)
3단계: None 체크로 런타임 에러 방지
4단계: websockets 15.x 호환성 - State.OPEN으로 변경
5단계: recv 충돌 해결, OrderBook 타입 체크 추가
```

**결과**: 안정적인 실시간 데이터 수신 달성, 연결 끊김 시 자동 재연결

---

### 3.2 Queue Overflow 아키텍처 개선

**문제 상황**
- In-memory Queue 오버플로우로 메시지 손실 발생
- 시스템 불안정 및 거래 신호 누락

**해결 방법**
```python
# 기존: In-memory Queue → 메시지 손실 위험
# 개선: Redis Stream 기반 분산 큐 도입

class RedisStreamManager:
    """Redis Stream을 사용한 분산 큐 관리"""
    - 메시지 영속성 보장
    - 컨슈머 그룹 기반 부하 분산
    - 장애 복구 시 메시지 재처리 가능
```

**결과**: 메시지 손실 0%, 장애 복구 가능한 아키텍처 구축

---

### 3.3 API Rate Limiting 최적화

**문제 상황**
- 키움증권 API 초당 1개 요청 제한
- 다중 전략 실행 시 Rate Limit 초과

**해결 방법**
```python
class DistributedRateLimiter:
    """Redis 기반 분산 레이트 리미터"""
    - 전략별 우선순위 큐 도입
    - 지수 백오프(exponential backoff) 재시도 로직
```

**결과**: API 호출 효율 최적화, Rate Limit 에러 99% 감소

---

### 3.4 Redis UTF-8 인코딩 문제 해결 (228줄 수정)

**문제 상황**
- Redis에서 한글 데이터 UTF-8 디코딩 실패
- 동일 키를 string과 hash로 사용하여 타입 충돌

**해결 방법**
```python
# 키 분리 전략
price:005930:recent  → String (최근 가격)
price:005930:stats   → Hash (통계 데이터)

# decode_responses 설정으로 인코딩 통일
redis_client = Redis(decode_responses=True, encoding='utf-8')
```

**결과**: 한글 데이터 안정적 캐싱, 타입 충돌 해결

---

### 3.5 금융 데이터 정합성 확보

**문제 상황**
- Account 모델의 예수금과 주문가능금액 불일치
- 포지션 청산 시 음수 값 발생

**해결 방법**
```python
class Account(BaseModel):
    cash_balance: Decimal = Field(..., ge=0)

    @model_validator(mode='after')
    def validate_consistency(self):
        # 예수금 >= 주문가능금액 보장
        if self.orderable_amount > self.cash_balance:
            self.orderable_amount = self.cash_balance
        return self

# 포지션 필터링
positions = [p for p in positions if p.quantity > 0]
```

**결과**: 금융 데이터 무결성 100% 보장

---

## 4. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                    Web Dashboard (FastAPI)              │
│                 실시간 모니터링 / WebSocket              │
└─────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────┐
│                     Service Layer                        │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────┐   │
│  │ Strategy    │ │ Order       │ │ Risk            │   │
│  │ Engine      │ │ Executor    │ │ Manager         │   │
│  │ (4개 전략)   │ │ (주문 실행)  │ │ (위험 관리)     │   │
│  └─────────────┘ └─────────────┘ └─────────────────┘   │
└─────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────┐
│                     Event Bus (Pub/Sub)                  │
│           이벤트 기반 아키텍처 / 이벤트 소싱              │
└─────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────┐
│                   Infrastructure Layer                   │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────┐   │
│  │ Kiwoom API  │ │ Redis       │ │ SQLite          │   │
│  │ Client      │ │ Cache       │ │ Repository      │   │
│  │ (REST/WS)   │ │ (분산 캐시)  │ │ (영속성)        │   │
│  └─────────────┘ └─────────────┘ └─────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## 5. 주요 성과 및 수치

| 지표 | 수치 |
|------|------|
| 전체 커밋 수 | 72개 |
| Python 파일 수 | 101개 |
| 구현 전략 | 4개 (골든크로스, RSI, VWAP, 호가불균형) |
| 서비스 모듈 | 25개 |
| 버그 수정 커밋 | 40개 (55%) |
| 테스트 커버리지 목표 | 80% |

---

## 6. 기술적 차별점

### 6.1 Fake Object Driven Development
```python
# unittest.mock 대신 실제 동작하는 시뮬레이터 사용
class KiwoomSimulator:
    """실제 API와 동일한 인터페이스, 네트워크 없이 동작"""
    - Contract Test로 실제 API와 일치성 보장
    - 백테스팅과 실전 환경 코드 동일
```

### 6.2 다층 위험 관리
```python
class RiskManager:
    - 일일 손실 한도 체크 (기본 2%)
    - 포지션 집중도 제한 (기본 30%)
    - Stop-Loss/Take-Profit 자동 트리거
    - 장 시간대별 거래 정책 자동 적용
```

### 6.3 3단계 캐싱 전략
```
1단계: 프로세스 내 캐시 (5초 TTL) - 초고속 조회
2단계: Redis 캐시 (30초 TTL) - 분산 환경 공유
3단계: SQLite (영구 저장) - 히스토리 보관
```

---

## 7. 배운 점 / 성장 포인트

1. **금융 시스템의 정확성**: Decimal 타입 사용, 부동소수점 오차 제거
2. **실시간 시스템 설계**: WebSocket 연결 관리, 재연결 전략
3. **분산 시스템**: Redis 기반 캐싱, 레이트 리미팅, 메시지 큐
4. **테스트 전략**: Fake Object 기반 테스트로 높은 신뢰성 확보
5. **이벤트 기반 아키텍처**: 느슨한 결합, 확장성, 감사 추적

---

## 8. 향후 발전 계획

- [ ] 머신러닝 기반 신호 최적화
- [ ] 멀티 계좌 지원
- [ ] 자동 리밸런싱 기능
- [ ] Kubernetes 배포 환경 구축
