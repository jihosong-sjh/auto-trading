# 키움증권 REST API 계약 명세

**Feature Branch**: `001-kiwoom-auto-trading`
**Created**: 2025-11-22
**Status**: Draft
**Related**: [spec.md](../spec.md) | [data-model.md](../data-model.md)

## 개요

본 문서는 키움증권 REST API와의 통합을 위한 계약 명세를 정의한다. 모든 API 엔드포인트, 요청/응답 형식, 에러 코드, Rate Limiting 정보를 포함한다.

## 목차

1. [인증 (Authentication)](#인증-authentication)
2. [실시간 시세 데이터](#실시간-시세-데이터)
3. [과거 차트 데이터](#과거-차트-데이터)
4. [주문 실행](#주문-실행)
5. [주문 상태 조회](#주문-상태-조회)
6. [계좌 잔고 조회](#계좌-잔고-조회)
7. [보유 종목 조회](#보유-종목-조회)
8. [에러 코드 및 처리](#에러-코드-및-처리)
9. [Rate Limiting](#rate-limiting)

---

## 공통 사항

### Base URL

```
https://openapi.kiwoom.com/api/v1
```

### 공통 헤더

모든 API 요청에는 다음 헤더가 포함되어야 한다:

```http
Content-Type: application/json
Authorization: Bearer {access_token}
tr_cd: {거래코드}
custtype: {고객구분}
```

### 공통 응답 형식

```typescript
{
  "rt_cd": "0",           // 응답 코드 (0: 성공, 그 외: 에러)
  "msg_cd": "OPSP0000",   // 메시지 코드
  "msg1": "정상처리 되었습니다.",  // 메시지 내용
  "output": {...}         // 실제 응답 데이터
}
```

---

## 인증 (Authentication)

### 1. 액세스 토큰 발급

**Endpoint**: `POST /oauth2/token`

**설명**: API Key와 Secret을 사용하여 액세스 토큰을 발급받는다.

**Request**:

```http
POST /oauth2/token HTTP/1.1
Host: openapi.kiwoom.com
Content-Type: application/json

{
  "grant_type": "client_credentials",
  "appkey": "your_app_key",
  "appsecret": "your_app_secret"
}
```

**Response**:

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 86400,
  "scope": "read write"
}
```

**응답 필드**:

| 필드명 | 타입 | 설명 |
|-------|------|------|
| `access_token` | string | 액세스 토큰 (JWT 형식) |
| `token_type` | string | 토큰 타입 (항상 "Bearer") |
| `expires_in` | integer | 토큰 유효 시간 (초 단위, 기본 24시간) |
| `scope` | string | 토큰 권한 범위 |

**에러 응답**:

```json
{
  "error": "invalid_client",
  "error_description": "Invalid app key or secret"
}
```

**사용 예시 (Python)**:

```python
import httpx
from typing import Optional

class KiwoomAuthClient:
    """Kiwoom API authentication client."""

    def __init__(self, app_key: str, app_secret: str):
        self.app_key = app_key
        self.app_secret = app_secret
        self.base_url = "https://openapi.kiwoom.com/api/v1"
        self.access_token: Optional[str] = None

    async def get_access_token(self) -> str:
        """Get access token from Kiwoom API.

        Returns:
            Access token string.

        Raises:
            httpx.HTTPStatusError: If authentication fails.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/oauth2/token",
                json={
                    "grant_type": "client_credentials",
                    "appkey": self.app_key,
                    "appsecret": self.app_secret
                }
            )
            response.raise_for_status()
            data = response.json()
            self.access_token = data["access_token"]
            return self.access_token
```

---

## 실시간 시세 데이터

### 2. 실시간 체결가 조회

**Endpoint**: `GET /market/price`

**설명**: 특정 종목의 실시간 체결가 정보를 조회한다.

**Request**:

```http
GET /market/price?stock_code=005930 HTTP/1.1
Host: openapi.kiwoom.com
Authorization: Bearer {access_token}
tr_cd: FHKST01010100
```

**Query Parameters**:

| 파라미터 | 타입 | 필수 | 설명 | 예시 |
|---------|------|-----|------|------|
| `stock_code` | string | Yes | 종목코드 (6자리) | "005930" |

**Response**:

```json
{
  "rt_cd": "0",
  "msg_cd": "OPSP0000",
  "msg1": "정상처리 되었습니다.",
  "output": {
    "stock_code": "005930",
    "stock_name": "삼성전자",
    "current_price": "72000",
    "change": "500",
    "change_rate": "0.70",
    "volume": "15234567",
    "open_price": "71500",
    "high_price": "72500",
    "low_price": "71000",
    "timestamp": "2025-11-22T14:30:15+09:00"
  }
}
```

**응답 필드**:

| 필드명 | 타입 | 설명 |
|-------|------|------|
| `stock_code` | string | 종목코드 |
| `stock_name` | string | 종목명 |
| `current_price` | string | 현재가 (숫자를 문자열로 반환) |
| `change` | string | 전일 대비 (양수: 상승, 음수: 하락) |
| `change_rate` | string | 등락률 (%) |
| `volume` | string | 누적 거래량 |
| `open_price` | string | 시가 |
| `high_price` | string | 고가 |
| `low_price` | string | 저가 |
| `timestamp` | string | 체결 시간 (ISO 8601 형식, KST) |

**사용 예시 (Python)**:

```python
from decimal import Decimal
from datetime import datetime
from typing import Optional

class KiwoomMarketDataClient:
    """Kiwoom market data API client."""

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.base_url = "https://openapi.kiwoom.com/api/v1"

    async def get_current_price(self, stock_code: str) -> dict:
        """Get current price for a stock.

        Args:
            stock_code: 6-digit stock code.

        Returns:
            Stock price data as dict.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/market/price",
                params={"stock_code": stock_code},
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "tr_cd": "FHKST01010100"
                }
            )
            response.raise_for_status()
            data = response.json()

            if data["rt_cd"] != "0":
                raise ValueError(f"API error: {data['msg1']}")

            output = data["output"]

            # Convert string values to appropriate types
            return {
                "stock_code": output["stock_code"],
                "stock_name": output["stock_name"],
                "current_price": Decimal(output["current_price"]),
                "volume": int(output["volume"]),
                "open_price": Decimal(output["open_price"]),
                "high_price": Decimal(output["high_price"]),
                "low_price": Decimal(output["low_price"]),
                "timestamp": datetime.fromisoformat(output["timestamp"])
            }
```

### 3. 실시간 호가 조회

**Endpoint**: `GET /market/orderbook`

**설명**: 특정 종목의 실시간 호가 정보를 조회한다.

**Request**:

```http
GET /market/orderbook?stock_code=005930 HTTP/1.1
Host: openapi.kiwoom.com
Authorization: Bearer {access_token}
tr_cd: FHKST01010200
```

**Response**:

```json
{
  "rt_cd": "0",
  "msg_cd": "OPSP0000",
  "msg1": "정상처리 되었습니다.",
  "output": {
    "stock_code": "005930",
    "timestamp": "2025-11-22T14:30:15+09:00",
    "asks": [
      {"price": "72100", "quantity": "1500"},
      {"price": "72200", "quantity": "2300"},
      {"price": "72300", "quantity": "1800"}
    ],
    "bids": [
      {"price": "72000", "quantity": "2100"},
      {"price": "71900", "quantity": "1900"},
      {"price": "71800", "quantity": "2500"}
    ]
  }
}
```

---

## 과거 차트 데이터

### 4. 일봉 데이터 조회

**Endpoint**: `GET /market/chart/daily`

**설명**: 특정 종목의 과거 일봉 데이터를 조회한다.

**Request**:

```http
GET /market/chart/daily?stock_code=005930&start_date=20251101&end_date=20251122 HTTP/1.1
Host: openapi.kiwoom.com
Authorization: Bearer {access_token}
tr_cd: FHKST03010100
```

**Query Parameters**:

| 파라미터 | 타입 | 필수 | 설명 | 예시 |
|---------|------|-----|------|------|
| `stock_code` | string | Yes | 종목코드 (6자리) | "005930" |
| `start_date` | string | Yes | 시작일 (YYYYMMDD) | "20251101" |
| `end_date` | string | Yes | 종료일 (YYYYMMDD) | "20251122" |
| `limit` | integer | No | 최대 조회 건수 (기본 100, 최대 500) | 100 |

**Response**:

```json
{
  "rt_cd": "0",
  "msg_cd": "OPSP0000",
  "msg1": "정상처리 되었습니다.",
  "output": {
    "stock_code": "005930",
    "data": [
      {
        "date": "20251122",
        "open": "71500",
        "high": "72500",
        "low": "71000",
        "close": "72000",
        "volume": "15234567"
      },
      {
        "date": "20251121",
        "open": "70000",
        "high": "71500",
        "low": "69800",
        "close": "71500",
        "volume": "14523456"
      }
    ]
  }
}
```

**응답 필드**:

| 필드명 | 타입 | 설명 |
|-------|------|------|
| `date` | string | 날짜 (YYYYMMDD) |
| `open` | string | 시가 |
| `high` | string | 고가 |
| `low` | string | 저가 |
| `close` | string | 종가 |
| `volume` | string | 거래량 |

**사용 예시 (Python)**:

```python
from datetime import datetime, timedelta
from typing import List

async def get_daily_chart(
    client: KiwoomMarketDataClient,
    stock_code: str,
    days: int = 20
) -> List[dict]:
    """Get daily chart data for the last N days.

    Args:
        client: Kiwoom API client.
        stock_code: 6-digit stock code.
        days: Number of days to retrieve (default 20).

    Returns:
        List of daily candle data.
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    async with httpx.AsyncClient() as http_client:
        response = await http_client.get(
            f"{client.base_url}/market/chart/daily",
            params={
                "stock_code": stock_code,
                "start_date": start_date.strftime("%Y%m%d"),
                "end_date": end_date.strftime("%Y%m%d")
            },
            headers={
                "Authorization": f"Bearer {client.access_token}",
                "tr_cd": "FHKST03010100"
            }
        )
        response.raise_for_status()
        data = response.json()

        if data["rt_cd"] != "0":
            raise ValueError(f"API error: {data['msg1']}")

        return [
            {
                "date": datetime.strptime(item["date"], "%Y%m%d"),
                "open": Decimal(item["open"]),
                "high": Decimal(item["high"]),
                "low": Decimal(item["low"]),
                "close": Decimal(item["close"]),
                "volume": int(item["volume"])
            }
            for item in data["output"]["data"]
        ]
```

### 5. 분봉 데이터 조회

**Endpoint**: `GET /market/chart/minute`

**설명**: 특정 종목의 과거 분봉 데이터를 조회한다.

**Request**:

```http
GET /market/chart/minute?stock_code=005930&interval=5&count=100 HTTP/1.1
Host: openapi.kiwoom.com
Authorization: Bearer {access_token}
tr_cd: FHKST03010200
```

**Query Parameters**:

| 파라미터 | 타입 | 필수 | 설명 | 예시 |
|---------|------|-----|------|------|
| `stock_code` | string | Yes | 종목코드 (6자리) | "005930" |
| `interval` | integer | Yes | 분봉 주기 (1, 5, 10, 30, 60) | 5 |
| `count` | integer | No | 조회 개수 (기본 100, 최대 500) | 100 |

**Response**:

```json
{
  "rt_cd": "0",
  "msg_cd": "OPSP0000",
  "msg1": "정상처리 되었습니다.",
  "output": {
    "stock_code": "005930",
    "interval": 5,
    "data": [
      {
        "timestamp": "2025-11-22T14:30:00+09:00",
        "open": "71800",
        "high": "72000",
        "low": "71750",
        "close": "71950",
        "volume": "123456"
      }
    ]
  }
}
```

---

## 주문 실행

### 6. 매수 주문

**Endpoint**: `POST /order/buy`

**설명**: 주식 매수 주문을 실행한다.

**Request**:

```http
POST /order/buy HTTP/1.1
Host: openapi.kiwoom.com
Authorization: Bearer {access_token}
Content-Type: application/json
tr_cd: TTTC0802U

{
  "account_number": "12345678",
  "stock_code": "005930",
  "price_type": "LIMIT",
  "price": "72000",
  "quantity": 100
}
```

**Request Body**:

| 필드명 | 타입 | 필수 | 설명 | 예시 |
|-------|------|-----|------|------|
| `account_number` | string | Yes | 계좌번호 (8자리) | "12345678" |
| `stock_code` | string | Yes | 종목코드 (6자리) | "005930" |
| `price_type` | string | Yes | 가격 유형 (MARKET, LIMIT) | "LIMIT" |
| `price` | string | Conditional | 주문가격 (LIMIT 시 필수) | "72000" |
| `quantity` | integer | Yes | 주문 수량 | 100 |

**Response (성공)**:

```json
{
  "rt_cd": "0",
  "msg_cd": "OPSP0000",
  "msg1": "정상처리 되었습니다.",
  "output": {
    "order_id": "2025112212345678",
    "account_number": "12345678",
    "stock_code": "005930",
    "order_type": "BUY",
    "price_type": "LIMIT",
    "price": "72000",
    "quantity": 100,
    "status": "SUBMITTED",
    "timestamp": "2025-11-22T14:30:15+09:00"
  }
}
```

**Response (실패)**:

```json
{
  "rt_cd": "1",
  "msg_cd": "OPSP0001",
  "msg1": "예수금이 부족합니다.",
  "output": null
}
```

**응답 필드**:

| 필드명 | 타입 | 설명 |
|-------|------|------|
| `order_id` | string | 주문번호 (API에서 발급) |
| `account_number` | string | 계좌번호 |
| `stock_code` | string | 종목코드 |
| `order_type` | string | 주문 유형 (BUY/SELL) |
| `price_type` | string | 가격 유형 (MARKET/LIMIT) |
| `price` | string | 주문 가격 |
| `quantity` | integer | 주문 수량 |
| `status` | string | 주문 상태 (SUBMITTED) |
| `timestamp` | string | 주문 접수 시간 (ISO 8601) |

**사용 예시 (Python)**:

```python
from pydantic import BaseModel
from typing import Optional

class OrderRequest(BaseModel):
    """Order request model."""
    account_number: str
    stock_code: str
    price_type: str  # "MARKET" or "LIMIT"
    price: Optional[str] = None
    quantity: int

class KiwoomOrderClient:
    """Kiwoom order API client."""

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.base_url = "https://openapi.kiwoom.com/api/v1"

    async def place_buy_order(
        self,
        request: OrderRequest
    ) -> dict:
        """Place a buy order.

        Args:
            request: Order request details.

        Returns:
            Order response data.

        Raises:
            ValueError: If order validation fails.
            httpx.HTTPStatusError: If API call fails.
        """
        # Validate LIMIT order has price
        if request.price_type == "LIMIT" and not request.price:
            raise ValueError("LIMIT orders must have a price")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/order/buy",
                json=request.model_dump(exclude_none=True),
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                    "tr_cd": "TTTC0802U"
                }
            )
            response.raise_for_status()
            data = response.json()

            if data["rt_cd"] != "0":
                raise ValueError(f"Order failed: {data['msg1']}")

            return data["output"]
```

### 7. 매도 주문

**Endpoint**: `POST /order/sell`

**설명**: 주식 매도 주문을 실행한다.

**Request**:

```http
POST /order/sell HTTP/1.1
Host: openapi.kiwoom.com
Authorization: Bearer {access_token}
Content-Type: application/json
tr_cd: TTTC0801U

{
  "account_number": "12345678",
  "stock_code": "005930",
  "price_type": "MARKET",
  "quantity": 100
}
```

**Request/Response**: 매수 주문과 동일한 형식.

### 8. 주문 취소

**Endpoint**: `POST /order/cancel`

**설명**: 미체결 주문을 취소한다.

**Request**:

```http
POST /order/cancel HTTP/1.1
Host: openapi.kiwoom.com
Authorization: Bearer {access_token}
Content-Type: application/json
tr_cd: TTTC0803U

{
  "account_number": "12345678",
  "order_id": "2025112212345678"
}
```

**Response**:

```json
{
  "rt_cd": "0",
  "msg_cd": "OPSP0000",
  "msg1": "주문이 취소되었습니다.",
  "output": {
    "order_id": "2025112212345678",
    "status": "CANCELLED",
    "timestamp": "2025-11-22T14:35:00+09:00"
  }
}
```

---

## 주문 상태 조회

### 9. 주문 내역 조회

**Endpoint**: `GET /order/status`

**설명**: 특정 주문의 상태를 조회한다.

**Request**:

```http
GET /order/status?account_number=12345678&order_id=2025112212345678 HTTP/1.1
Host: openapi.kiwoom.com
Authorization: Bearer {access_token}
tr_cd: TTTC8001R
```

**Query Parameters**:

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|-----|------|
| `account_number` | string | Yes | 계좌번호 (8자리) |
| `order_id` | string | Yes | 주문번호 |

**Response**:

```json
{
  "rt_cd": "0",
  "msg_cd": "OPSP0000",
  "msg1": "정상처리 되었습니다.",
  "output": {
    "order_id": "2025112212345678",
    "account_number": "12345678",
    "stock_code": "005930",
    "stock_name": "삼성전자",
    "order_type": "BUY",
    "price_type": "LIMIT",
    "order_price": "72000",
    "order_quantity": 100,
    "filled_quantity": 100,
    "filled_price": "72000",
    "status": "FILLED",
    "order_time": "2025-11-22T14:30:15+09:00",
    "filled_time": "2025-11-22T14:30:45+09:00"
  }
}
```

**응답 필드**:

| 필드명 | 타입 | 설명 |
|-------|------|------|
| `order_id` | string | 주문번호 |
| `status` | string | 주문 상태 (SUBMITTED, PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED) |
| `order_quantity` | integer | 주문 수량 |
| `filled_quantity` | integer | 체결 수량 |
| `filled_price` | string | 평균 체결가 |
| `order_time` | string | 주문 시간 |
| `filled_time` | string | 체결 완료 시간 (완전 체결 시) |

### 10. 당일 주문 내역 조회

**Endpoint**: `GET /order/list`

**설명**: 당일 모든 주문 내역을 조회한다.

**Request**:

```http
GET /order/list?account_number=12345678&date=20251122 HTTP/1.1
Host: openapi.kiwoom.com
Authorization: Bearer {access_token}
tr_cd: TTTC8001R
```

**Response**:

```json
{
  "rt_cd": "0",
  "msg_cd": "OPSP0000",
  "msg1": "정상처리 되었습니다.",
  "output": {
    "date": "20251122",
    "orders": [
      {
        "order_id": "2025112212345678",
        "stock_code": "005930",
        "order_type": "BUY",
        "status": "FILLED",
        "quantity": 100,
        "filled_price": "72000"
      }
    ]
  }
}
```

---

## 계좌 잔고 조회

### 11. 예수금 조회

**Endpoint**: `GET /account/balance`

**설명**: 계좌의 현재 예수금 및 총 자산을 조회한다.

**Request**:

```http
GET /account/balance?account_number=12345678 HTTP/1.1
Host: openapi.kiwoom.com
Authorization: Bearer {access_token}
tr_cd: TTTC8908R
```

**Response**:

```json
{
  "rt_cd": "0",
  "msg_cd": "OPSP0000",
  "msg1": "정상처리 되었습니다.",
  "output": {
    "account_number": "12345678",
    "cash_balance": "10000000",
    "total_asset_value": "15000000",
    "total_stock_value": "5000000",
    "total_pnl": "500000",
    "total_pnl_rate": "3.45",
    "timestamp": "2025-11-22T14:30:15+09:00"
  }
}
```

**응답 필드**:

| 필드명 | 타입 | 설명 |
|-------|------|------|
| `account_number` | string | 계좌번호 |
| `cash_balance` | string | 예수금 (현금 잔고) |
| `total_asset_value` | string | 총 평가 금액 |
| `total_stock_value` | string | 주식 평가 금액 |
| `total_pnl` | string | 총 손익 (원) |
| `total_pnl_rate` | string | 총 손익률 (%) |
| `timestamp` | string | 조회 시간 |

---

## 보유 종목 조회

### 12. 보유 종목 조회

**Endpoint**: `GET /account/positions`

**설명**: 계좌의 보유 종목 목록을 조회한다.

**Request**:

```http
GET /account/positions?account_number=12345678 HTTP/1.1
Host: openapi.kiwoom.com
Authorization: Bearer {access_token}
tr_cd: TTTC8434R
```

**Response**:

```json
{
  "rt_cd": "0",
  "msg_cd": "OPSP0000",
  "msg1": "정상처리 되었습니다.",
  "output": {
    "account_number": "12345678",
    "positions": [
      {
        "stock_code": "005930",
        "stock_name": "삼성전자",
        "quantity": 150,
        "average_buy_price": "70000",
        "current_price": "72000",
        "evaluation_amount": "10800000",
        "unrealized_pnl": "300000",
        "return_rate": "2.86"
      }
    ],
    "timestamp": "2025-11-22T14:30:15+09:00"
  }
}
```

**응답 필드**:

| 필드명 | 타입 | 설명 |
|-------|------|------|
| `stock_code` | string | 종목코드 |
| `stock_name` | string | 종목명 |
| `quantity` | integer | 보유 수량 |
| `average_buy_price` | string | 평균 매수가 |
| `current_price` | string | 현재가 |
| `evaluation_amount` | string | 평가 금액 |
| `unrealized_pnl` | string | 미실현 손익 (원) |
| `return_rate` | string | 수익률 (%) |

---

## 에러 코드 및 처리

### 에러 응답 형식

모든 API 에러는 다음 형식으로 반환된다:

```json
{
  "rt_cd": "1",
  "msg_cd": "ERROR_CODE",
  "msg1": "에러 메시지 상세 내용",
  "output": null
}
```

### 주요 에러 코드

| 에러 코드 | 메시지 | 설명 | 처리 방법 |
|----------|--------|------|----------|
| `AUTH0001` | 인증 실패 | 액세스 토큰이 유효하지 않음 | 토큰 재발급 |
| `AUTH0002` | 토큰 만료 | 액세스 토큰이 만료됨 | 토큰 재발급 |
| `ORDR0001` | 예수금 부족 | 매수 가능 금액 부족 | 주문 수량 조정 또는 취소 |
| `ORDR0002` | 주문 수량 오류 | 최소/최대 수량 위반 | 주문 수량 조정 |
| `ORDR0003` | 중복 주문 | 동일 종목 주문 중복 | 기존 주문 확인 후 재시도 |
| `ORDR0004` | 주문 가격 오류 | 호가 단위 미준수 | 호가 단위에 맞게 가격 조정 |
| `ORDR0005` | 주문 불가 종목 | 거래 정지/관리 종목 | 거래 재개 후 재시도 |
| `ORDR0006` | 주문 시간 외 | 장 운영 시간 외 주문 시도 | 장 시작 후 재시도 |
| `DATA0001` | 종목 코드 오류 | 존재하지 않는 종목코드 | 종목코드 확인 |
| `DATA0002` | 데이터 없음 | 조회 결과 없음 | 조회 조건 변경 |
| `RATE0001` | Rate Limit 초과 | API 호출 한도 초과 | 대기 후 재시도 |
| `SYST0001` | 서버 오류 | 내부 서버 오류 | 잠시 후 재시도 |
| `SYST0002` | 점검 중 | 시스템 점검 중 | 점검 종료 후 재시도 |

### 에러 처리 예시 (Python)

```python
import asyncio
from typing import Optional

class KiwoomAPIError(Exception):
    """Kiwoom API error exception."""

    def __init__(self, error_code: str, message: str):
        self.error_code = error_code
        self.message = message
        super().__init__(f"[{error_code}] {message}")

class KiwoomAPIClient:
    """Kiwoom API client with error handling."""

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.max_retries = 3
        self.retry_delay = 1.0  # seconds

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> dict:
        """Make API request with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.).
            endpoint: API endpoint path.
            **kwargs: Additional request parameters.

        Returns:
            API response data.

        Raises:
            KiwoomAPIError: If API returns an error.
        """
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    request_func = getattr(client, method.lower())
                    response = await request_func(
                        f"{self.base_url}{endpoint}",
                        **kwargs
                    )
                    response.raise_for_status()
                    data = response.json()

                    # Check API-level error
                    if data["rt_cd"] != "0":
                        error_code = data["msg_cd"]
                        error_msg = data["msg1"]

                        # Handle specific errors
                        if error_code in ["AUTH0001", "AUTH0002"]:
                            # Token expired, need to re-authenticate
                            raise KiwoomAPIError(error_code, "Token expired, re-authentication required")
                        elif error_code == "RATE0001":
                            # Rate limit, wait and retry
                            if attempt < self.max_retries - 1:
                                await asyncio.sleep(self.retry_delay * (attempt + 1))
                                continue
                        elif error_code.startswith("SYST"):
                            # System error, retry
                            if attempt < self.max_retries - 1:
                                await asyncio.sleep(self.retry_delay)
                                continue

                        raise KiwoomAPIError(error_code, error_msg)

                    return data["output"]

            except httpx.HTTPStatusError as e:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                    continue
                raise

        raise KiwoomAPIError("RETRY_EXHAUSTED", "Max retries exceeded")
```

---

## Rate Limiting

### Rate Limit 정책

키움증권 REST API는 다음과 같은 Rate Limiting 정책을 적용한다:

| 제한 타입 | 제한 값 | 기간 | 설명 |
|----------|--------|------|------|
| **시세 조회** | 초당 5회 | 1초 | 실시간 가격/호가 조회 |
| **차트 데이터** | 분당 20회 | 1분 | 일봉/분봉 데이터 조회 |
| **주문 실행** | 초당 2회 | 1초 | 매수/매도 주문 실행 |
| **계좌 조회** | 분당 10회 | 1분 | 잔고/보유종목 조회 |
| **전체 API** | 시간당 1000회 | 1시간 | 모든 API 호출 합산 |

### Rate Limit 헤더

API 응답에 다음 헤더가 포함된다:

```http
X-RateLimit-Limit: 5
X-RateLimit-Remaining: 3
X-RateLimit-Reset: 1700654400
```

| 헤더명 | 설명 |
|-------|------|
| `X-RateLimit-Limit` | 허용된 최대 요청 수 |
| `X-RateLimit-Remaining` | 남은 요청 수 |
| `X-RateLimit-Reset` | Rate limit 리셋 시간 (Unix timestamp) |

### Rate Limit 초과 시 응답

```json
{
  "rt_cd": "1",
  "msg_cd": "RATE0001",
  "msg1": "API 호출 한도를 초과했습니다. 잠시 후 다시 시도해주세요.",
  "output": null
}
```

**HTTP Status Code**: `429 Too Many Requests`

### Rate Limiting 처리 예시

```python
import asyncio
from datetime import datetime, timedelta
from collections import deque
from typing import Deque

class RateLimiter:
    """Rate limiter for API requests."""

    def __init__(self, max_calls: int, period_seconds: float):
        """Initialize rate limiter.

        Args:
            max_calls: Maximum number of calls allowed.
            period_seconds: Time period in seconds.
        """
        self.max_calls = max_calls
        self.period = timedelta(seconds=period_seconds)
        self.calls: Deque[datetime] = deque()

    async def wait_if_needed(self) -> None:
        """Wait if rate limit would be exceeded.

        This method blocks until a call can be made without
        exceeding the rate limit.
        """
        now = datetime.now()

        # Remove old calls outside the period
        while self.calls and (now - self.calls[0]) > self.period:
            self.calls.popleft()

        # If at limit, wait until oldest call expires
        if len(self.calls) >= self.max_calls:
            sleep_time = (self.calls[0] + self.period - now).total_seconds()
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

        # Record this call
        self.calls.append(datetime.now())

class KiwoomAPIClientWithRateLimit:
    """Kiwoom API client with rate limiting."""

    def __init__(self, access_token: str):
        self.access_token = access_token

        # Create rate limiters for different API categories
        self.price_limiter = RateLimiter(max_calls=5, period_seconds=1.0)
        self.chart_limiter = RateLimiter(max_calls=20, period_seconds=60.0)
        self.order_limiter = RateLimiter(max_calls=2, period_seconds=1.0)
        self.account_limiter = RateLimiter(max_calls=10, period_seconds=60.0)

    async def get_current_price(self, stock_code: str) -> dict:
        """Get current price with rate limiting.

        Args:
            stock_code: Stock code to query.

        Returns:
            Current price data.
        """
        await self.price_limiter.wait_if_needed()

        # Make actual API call
        # ...
        pass

    async def place_order(self, order_request: OrderRequest) -> dict:
        """Place order with rate limiting.

        Args:
            order_request: Order details.

        Returns:
            Order response.
        """
        await self.order_limiter.wait_if_needed()

        # Make actual API call
        # ...
        pass
```

---

## 베스트 프랙티스

### 1. 연결 관리

```python
class KiwoomAPIConnectionManager:
    """Manages API connection lifecycle."""

    def __init__(self, app_key: str, app_secret: str):
        self.app_key = app_key
        self.app_secret = app_secret
        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None

    async def ensure_authenticated(self) -> str:
        """Ensure valid access token exists.

        Returns:
            Valid access token.
        """
        now = datetime.now()

        # Refresh token 5 minutes before expiry
        if (not self.access_token or
            not self.token_expires_at or
            now >= self.token_expires_at - timedelta(minutes=5)):

            await self._refresh_token()

        return self.access_token

    async def _refresh_token(self) -> None:
        """Refresh access token."""
        auth_client = KiwoomAuthClient(self.app_key, self.app_secret)
        self.access_token = await auth_client.get_access_token()
        self.token_expires_at = datetime.now() + timedelta(hours=24)
```

### 2. 재시도 전략

- 네트워크 오류: 최대 3회 재시도, 지수 백오프 적용
- Rate Limit 오류: Rate limit 리셋까지 대기 후 재시도
- 서버 오류 (5xx): 최대 3회 재시도
- 클라이언트 오류 (4xx): 재시도 없이 즉시 실패

### 3. 로깅

모든 API 호출과 응답을 로그에 기록하여 추적 가능하도록 한다:

```python
import logging

logger = logging.getLogger(__name__)

async def api_call_with_logging(endpoint: str, **kwargs) -> dict:
    """Make API call with logging.

    Args:
        endpoint: API endpoint.
        **kwargs: Request parameters.

    Returns:
        API response.
    """
    logger.info(f"API Call: {endpoint}", extra={"params": kwargs})

    try:
        response = await make_api_call(endpoint, **kwargs)
        logger.info(f"API Success: {endpoint}", extra={"response": response})
        return response
    except Exception as e:
        logger.error(f"API Error: {endpoint}", extra={"error": str(e)}, exc_info=True)
        raise
```

---

## 요약

본 문서는 키움증권 REST API의 모든 주요 엔드포인트와 계약을 정의하였다. 실제 구현 시:

1. **인증 관리**: 토큰 만료 5분 전 자동 갱신
2. **에러 처리**: 에러 코드별 적절한 재시도 전략 적용
3. **Rate Limiting**: 각 API 카테고리별 Rate Limiter 구현
4. **로깅**: 모든 API 호출 추적 가능하도록 로그 기록

다음 문서: [internal-interfaces.md](./internal-interfaces.md)
