# API Rate Limit 설정 가이드

## 🚨 중요: 각 증권사 API의 Rate Limit 제한사항

### 1. 키움증권 REST API
- **초당 제한**: 1회
- **분당 제한**: 60회
- **시간당 제한**: 3,600회
- **특징**:
  - 매우 엄격한 제한
  - 초과 시 일시적 차단 또는 계정 제재 가능
  - 실시간 시세는 WebSocket 활용 권장

### 2. 한국투자증권(KIS) API
- **초당 제한**: 20회
- **분당 제한**: 1,000회
- **일일 제한**: API 종류별 상이 (10만~100만회)
- **특징**:
  - 상대적으로 여유로운 제한
  - API 종류별로 다른 제한 적용

## 📋 Rate Limiter 구현 특징

### Token Bucket 알고리즘
```python
# 키움증권용 설정 예시
rate_limiter.register_api(
    api_key="kiwoom",
    requests_per_second=1.0,  # 초당 1회
    burst_size=2              # 짧은 버스트만 허용
)
```

### 다단계 제한
1. **초 단위**: 순간적인 과부하 방지
2. **분 단위**: 중기 트래픽 제어
3. **시간 단위**: 장기 할당량 관리

## 🔧 최적화 전략

### 1. 키움증권 API 사용 시
- **캐싱 적극 활용**: Redis로 자주 조회하는 데이터 캐싱
- **배치 처리**: 여러 요청을 모아서 한 번에 처리
- **우선순위 큐**: 중요한 요청 우선 처리
- **폴링 간격 조정**: 최소 1초 이상 간격 유지

### 2. WebSocket Proxy Server 활용
```python
# 중앙화된 폴링으로 개별 클라이언트 제한 회피
async def start_polling(symbol: str):
    await api_poller.start_polling(
        symbol=symbol,
        interval=1.0,  # 최소 1초 간격
        api_key="kiwoom"
    )
```

### 3. 지능형 재시도 로직
```python
# 지수 백오프로 재시도
async def retry_with_backoff():
    delay = 1.0
    max_delay = 60.0

    while not await rate_limiter.acquire():
        await asyncio.sleep(delay)
        delay = min(delay * 2, max_delay)
```

## 📊 모니터링 및 알림

### Rate Limit 상태 확인
```python
# 남은 용량 확인
capacity = rate_limiter.get_remaining_capacity()
print(f"키움 API 남은 용량: {capacity['apis']['kiwoom']}")

# 통계 조회
stats = rate_limiter.get_stats("kiwoom")
print(f"차단된 요청: {stats['blocked_requests']}")
```

### 경고 임계값 설정
- 용량 20% 미만: 경고 알림
- 용량 10% 미만: 긴급 조치 (비필수 요청 중단)
- 용량 소진: 자동 대기 모드

## ⚠️ 주의사항

1. **테스트 환경에서도 Rate Limit 준수**
   - 개발/테스트 시에도 실제 제한 적용
   - Mock API 사용 고려

2. **에러 처리**
   - 429 (Too Many Requests) 에러 적절히 처리
   - 자동 재시도 시 추가 지연 적용

3. **로그 기록**
   - 모든 API 호출 기록 보관
   - Rate Limit 위반 시도 추적

## 🚀 성능 최적화 팁

### 1. 데이터 집계
```python
# TimescaleDB의 Continuous Aggregates 활용
# 1분봉 데이터를 미리 계산하여 API 호출 감소
CREATE MATERIALIZED VIEW ohlcv_1min
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 minute', time) AS bucket,
       symbol,
       FIRST(price, time) AS open,
       MAX(price) AS high,
       MIN(price) AS low,
       LAST(price, time) AS close
FROM market_data
GROUP BY bucket, symbol;
```

### 2. 스마트 캐싱
```python
# Redis TTL 설정으로 자동 갱신
cache.set(f"price:{symbol}", price, ttl=5)  # 5초 캐시
```

### 3. 우선순위 기반 요청
```python
# 중요도에 따른 요청 순서 조정
priority_queue = asyncio.PriorityQueue()
await priority_queue.put((1, "critical_order"))  # 우선순위 1
await priority_queue.put((5, "market_data"))     # 우선순위 5
```

## 📈 실제 사용 예시

```python
# 키움증권 API 안전한 사용
async def safe_kiwoom_request(endpoint, params):
    # 1. Rate Limit 확인 및 대기
    if not await rate_limiter.wait_and_acquire("kiwoom", timeout=30):
        raise Exception("Rate limit timeout")

    # 2. 캐시 확인
    cached = cache.get(f"{endpoint}:{params}")
    if cached:
        return cached

    # 3. API 호출
    try:
        response = await kiwoom_api.request(endpoint, params)

        # 4. 캐시 저장
        cache.set(f"{endpoint}:{params}", response, ttl=10)

        return response
    except RateLimitError:
        # 5. 백오프 후 재시도
        await asyncio.sleep(60)
        return await safe_kiwoom_request(endpoint, params)
```

## 🔍 트러블슈팅

### 문제: "API 호출 한도 초과" 에러
**해결책**:
1. Rate Limiter 설정 확인
2. 불필요한 중복 요청 제거
3. 캐싱 TTL 증가
4. WebSocket 실시간 데이터 활용

### 문제: 데이터 지연
**해결책**:
1. 우선순위 큐 도입
2. 병렬 처리 최적화
3. 예측 가능한 데이터 사전 로드

### 문제: 피크 시간 성능 저하
**해결책**:
1. 오프피크 시간에 배치 작업 수행
2. 증분 업데이트 방식 채택
3. 로컬 데이터베이스 캐시 확대