# 키움증권 REST API 매핑 명세서

## T050. 인증 (OAuth2 토큰 발급)
API 클라이언트 초기화 및 세션 유지를 위한 접근 토큰 발급 API입니다.

### [au10001] 접근토큰 발급
*   **URL:** `/oauth2/token`
*   **Method:** `POST`
*   **설명:** API 사용을 위한 Access Token을 발급받습니다.
*   **주요 Request:**
    *   `grant_type`: "client_credentials" (고정)
    *   `appkey`: 앱키
    *   `secretkey`: 시크릿키
*   **주요 Response:**
    *   `token`: 접근 토큰 (Authorization 헤더에 Bearer로 사용)
    *   `expires_in`: 토큰 만료 시간

---

## T052. 실시간 시세 조회
주식의 현재가, 호가 정보를 조회합니다.

### [ka10004] 주식호가요청
*   **URL:** `/api/dostk/mrkcond`
*   **Method:** `POST`
*   **설명:** 특정 종목의 매도/매수 호가(10단계) 정보를 조회합니다.
*   **주요 Request:**
    *   `stk_cd`: 종목코드
*   **주요 Response:**
    *   `sel_1_bid` ~ `sel_10_bid`: 매도 호가
    *   `buy_1_bid` ~ `buy_10_bid`: 매수 호가

### [ka10006] 주식시세요청
*   **URL:** `/api/dostk/mrkcond`
*   **Method:** `POST`
*   **설명:** 특정 종목의 현재가, 시가, 고가, 저가, 거래량 등을 조회합니다.
*   **주요 Request:**
    *   `stk_cd`: 종목코드
*   **주요 Response:**
    *   `cur_prc`: 현재가
    *   `open_pric`: 시가
    *   `high_pric`: 고가
    *   `low_pric`: 저가
    *   `trde_qty`: 거래량

---

## T053. 일봉 데이터 조회
차트 분석을 위한 과거 일별 데이터를 조회합니다.

### [ka10081] 주식일봉차트조회요청
*   **URL:** `/api/dostk/chart`
*   **Method:** `POST`
*   **설명:** 특정 종목의 일봉 차트 데이터를 조회합니다.
*   **주요 Request:**
    *   `stk_cd`: 종목코드
    *   `base_dt`: 기준일자 (YYYYMMDD)
*   **주요 Response:**
    *   `stk_dt_pole_chart_qry`: 일봉 데이터 리스트
        *   `dt`: 일자
        *   `open_pric`: 시가
        *   `high_pric`: 고가
        *   `low_pric`: 저가
        *   `cur_prc`: 종가
        *   `trde_qty`: 거래량

---

## T054. 매수 주문
현금 매수 주문을 실행합니다.

### [kt10000] 주식 매수주문
*   **URL:** `/api/dostk/ordr`
*   **Method:** `POST`
*   **설명:** 주식 현금 매수 주문을 전송합니다.
*   **주요 Request:**
    *   `acnt_no`: 계좌번호
    *   `stk_cd`: 종목코드
    *   `ord_qty`: 주문수량
    *   `ord_uv`: 주문단가 (시장가인 경우 0)
    *   `trde_tp`: 매매구분 (0:보통/지정가, 3:시장가 등)
*   **주요 Response:**
    *   `ord_no`: 주문번호
    *   `return_code`: 결과코드 (0:성공)

---

## T055. 매도 주문
보유 주식에 대한 매도 주문을 실행합니다.

### [kt10001] 주식 매도주문
*   **URL:** `/api/dostk/ordr`
*   **Method:** `POST`
*   **설명:** 주식 현금 매도 주문을 전송합니다.
*   **주요 Request:**
    *   `acnt_no`: 계좌번호
    *   `stk_cd`: 종목코드
    *   `ord_qty`: 주문수량
    *   `ord_uv`: 주문단가
    *   `trde_tp`: 매매구분
*   **주요 Response:**
    *   `ord_no`: 주문번호

---

## T056. 주문 상태 조회
주문의 체결 여부 및 미체결 잔량을 조회합니다.

### [ka10075] 미체결요청 (또는 kt10075)
*   **URL:** `/api/dostk/acnt`
*   **Method:** `POST`
*   **설명:** 계좌의 미체결 내역을 조회하여 주문 상태를 확인합니다.
*   **주요 Request:**
    *   `acnt_no`: 계좌번호
    *   `stk_cd`: 종목코드 (전체 조회시 공백)
*   **주요 Response:**
    *   `oso`: 미체결 리스트
        *   `ord_no`: 주문번호
        *   `ord_qty`: 주문수량
        *   `cntr_qty`: 체결수량
        *   `oso_qty`: 미체결수량

### [ka10076] 체결요청 (또는 kt10076)
*   **URL:** `/api/dostk/acnt`
*   **Method:** `POST`
*   **설명:** 당일 체결된 내역을 조회합니다.
*   **주요 Request:**
    *   `acnt_no`: 계좌번호
*   **주요 Response:**
    *   `cntr`: 체결 리스트

---

## T057. 계좌 잔고 조회 (예수금)
주문 가능 금액(예수금)을 확인합니다.

### [kt00001] 예수금상세현황요청
*   **URL:** `/api/dostk/acnt`
*   **Method:** `POST`
*   **설명:** 계좌의 예수금 및 주문 가능 금액을 상세 조회합니다.
*   **주요 Request:**
    *   `acnt_no`: 계좌번호
*   **주요 Response:**
    *   `entr`: 예수금
    *   `ord_alowa`: 주문가능현금
    *   `wthd_alowa`: 인출가능금액

---

## T058. 보유 종목 조회
현재 계좌에 보유 중인 주식 리스트를 조회합니다.

### [kt00018] 계좌평가잔고내역요청
*   **URL:** `/api/dostk/acnt`
*   **Method:** `POST`
*   **설명:** 계좌의 총 평가 금액 및 보유 종목별 잔고 현황을 조회합니다.
*   **주요 Request:**
    *   `acnt_no`: 계좌번호
    *   `qry_tp`: 조회구분 (1:합산, 2:개별)
*   **주요 Response:**
    *   `tot_evlt_amt`: 총평가금액
    *   `tot_pft_rt`: 총수익률
    *   `acnt_evlt_remn_indv_tot`: 보유 종목 리스트
        *   `stk_cd`: 종목번호
        *   `stk_nm`: 종목명
        *   `rmnd_qty`: 보유수량
        *   `evlt_amt`: 평가금액
        *   `evltv_prft`: 평가손익
        *   `pft_rt`: 수익률

---

## T059. 에러 처리
API 응답 헤더 또는 바디의 공통 에러 코드를 처리합니다.

*   **참고 페이지:** 526페이지 (오류코드)
*   **주요 에러 코드 예시:**
    *   `1501`: API ID Null or Invalid
    *   `1513`: Authorization fail (토큰 만료 또는 오류) - **재발급 로직 트리거**
    *   `8103`: 토큰 인증 실패 - **재발급 로직 트리거**
    *   `1687`: 재귀 호출 제한 (Rate Limit 관련 가능성)