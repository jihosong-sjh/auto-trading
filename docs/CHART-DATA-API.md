제공해주신 PDF 파일의 198~201페이지 내용을 바탕으로 작성한 마크다운 문서입니다.
이 구간은 **주식분봉차트조회요청(ka10080)**과 **주식일봉차트조회요청(ka10081)**에 대한 내용을 담고 있습니다.

---

# 키움 REST API 명세서 (Pages 198-201)

## 1. 주식분봉차트조회요청 (ka10080)

### API 정보
*   **메뉴 위치**: 국내주식 > 차트 > 주식분봉차트조회요청(ka10080)
*   **API 명**: 주식분봉차트조회요청
*   **API ID**: ka10080

### 기본정보
*   **Method**: POST
*   **운영 도메인**: `https://api.kiwoom.com`
*   **모의투자 도메인**: `https://mockapi.kiwoom.com` (KRX만 지원가능)
*   **URL**: `/api/dostk/chart`
*   **Format**: JSON
*   **Content-Type**: `application/json;charset=UTF-8`

### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
| :--- | :--- | :--- | :--- | :---: | :---: | :--- |
| Header | api-id | TR명 | String | Y | 10 | |
| Header | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출<br>예) Bearer Egicyx... |
| Header | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 cont-yn값 세팅 |
| Header | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 next-key값 세팅 |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드<br>(KRX:039490, NXT:039490_NX, SOR:039490_AL) |
| Body | tic_scope | 틱범위 | String | Y | 2 | 1:1분, 3:3분, 5:5분, 10:10분, 15:15분, 30:30분, 45:45분, 60:60분 |
| Body | upd_stkpc_tp | 수정주가구분 | String | Y | 1 | 0 or 1 |

### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
| :--- | :--- | :--- | :--- | :---: | :---: | :--- |
| Header | api-id | TR명 | String | Y | 10 | |
| Header | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| Header | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_cd | 종목코드 | String | N | 6 | |
| Body | stk_min_pole_chart_qry | 주식분봉차트조회 | LIST | N | | |
| Body | - cur_prc | 현재가 | String | N | 20 | 종가 |
| Body | - trde_qty | 거래량 | String | N | 20 | |
| Body | - cntr_tm | 체결시간 | String | N | 20 | |
| Body | - open_pric | 시가 | String | N | 20 | |
| Body | - high_pric | 고가 | String | N | 20 | |
| Body | - low_pric | 저가 | String | N | 20 | |
| Body | - pred_pre | 전일대비 | String | N | 20 | 현재가 - 전일종가 |
| Body | - pred_pre_sig | 전일대비 기호 | String | N | 20 | 1: 상한가, 2:상승, 3:보합, 4:하한가, 5:하락 |
| Body | - trde_tern_rt | 거래회전율 | String | N | 20 | |

### Request Example
```json
{
    "stk_cd": "005930",
    "tic_scope": "1",
    "upd_stkpc_tp": "1"
}
```

### Response Example
```json
{
    "stk_cd": "005930",
    "stk_min_pole_chart_qry": [
        {
            "cur_prc": "-78800",
            "trde_qty": "7913",
            "cntr_tm": "20250917132000",
            "open_pric": "-78850",
            "high_pric": "-78900",
            "low_pric": "-78800",
            "acc_trde_qty": "14947571",
            "pred_pre": "-600",
            "pred_pre_sig": "5"
        },
        {
            "cur_prc": "-78900",
            "trde_qty": "16084",
            "cntr_tm": "20250917131900",
            "open_pric": "-78900",
            "high_pric": "-78900",
            "low_pric": "-78800",
            "acc_trde_qty": "14939658",
            "pred_pre": "-500",
            "pred_pre_sig": "5"
        }
    ],
    "return_code": 0,
    "return_msg": "정상적으로 처리되었습니다"
}
```

---

## 2. 주식일봉차트조회요청 (ka10081)

