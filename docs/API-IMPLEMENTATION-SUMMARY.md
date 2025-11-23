# 키움증권 REST API 구현 완료 보고서

**작성일**: 2025-11-23
**작업 범위**: T050-T059 (Phase 5: Real API Integration)

## 요약

실제 키움증권 REST API 명세 (`KIWOOM-REST-API.md`)를 기반으로 `KiwoomClient` 구현을 완전히 재작성하였습니다. 기존 구현은 일반적인 RESTful API 패턴을 사용했으나, 실제 키움 API는 고유한 구조를 가지고 있어 대부분의 엔드포인트와 필드명을 수정했습니다.

## 주요 변경 사항

### 1. API ID 매핑 시스템 구현 (tr_cd)

키움 API는 같은 엔드포인트를 여러 API가 공유하므로, `tr_cd` (거래코드) 필드로 구분합니다.

| 엔드포인트 | API ID | 설명 |
|-----------|--------|------|
| `/api/dostk/mrkcond` | `ka10006` | 주식시세요청 |
| `/api/dostk/chart` | `ka10081` | 주식일봉차트조회요청 |
| `/api/dostk/ordr` | `kt10000` | 주식 매수주문 |
| `/api/dostk/ordr` | `kt10001` | 주식 매도주문 |
| `/api/dostk/acnt` | `ka10075` | 미체결요청 |
| `/api/dostk/acnt` | `ka10076` | 체결요청 |
| `/api/dostk/acnt` | `kt00001` | 예수금상세현황요청 |
| `/api/dostk/acnt` | `kt00018` | 계좌평가잔고내역요청 |

### 2. 세부 변경 내역

#### T050: OAuth2 토큰 인증 ✅
```python
# 변경 전
payload = {"grant_type": "client_credentials", "client_id": api_key, "client_secret": api_secret}
token_response.access_token

# 변경 후
payload = {"grant_type": "client_credentials", "appkey": api_key, "secretkey": api_secret}
token_response.token
```

#### T052: 실시간 시세 조회 ✅
```python
# 변경 전
GET /market/price/{stock_code}
response: {stock_code, current_price, open_price, ...}

# 변경 후
POST /api/dostk/mrkcond
request: {tr_cd: "ka10006", stk_cd}
response: {cur_prc, open_pric, high_pric, low_pric, trde_qty}
```

#### T053: 일봉 데이터 조회 ✅
```python
# 변경 전
GET /market/chart/{stock_code}
response: {chart_data: [{timestamp, open_price, high_price, ...}]}

# 변경 후
POST /api/dostk/chart
request: {tr_cd: "ka10081", stk_cd, base_dt}
response: {stk_dt_pole_chart_qry: [{dt, open_pric, high_pric, low_pric, cur_prc, trde_qty}]}
```

#### T054/T055: 매수/매도 주문 ✅
```python
# 변경 전
POST /order/buy (매수)
POST /order/sell (매도)
request: {account_number, stock_code, quantity, price_type}

# 변경 후
POST /api/dostk/ordr (통합)
request: {
    tr_cd: "kt10000" (매수) | "kt10001" (매도),
    acnt_no,
    stk_cd,
    ord_qty,
    ord_uv,  # 주문단가 (시장가=0)
    trde_tp  # 매매구분 (0=지정가, 3=시장가)
}
response: {ord_no, return_code}
```

#### T056: 주문 상태 조회 ✅
```python
# 변경 전
GET /order/status/{order_id}

# 변경 후
POST /api/dostk/acnt
request: {tr_cd: "ka10075", acnt_no, stk_cd?}
response: {oso: [{ord_no, ord_qty, cntr_qty, oso_qty}]}
# 미체결 목록에서 ord_no로 검색
```

#### T057: 계좌 잔고 조회 ✅
```python
# 변경 전
GET /account/balance/{account_number}
response: {cash_balance, total_asset_value, ...}

# 변경 후
POST /api/dostk/acnt
request: {tr_cd: "kt00001", acnt_no}
response: {entr, ord_alowa, wthd_alowa}
# entr: 예수금, ord_alowa: 주문가능현금, wthd_alowa: 인출가능금액
```

