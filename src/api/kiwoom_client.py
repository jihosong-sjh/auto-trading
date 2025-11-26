"""키움증권 REST API 클라이언트 구현."""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, Field

from ..models import (
    Account,
    ChartInterval,
    Order,
    OrderStatus,
    OrderType,
    Position,
    PriceType,
    Stock,
)
from ..models.chart_data import ChartData
from ..utils.logger import get_logger
from .exceptions import (
    APITimeoutError,
    InsufficientBalanceError,
    InvalidStockCodeError,
    KiwoomAPIError,
    RateLimitExceededError,
)
from .rate_limiter import RateLimiter, RequestPriority
from ..cache.distributed_rate_limiter import DistributedRateLimiter

KST = ZoneInfo("Asia/Seoul")
logger = get_logger(__name__)


class TokenResponse(BaseModel):
    """OAuth2 토큰 응답 모델 (au10001)."""

    model_config = {"populate_by_name": True}

    token: str = Field(..., description="접근 토큰", alias="access_token")
    expires_dt: str = Field(..., description="토큰 만료 시간 (YYYYMMDDHHmmss)")
    return_code: int = Field(default=0, description="응답 코드")
    return_msg: str = Field(default="", description="응답 메시지")


class KiwoomClient:
    """키움증권 REST API 클라이언트."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        account_number: str,
        base_url: str = "https://api.kiwoom.com",
        max_requests_per_second: int = 15,
        request_timeout: float = 10.0,
        distributed_rate_limiter: Optional[DistributedRateLimiter] = None
    ):
        """KiwoomClient 초기화.

        Args:
            api_key: API 키
            api_secret: API 시크릿
            account_number: 계좌번호
            base_url: API 베이스 URL
            max_requests_per_second: 초당 최대 요청 수
            request_timeout: 요청 타임아웃 (초)
            distributed_rate_limiter: Redis 기반 분산 rate limiter (옵션)
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.account_number = account_number
        self.base_url = base_url.rstrip("/")
        self.request_timeout = request_timeout

        self.client: httpx.AsyncClient | None = None

        # 분산 rate limiter가 제공되면 우선 사용, 없으면 로컬 사용
        self.distributed_rate_limiter = distributed_rate_limiter
        self.local_rate_limiter = RateLimiter(max_requests=max_requests_per_second, time_window=1.0)

        # 분산 환경 여부 플래그
        self.use_distributed = distributed_rate_limiter is not None

        self.access_token: str | None = None
        self.token_expires_at: datetime | None = None

    async def __aenter__(self):
        """비동기 컨텍스트 매니저 진입."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """비동기 컨텍스트 매니저 종료."""
        await self.close()

    async def connect(self) -> None:
        """API 클라이언트 연결 및 인증."""
        if self.client is None:
            self.client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.request_timeout),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }
            )

        # Rate limiter 시작 (로컬 rate limiter만 필요)
        await self.local_rate_limiter.start()

        await self._refresh_token()

        if self.use_distributed:
            logger.info("Kiwoom API client connected with distributed rate limiter")
        else:
            logger.info("Kiwoom API client connected with local rate limiter")

    async def close(self) -> None:
        """API 클라이언트 연결 종료."""
        # Rate limiter 종료
        await self.local_rate_limiter.stop()

        if self.client:
            await self.client.aclose()
            self.client = None
            logger.info("Kiwoom API client closed")

    async def _refresh_token(self) -> None:
        """OAuth2 토큰 발급 또는 갱신 (au10001).

        URL: POST /oauth2/token
        Request: grant_type, appkey, secretkey
        Response: token, expires_in
        """
        if not self.client:
            raise KiwoomAPIError("Client not connected. Call connect() first.")

        logger.info("Refreshing OAuth2 token")

        payload = {
            "grant_type": "client_credentials",
            "appkey": self.api_key,
            "secretkey": self.api_secret
        }

        try:
            response = await self.client.post("/oauth2/token", json=payload)
            response.raise_for_status()

            token_data = response.json()
            logger.debug(f"Token response: {token_data}")

            # Kiwoom API returns return_code in all responses
            # return_code: 0 = success, non-zero = error
            if "return_code" in token_data:
                return_code = token_data.get("return_code")
                return_msg = token_data.get("return_msg", "Unknown")

                if return_code != 0:
                    logger.error(f"Token refresh failed with return_code {return_code}: {return_msg}")
                    raise KiwoomAPIError(
                        f"Token refresh failed (code: {return_code}): {return_msg}",
                        response_data=token_data
                    )

                logger.info(f"Token API response: {return_msg}")

            token_response = TokenResponse(**token_data)

            self.access_token = token_response.token

            # Parse expires_dt (format: YYYYMMDDHHmmss)
            expires_dt = datetime.strptime(token_response.expires_dt, "%Y%m%d%H%M%S")
            self.token_expires_at = expires_dt.replace(tzinfo=KST)

            logger.info(f"Token refreshed successfully. Expires at {self.token_expires_at}")

        except httpx.HTTPStatusError as e:
            logger.error(f"Token refresh failed: {e.response.status_code} - {e.response.text}")
            raise KiwoomAPIError(
                f"Token refresh failed: {e.response.text}",
                status_code=e.response.status_code,
                response_data=e.response.json() if "application/json" in e.response.headers.get("content-type", "") else {}
            ) from e
        except KiwoomAPIError:
            # Re-raise KiwoomAPIError as-is
            raise
        except Exception as e:
            logger.error(f"Unexpected error during token refresh: {e}")
            raise KiwoomAPIError(f"Token refresh failed: {str(e)}") from e

    async def _ensure_authenticated(self) -> None:
        """토큰 유효성 확인 및 필요 시 갱신."""
        if not self.access_token or not self.token_expires_at:
            await self._refresh_token()
        elif datetime.now(tz=KST) >= self.token_expires_at:
            logger.info("Token expired, refreshing")
            await self._refresh_token()

    async def _request(
        self,
        method: str,
        endpoint: str,
        max_retries: int = 3,
        tr_id: str | None = None,
        priority: RequestPriority = RequestPriority.LOW,
        **kwargs
    ) -> dict[str, Any]:
        """API 요청 실행 (재시도 로직 포함).

        Args:
            method: HTTP 메서드 (GET, POST 등)
            endpoint: API 엔드포인트
            max_retries: 최대 재시도 횟수
            tr_id: 거래 ID
            priority: 요청 우선순위 (기본값: LOW)
            **kwargs: 추가 요청 파라미터
        """
        if not self.client:
            raise KiwoomAPIError("Client not connected. Call connect() first.")

        await self._ensure_authenticated()

        # Rate limiting: 분산 또는 로컬 사용
        if self.use_distributed and self.distributed_rate_limiter:
            # Redis 기반 분산 rate limiter 사용
            success = await self.distributed_rate_limiter.acquire(
                identifier="kiwoom_api",
                wait=True,
                timeout=30.0
            )
            if not success:
                raise RateLimitExceededError("Distributed rate limit exceeded")
        else:
            # 로컬 rate limiter 사용 (우선순위 기반)
            await self.local_rate_limiter.acquire(
                priority=priority,
                description=f"{method} {endpoint} (tr_id={tr_id})"
            )

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"
        headers["appkey"] = self.api_key
        headers["appsecret"] = self.api_secret
        if tr_id:
            headers["api-id"] = tr_id  # Kiwoom API uses "api-id" header

        retry_count = 0
        last_exception = None

        while retry_count < max_retries:
            try:
                response = await self.client.request(
                    method=method,
                    url=endpoint,
                    headers=headers,
                    **kwargs
                )

                # Success response (2xx status codes)
                if response.is_success:
                    try:
                        # Handle Korean encoding (EUC-KR/cp949) from Mock API
                        # Always decode manually to handle various encodings
                        import json

                        json_data = None
                        content = response.content

                        # Try common encodings in order of likelihood
                        for encoding in ['utf-8', 'euc-kr', 'cp949']:
                            try:
                                text = content.decode(encoding)
                                json_data = json.loads(text)
                                if encoding != 'utf-8':
                                    logger.debug(f"Decoded response with {encoding} encoding")
                                break
                            except (UnicodeDecodeError, json.JSONDecodeError):
                                continue

                        if json_data is None:
                            # If all encodings fail, raise error
                            raise ValueError(f"Failed to decode response with any encoding. Content: {content[:100]}")

                        # Check Kiwoom-specific return_code in response body
                        # return_code: 0 = success, non-zero = error
                        if "return_code" in json_data:
                            return_code = json_data.get("return_code")
                            if return_code != 0:
                                return_msg = json_data.get("return_msg", "Unknown error")
                                logger.error(f"API returned error: code={return_code}, msg={return_msg}")
                                raise KiwoomAPIError(
                                    f"API error (return_code: {return_code}): {return_msg}",
                                    status_code=200,
                                    response_data=json_data
                                )

                        return json_data
                    except KiwoomAPIError:
                        raise
                    except Exception as e:
                        logger.error(f"Failed to parse success response as JSON: {e}")
                        raise KiwoomAPIError(f"Invalid JSON in success response: {str(e)}") from e

                # Error response - try to parse error details
                error_data = {}
                error_text = ""

                # Try to decode error response with multiple encodings
                import json
                content = response.content
                for encoding in ['utf-8', 'euc-kr', 'cp949']:
                    try:
                        error_text = content.decode(encoding)
                        if "application/json" in response.headers.get("content-type", ""):
                            error_data = json.loads(error_text)
                        break
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue

                error_message = error_data.get("message", error_text)
                error_code = str(error_data.get("error_code", ""))

                # Handle Kiwoom-specific error codes (T059)
                # 1513, 8103: Token authentication failure - trigger re-auth
                if error_code in ["1513", "8103"]:
                    logger.warning(f"Token authentication failed (code: {error_code}). Re-authenticating...")
                    self.access_token = None
                    self.token_expires_at = None
                    # Don't retry here - let it fail and retry on next request
                    raise KiwoomAPIError(
                        f"Token authentication failed: {error_message}",
                        status_code=response.status_code,
                        response_data=error_data
                    )

                # 1501: API ID Null or Invalid
                if error_code == "1501":
                    raise KiwoomAPIError(
                        f"Invalid API credentials: {error_message}",
                        status_code=response.status_code,
                        response_data=error_data
                    )

                # 1687: Recursion limit (Rate Limit)
                if error_code == "1687" or response.status_code == 429:
                    raise RateLimitExceededError(
                        f"Rate limit exceeded: {error_message}",
                        status_code=response.status_code,
                        response_data=error_data
                    )

                # HTTP 400 errors
                if response.status_code == 400:
                    if "insufficient balance" in error_message.lower() or "예수금 부족" in error_message:
                        raise InsufficientBalanceError(
                            error_message,
                            status_code=response.status_code,
                            response_data=error_data
                        )
                    if "invalid stock code" in error_message.lower() or "종목코드" in error_message:
                        raise InvalidStockCodeError(
                            error_message,
                            status_code=response.status_code,
                            response_data=error_data
                        )

                raise KiwoomAPIError(
                    f"API error (code: {error_code}): {error_message}",
                    status_code=response.status_code,
                    response_data=error_data
                )

            except httpx.TimeoutException as e:
                retry_count += 1
                last_exception = e
                logger.warning(f"Request timeout (attempt {retry_count}/{max_retries}): {endpoint}")

                if retry_count >= max_retries:
                    raise APITimeoutError(f"Request timed out after {max_retries} attempts") from e

                await asyncio.sleep(2 ** retry_count)

            except (InsufficientBalanceError, InvalidStockCodeError, RateLimitExceededError):
                raise

            except KiwoomAPIError:
                raise

            except Exception as e:
                retry_count += 1
                last_exception = e
                logger.error(f"Unexpected error (attempt {retry_count}/{max_retries}): {e}")

                if retry_count >= max_retries:
                    raise KiwoomAPIError(f"Request failed after {max_retries} attempts: {str(e)}") from e

                await asyncio.sleep(2 ** retry_count)

        raise KiwoomAPIError(
            f"Request failed after {max_retries} attempts",
            response_data={"last_exception": str(last_exception)}
        )

    async def get_stock_price(self, stock_code: str) -> Stock:
        """실시간 시세 조회 (ka10006).

        URL: POST /api/dostk/mrkcond
        Request: tr_cd, stk_cd
        Response: cur_prc, open_pric, high_pric, low_pric, trde_qty
        """
        logger.info(f"Fetching stock price for {stock_code}")

        payload = {
            "stk_cd": stock_code  # Only stock code in body
        }

        data = await self._request("POST", "/api/dostk/mrkcond", tr_id="ka10006", json=payload)

        # Parse response (Kiwoom Mock API format)
        # Field mapping:
        # - close_pric: 현재가 (+ prefix means positive)
        # - open_pric, high_pric, low_pric: OHLC
        # - trde_qty: 거래량

        def parse_price(price_str: str) -> Decimal:
            """Parse price string like '+101400' or '-255000' to Decimal."""
            if not price_str:
                return Decimal("0")
            # Remove leading '+' or '-' sign for Decimal conversion
            clean_price = price_str.lstrip('+-')
            # Get absolute value (prices should always be positive)
            return Decimal(clean_price)

        # Infer market from stock code (since API doesn't provide it)
        # KOSPI: 000000~099999 (typical, not absolute rule)
        stock_code_int = int(stock_code)
        market = "KOSPI" if stock_code_int < 100000 else "KOSDAQ"

        # Stock name fallback (API may not provide it in ka10006)
        stock_name = data.get("stk_nm") or f"Stock_{stock_code}"

        return Stock(
            stock_code=stock_code,
            stock_name=stock_name,
            market=market,
            current_price=parse_price(data.get("close_pric", "0")),
            open_price=parse_price(data.get("open_pric")) if data.get("open_pric") else None,
            high_price=parse_price(data.get("high_pric")) if data.get("high_pric") else None,
            low_price=parse_price(data.get("low_pric")) if data.get("low_pric") else None,
            volume=int(data.get("trde_qty", 0)),
            updated_at=datetime.now(tz=KST)
        )

    async def get_chart_data(
        self,
        stock_code: str,
        interval: ChartInterval = ChartInterval.DAY,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
        priority: RequestPriority = RequestPriority.BACKGROUND
    ) -> list[ChartData]:
        """일봉 차트 데이터 조회 (ka10081).

        URL: POST /api/dostk/chart
        Request: tr_cd, stk_cd, base_dt
        Response: stk_dt_pole_chart_qry (dt, open_pric, high_pric, low_pric, cur_prc, trde_qty)

        Args:
            stock_code: 종목 코드
            interval: 차트 간격
            start_date: 시작 날짜
            end_date: 종료 날짜
            limit: 조회 개수
            priority: 요청 우선순위 (기본값: BACKGROUND)
        """
        logger.info(f"Fetching chart data for {stock_code}, interval={interval.value}, priority={priority.name}")

        if not end_date:
            end_date = datetime.now(tz=KST)

        payload = {
            "stk_cd": stock_code,
            "base_dt": end_date.strftime("%Y%m%d"),
            "upd_stkpc_tp": "1"  # 수정주가구분: 0=미적용, 1=적용
        }

        data = await self._request("POST", "/api/dostk/chart", tr_id="ka10081", priority=priority, json=payload)

        chart_list = []
        for item in data.get("stk_dt_pole_chart_qry", []):
            # Parse date from YYYYMMDD format
            dt_str = str(item["dt"])
            timestamp = datetime.strptime(dt_str, "%Y%m%d").replace(tzinfo=KST)

            chart = ChartData(
                stock_code=stock_code,
                interval=interval,
                timestamp=timestamp,
                open_price=Decimal(str(item["open_pric"])),
                high_price=Decimal(str(item["high_pric"])),
                low_price=Decimal(str(item["low_pric"])),
                close_price=Decimal(str(item["cur_prc"])),
                volume=int(item["trde_qty"])
            )
            chart_list.append(chart)

        return chart_list

    async def submit_order(self, order: Order) -> Order:
        """주문 제출 (매수/매도) (kt10000, kt10001).

        URL: POST /api/dostk/ordr
        Request: tr_cd, acnt_no, stk_cd, ord_qty, ord_uv, trde_tp
        Response: ord_no, return_code

        trde_tp (매매구분):
        - 0: 보통/지정가
        - 3: 시장가
        """
        # use_enum_values=True로 인해 order_type이 문자열일 수 있음
        order_type_value = order.order_type.value if isinstance(order.order_type, OrderType) else order.order_type
        logger.info(f"Submitting order: {order_type_value} {order.quantity} shares of {order.stock_code}")

        # Determine tr_cd and trde_tp
        tr_cd = "kt10000" if order_type_value == OrderType.BUY.value else "kt10001"  # 매수/매도 구분

        price_type_value = order.price_type.value if isinstance(order.price_type, PriceType) else order.price_type
        if price_type_value == PriceType.MARKET.value:
            trde_tp = "3"  # 시장가
            ord_uv = 0  # 시장가는 0
        else:
            trde_tp = "0"  # 지정가
            ord_uv = int(order.limit_price) if order.limit_price else 0

        payload = {
            "tr_cd": tr_cd,
            "acnt_no": self.account_number,
            "stk_cd": order.stock_code,
            "ord_qty": str(order.quantity),  # API requires string type
            "ord_uv": str(ord_uv),  # API requires string type
            "trde_tp": trde_tp,
            "dmst_stex_tp": "KRX"  # 국내거래소구분: KRX(한국거래소), NXT(넥스트레이드), SOR
        }

        data = await self._request("POST", "/api/dostk/ordr", tr_id=tr_cd, json=payload)

        # Check return code (API may return int or string)
        return_code = data.get("return_code", 0)
        # 0 또는 "0" 모두 성공으로 처리
        if str(return_code) != "0":
            raise KiwoomAPIError(
                f"Order failed with return_code: {return_code}",
                response_data=data
            )

        # Update order with response
        order_no = data.get("ord_no")
        if order_no:
            order.order_id = order_no

        order.status = OrderStatus.PENDING  # 주문 접수됨
        order.submitted_at = datetime.now(tz=KST)

        logger.info(f"Order submitted successfully: order_id={order.order_id}, ord_no={order_no}")

        return order

    async def get_order_status(self, order_id: str, stock_code: str | None = None) -> Order | None:
        """주문 상태 조회 (ka10075 미체결).

        URL: POST /api/dostk/acnt
        Request: tr_cd, acnt_no, stk_cd (optional)
        Response: oso (ord_no, ord_qty, cntr_qty, oso_qty)

        Note:
            - 미체결 목록에서 해당 주문번호를 찾아 반환합니다.
            - API 응답에 order_type, price_type 정보가 없어 기본값 사용
            - 정확한 정보가 필요하면 submit_order() 응답을 저장하여 사용하세요.

        Args:
            order_id: 주문번호 (ord_no)
            stock_code: 종목코드 (선택, 특정 종목으로 필터링)

        Returns:
            Order 객체 또는 None (미체결 목록에 없으면 None)
        """
        logger.info(f"Fetching order status for {order_id}")

        payload = {
            "tr_cd": "ka10075",  # 미체결요청
            "acnt_no": self.account_number,
        }
        if stock_code:
            payload["stk_cd"] = stock_code

        data = await self._request("POST", "/api/dostk/acnt", json=payload)

        # Search for order in unfilled orders list (oso)
        oso_list = data.get("oso", [])
        for oso_item in oso_list:
            if oso_item.get("ord_no") == order_id:
                ord_qty = int(oso_item.get("ord_qty", 0))
                cntr_qty = int(oso_item.get("cntr_qty", 0))
                # oso_qty = int(oso_item.get("oso_qty", 0))  # 미체결수량 (현재 미사용)

                # Determine status
                if cntr_qty == 0:
                    status = OrderStatus.PENDING
                elif cntr_qty < ord_qty:
                    status = OrderStatus.PARTIALLY_FILLED
                else:
                    status = OrderStatus.FILLED

                return Order(
                    order_id=order_id,
                    account_number=self.account_number,
                    stock_code=oso_item.get("stk_cd", stock_code or ""),
                    order_type=OrderType.BUY,  # TODO: Need to store this separately
                    price_type=PriceType.LIMIT,  # TODO: Need to store this separately
                    quantity=ord_qty,
                    limit_price=None,
                    status=status,
                    filled_quantity=cntr_qty,
                    filled_price=None,
                    created_at=datetime.now(tz=KST),
                    submitted_at=datetime.now(tz=KST),
                    filled_at=datetime.now(tz=KST) if cntr_qty > 0 else None
                )

        # Order not found in unfilled list - may be fully filled or cancelled
        logger.warning(f"Order {order_id} not found in unfilled orders list")
        return None

    async def get_filled_orders(self) -> list[Order]:
        """체결 내역 조회 (ka10076).

        URL: POST /api/dostk/acnt
        Request: tr_cd, acnt_no
        Response: cntr (체결 리스트)

        Note:
            - 당일 체결된 내역을 조회합니다.
            - 완전 체결된 주문 정보 확인에 활용

        Returns:
            체결된 주문 리스트
        """
        logger.info(f"Fetching filled orders for {self.account_number}")

        payload = {
            "tr_cd": "ka10076",  # 체결요청
            "acnt_no": self.account_number
        }

        data = await self._request("POST", "/api/dostk/acnt", json=payload)

        filled_orders = []
        for cntr_item in data.get("cntr", []):
            order = Order(
                order_id=cntr_item.get("ord_no", ""),
                account_number=self.account_number,
                stock_code=cntr_item.get("stk_cd", ""),
                order_type=OrderType.BUY,  # API에서 제공하지 않음
                price_type=PriceType.LIMIT,  # API에서 제공하지 않음
                quantity=int(cntr_item.get("ord_qty", 0)),
                limit_price=None,
                status=OrderStatus.FILLED,
                filled_quantity=int(cntr_item.get("cntr_qty", 0)),
                filled_price=Decimal(str(cntr_item.get("cntr_prc", 0))) if cntr_item.get("cntr_prc") else None,
                created_at=datetime.now(tz=KST),
                submitted_at=datetime.now(tz=KST),
                filled_at=datetime.now(tz=KST)
            )
            filled_orders.append(order)

        return filled_orders

    async def get_account(self) -> Account:
        """계좌 잔고 조회 (kt00001 예수금상세현황요청).

        URL: POST /api/dostk/acnt
        API ID: kt00001 (예수금상세현황요청)
        Request Header: api-id (TR명)
        Request Body: qry_tp (조회구분: 3=추정조회, 2=일반조회)
        Response: entr (예수금), ord_alow_amt (주문가능금액), pymn_alow_amt (출금가능금액)
        """
        logger.info(f"Fetching account balance for {self.account_number}")

        payload = {
            "qry_tp": "3"  # 3: 추정조회, 2: 일반조회
        }

        data = await self._request(
            "POST",
            "/api/dostk/acnt",
            tr_id="kt00001",  # API ID를 Header에 전달
            json=payload
        )

        # Extract balance information
        entr = Decimal(str(data.get("entr", 0)))  # 예수금
        ord_alow_amt = Decimal(str(data.get("ord_alow_amt", 0)))  # 주문가능금액
        # pymn_alow_amt = Decimal(str(data.get("pymn_alow_amt", 0)))  # 출금가능금액 (현재 미사용)

        return Account(
            account_number=self.account_number,
            name=data.get("acnt_nm", ""),
            cash_balance=ord_alow_amt,  # Use ord_alow_amt as available cash
            total_asset_value=entr,  # Use entr as total asset
            total_pnl=Decimal("0"),  # Not provided by this API
            daily_pnl=Decimal("0"),  # Not provided by this API
            daily_loss_limit=Decimal("0"),  # Not provided by this API
            updated_at=datetime.now(tz=KST)
        )

    async def get_positions(self) -> list[Position]:
        """보유 종목 조회 (kt00018 계좌평가잔고내역요청).

        URL: POST /api/dostk/acnt
        Request: tr_cd, acnt_no, qry_tp (조회구분: 1-합산, 2-개별)
        Response: acnt_evlt_remn_indv_tot (stk_cd, stk_nm, rmnd_qty, evlt_amt, evltv_prft, pft_rt)
        """
        logger.info(f"Fetching positions for {self.account_number}")

        payload = {
            "tr_cd": "kt00018",  # 계좌평가잔고내역요청
            "acnt_no": self.account_number,
            "qry_tp": "2"  # 개별 조회
        }

        data = await self._request("POST", "/api/dostk/acnt", json=payload)

        positions = []
        for item in data.get("acnt_evlt_remn_indv_tot", []):
            stk_cd = item.get("stk_cd", "")
            rmnd_qty = int(item.get("rmnd_qty", 0))  # 보유수량
            evlt_amt = Decimal(str(item.get("evlt_amt", 0)))  # 평가금액

            # Calculate average buy price from evaluation amount and quantity
            avg_buy_price = evlt_amt / Decimal(rmnd_qty) if rmnd_qty > 0 else Decimal("0")

            position = Position(
                account_number=self.account_number,
                stock_code=stk_cd,
                quantity=rmnd_qty,
                average_buy_price=avg_buy_price,
                current_price=avg_buy_price,  # Use same as avg for now
                opened_at=datetime.now(tz=KST),
                updated_at=datetime.now(tz=KST)
            )
            positions.append(position)

        return positions