### API 정보
*   **메뉴 위치**: 국내주식 > 차트 > 주식일봉차트조회요청(ka10081)
*   **API 명**: 주식일봉차트조회요청
*   **API ID**: ka10081

### 기본정보
*   **Method**: POST
*   **운영 도메인**: `https://api.kiwoom.com`
*   **모의투자 도메인**: `https://mockapi.kiwoom.com` (KRX만 지원가능)
*   **URL**: `/api/dostk/chart`
*   **Format**: JSON
*   **Content-Type**: `application/json;charset=UTF-8`

### Request

| 구분 | Element | 한글명 | Type | Required | Length | Description |
| :--- | :--- | :--- | :--- | :---: | :---: | :--- |
| Header | api-id | TR명 | String | Y | 10 | |
| Header | authorization | 접근토큰 | String | Y | 1000 | 토큰 지정시 토큰타입("Bearer") 붙혀서 호출<br>예) Bearer Egicyx... |
| Header | cont-yn | 연속조회여부 | String | N | 1 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 cont-yn값 세팅 |
| Header | next-key | 연속조회키 | String | N | 50 | 응답 Header의 연속조회여부값이 Y일 경우 다음데이터 요청시 응답 Header의 next-key값 세팅 |
| Body | stk_cd | 종목코드 | String | Y | 20 | 거래소별 종목코드<br>(KRX:039490, NXT:039490_NX, SOR:039490_AL) |
| Body | base_dt | 기준일자 | String | Y | 8 | YYYYMMDD |
| Body | upd_stkpc_tp | 수정주가구분 | String | Y | 1 | 0 or 1 |

### Response

| 구분 | Element | 한글명 | Type | Required | Length | Description |
| :--- | :--- | :--- | :--- | :---: | :---: | :--- |
| Header | api-id | TR명 | String | Y | 10 | |
| Header | cont-yn | 연속조회여부 | String | N | 1 | 다음 데이터가 있을시 Y값 전달 |
| Header | next-key | 연속조회키 | String | N | 50 | 다음 데이터가 있을시 다음 키값 전달 |
| Body | stk_cd | 종목코드 | String | N | 6 | |
| Body | stk_dt_pole_chart_qry | 주식일봉차트조회 | LIST | N | | |
| Body | - cur_prc | 현재가 | String | N | 20 | |
| Body | - trde_qty | 거래량 | String | N | 20 | |
| Body | - trde_prica | 거래대금 | String | N | 20 | |
| Body | - dt | 일자 | String | N | 20 | |
| Body | - open_pric | 시가 | String | N | 20 | |
| Body | - high_pric | 고가 | String | N | 20 | |
| Body | - low_pric | 저가 | String | N | 20 | |
| Body | - pred_pre | 전일대비 | String | N | 20 | 현재가 - 전일종가 |
| Body | - pred_pre_sig | 전일대비기호 | String | N | 20 | 1: 상한가, 2:상승, 3:보합, 4:하한가, 5:하락 |
| Body | - trde_tern_rt | 거래회전율 | String | N | 20 | |

### Request Example
```json
{
    "stk_cd": "005930",
    "base_dt": "20250908",
    "upd_stkpc_tp": "1"
}
```

### Response Example
```json
{
    "stk_cd": "005930",
    "stk_dt_pole_chart_qry": [
        {
            "cur_prc": "70100",
            "trde_qty": "9263135",
            "trde_prica": "648525",
            "dt": "20250908",
            "open_pric": "69800",
            "high_pric": "70500",
            "low_pric": "69600",
            "pred_pre": "+600",
            "pred_pre_sig": "2",
            "trde_tern_rt": "+0.16"
        },
        {
            "cur_prc": "69500",
            "trde_qty": "11526724",
            "trde_prica": "804642",
            "dt": "20250905",
            "open_pric": "70300",
            "high_pric": "70400",
            "low_pric": "69500",
            "pred_pre": "-600",
            "pred_pre_sig": "5",
            "trde_tern_rt": "+0.19"
        }
    ],
    "return_code": 0,
    "return_msg": "정상적으로 처리되었습니다"
}
```