#### T058: 보유 종목 조회 ✅
```python
# 변경 전
GET /account/positions/{account_number}
response: {positions: [{stock_code, quantity, average_buy_price, ...}]}

# 변경 후
POST /api/dostk/acnt
request: {tr_cd: "kt00018", acnt_no, qry_tp: "2"}
response: {acnt_evlt_remn_indv_tot: [{stk_cd, stk_nm, rmnd_qty, evlt_amt, evltv_prft, pft_rt}]}
```

#### T059: 에러 처리 ✅
```python
# 추가된 키움 전용 에러 코드 처리
error_code = "1501"  # API ID Null or Invalid
error_code = "1513"  # Authorization fail → 토큰 재발급 트리거
error_code = "8103"  # 토큰 인증 실패 → 토큰 재발급 트리거
error_code = "1687"  # Rate Limit (재귀 호출 제한)

# 한글 에러 메시지 감지
if "예수금 부족" in error_message:
    raise InsufficientBalanceError()
if "종목코드" in error_message:
    raise InvalidStockCodeError()
```

### 3. 추가 구현

#### 체결 내역 조회 (ka10076) ✅
```python
async def get_filled_orders(self) -> list[Order]:
    """당일 체결된 주문 내역 조회."""
    payload = {
        "tr_cd": "ka10076",
        "acnt_no": self.account_number
    }
    # response: {cntr: [{ord_no, stk_cd, ord_qty, cntr_qty, cntr_prc}]}
```

## 제한 사항

### 1. 주문 타입/가격 타입 복원 불가
키움 API의 `ka10075` (미체결요청), `ka10076` (체결요청)은 주문 타입(`OrderType.BUY/SELL`)과 가격 타입(`PriceType.LIMIT/MARKET`) 정보를 응답에 포함하지 않습니다.

**해결 방법**:
- `submit_order()` 응답을 저장하여 활용
- `OrderRepository`를 사용하여 주문 정보 관리
- 또는 별도의 매수/매도 구분 API 호출

```python
# get_order_status() 사용 시 주의사항
order = await client.get_order_status("ORD-001")
# order.order_type은 기본값(OrderType.BUY) 사용
# order.price_type은 기본값(PriceType.LIMIT) 사용
# 정확한 정보가 필요하면 submit_order() 응답을 저장하세요!
```

### 2. 계좌 정보 제한
`kt00001` (예수금상세현황요청)은 총 손익, 일일 손익을 직접 제공하지 않습니다. 필요 시 별도 계산 필요.

## 테스트

### 기본 테스트 (작성 완료)
```bash
pytest tests/api/test_kiwoom_client.py -v
# 4/4 테스트 통과
```

### Contract Test (TODO)
실제 키움 API와 통신하여 응답 형식을 검증하는 테스트가 필요합니다 (Phase 5.2, T060-T064).

## 파일 변경 목록

- ✅ `src/api/kiwoom_client.py` - 완전 재작성
- ✅ `tests/api/test_kiwoom_client.py` - 신규 작성
- ✅ `docs/KIWOOM-REST-API.md` - 이미 제공됨
- ✅ `docs/API-IMPLEMENTATION-SUMMARY.md` - 본 문서

## 다음 단계

1. **Contract Test 작성** (T060-T064)
   - 실제 키움 API Mock 서버 구축 또는
   - 키움 테스트 환경에서 실제 API 호출 테스트

2. **OrderExecutor 업데이트**
   - 새로운 API 구조에 맞게 주문 실행 로직 수정
   - OrderRepository 연동하여 주문 정보 저장

3. **통합 테스트**
   - Simulator → KiwoomClient 전환 테스트
   - 전체 플로우 검증

## 주의사항

⚠️ **실제 API 키 사용 전 필독**:
1. 모든 엔드포인트가 POST 메서드 사용
2. `tr_cd` 필드는 필수 (API 구분)
3. 필드명은 키움 API 명세와 정확히 일치해야 함
4. 에러 코드 `1513`, `8103` 발생 시 자동으로 토큰 재발급 시도
5. Rate Limit: 초당 최대 15 req (RateLimiter 자동 처리)

## 검증 완료 항목

- ✅ Python 컴파일 성공
- ✅ Ruff 린트 통과
- ✅ 기본 테스트 4개 통과
- ✅ 모든 API 메서드에 tr_cd 추가
- ✅ 모든 필드명 키움 API 명세와 일치
- ✅ 에러 처리 강화 (키움 전용 에러 코드)
- ✅ 문서화 완료

---

**작업자**: Claude
**검토자**: (검토 필요)
**승인자**: (승인 필요)
