"""키움증권 REST API 클라이언트 구현."""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
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
from .rate_limiter import RateLimiter

KST = ZoneInfo("Asia/Seoul")
logger = get_logger(__name__)


class TokenResponse(BaseModel):
    """OAuth2 토큰 응답 모델."""

    access_token: str = Field(..., description="액세스 토큰")
    token_type: str = Field(..., description="토큰 타입 (Bearer)")
    expires_in: int = Field(..., description="토큰 만료 시간 (초)")
    refresh_token: str | None = Field(None, description="리프레시 토큰")


class KiwoomClient:
    """키움증권 REST API 클라이언트."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        account_number: str,
        base_url: str = "https://api.kiwoom.com",
        max_requests_per_second: int = 15,
        request_timeout: float = 10.0
    ):
        """KiwoomClient 초기화."""
        self.api_key = api_key
        self.api_secret = api_secret
        self.account_number = account_number
        self.base_url = base_url.rstrip("/")
        self.request_timeout = request_timeout

        self.client: httpx.AsyncClient | None = None
        self.rate_limiter = RateLimiter(max_requests=max_requests_per_second, time_window=1.0)

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
        await self._refresh_token()
        logger.info("Kiwoom API client connected successfully")

    async def close(self) -> None:
        """API 클라이언트 연결 종료."""
        if self.client:
            await self.client.aclose()
            self.client = None
            logger.info("Kiwoom API client closed")

    async def _refresh_token(self) -> None:
        """OAuth2 토큰 발급 또는 갱신."""
        if not self.client:
            raise KiwoomAPIError("Client not connected. Call connect() first.")

        logger.info("Refreshing OAuth2 token")

        payload = {
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.api_secret
        }

        try:
            response = await self.client.post("/oauth2/token", json=payload)
            response.raise_for_status()

            token_data = response.json()
            token_response = TokenResponse(**token_data)

            self.access_token = token_response.access_token
            self.token_expires_at = datetime.now(tz=KST) + timedelta(seconds=token_response.expires_in - 60)

            logger.info(f"Token refreshed successfully. Expires at {self.token_expires_at}")

        except httpx.HTTPStatusError as e:
            logger.error(f"Token refresh failed: {e.response.status_code} - {e.response.text}")
            raise KiwoomAPIError(
                f"Token refresh failed: {e.response.text}",
                status_code=e.response.status_code,
                response_data=e.response.json() if "application/json" in e.response.headers.get("content-type", "") else {}
            ) from e
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
        **kwargs
    ) -> dict[str, Any]:
        """API 요청 실행 (재시도 로직 포함)."""
        if not self.client:
            raise KiwoomAPIError("Client not connected. Call connect() first.")

        await self._ensure_authenticated()
        await self.rate_limiter.acquire()

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"

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
                        return response.json()
                    except Exception as e:
                        logger.error(f"Failed to parse success response as JSON: {e}")
                        raise KiwoomAPIError(f"Invalid JSON in success response: {str(e)}") from e

                # Error response - try to parse error details
                error_data = {}
                if "application/json" in response.headers.get("content-type", ""):
                    try:
                        error_data = response.json()
                    except Exception as e:
                        logger.warning(f"Failed to parse error response as JSON: {e}")

                error_message = error_data.get("message", response.text)

                if response.status_code == 429:
                    raise RateLimitExceededError(
                        "Rate limit exceeded",
                        status_code=response.status_code,
                        response_data=error_data
                    )
                if response.status_code == 400:
                    if "insufficient balance" in error_message.lower():
                        raise InsufficientBalanceError(
                            error_message,
                            status_code=response.status_code,
                            response_data=error_data
                        )
                    if "invalid stock code" in error_message.lower():
                        raise InvalidStockCodeError(
                            error_message,
                            status_code=response.status_code,
                            response_data=error_data
                        )

                raise KiwoomAPIError(
                    f"API error: {error_message}",
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
        """실시간 시세 조회."""
        logger.info(f"Fetching stock price for {stock_code}")
        data = await self._request("GET", f"/market/price/{stock_code}")

        return Stock(
            stock_code=data["stock_code"],
            stock_name=data["stock_name"],
            market=data["market"],
            current_price=Decimal(str(data["current_price"])),
            open_price=Decimal(str(data.get("open_price", 0))) if data.get("open_price") else None,
            high_price=Decimal(str(data.get("high_price", 0))) if data.get("high_price") else None,
            low_price=Decimal(str(data.get("low_price", 0))) if data.get("low_price") else None,
            volume=data.get("volume", 0),
            updated_at=datetime.now(tz=KST)
        )

    async def get_chart_data(
        self,
        stock_code: str,
        interval: ChartInterval = ChartInterval.DAY,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100
    ) -> list[ChartData]:
        """일봉/분봉 차트 데이터 조회."""
        logger.info(f"Fetching chart data for {stock_code}, interval={interval.value}")

        if not end_date:
            end_date = datetime.now(tz=KST)
        if not start_date:
            start_date = end_date - timedelta(days=100)

        params = {
            "interval": interval.value,
            "start_date": start_date.strftime("%Y%m%d"),
            "end_date": end_date.strftime("%Y%m%d"),
            "limit": limit
        }

        data = await self._request("GET", f"/market/chart/{stock_code}", params=params)

        chart_list = []
        for item in data.get("chart_data", []):
            chart = ChartData(
                stock_code=stock_code,
                interval=interval,
                timestamp=datetime.fromisoformat(item["timestamp"]),
                open_price=Decimal(str(item["open_price"])),
                high_price=Decimal(str(item["high_price"])),
                low_price=Decimal(str(item["low_price"])),
                close_price=Decimal(str(item["close_price"])),
                volume=item["volume"]
            )
            chart_list.append(chart)

        return chart_list

    async def submit_order(self, order: Order) -> Order:
        """주문 제출 (매수/매도)."""
        logger.info(f"Submitting order: {order.order_type.value} {order.quantity} shares of {order.stock_code}")

        endpoint = "/order/buy" if order.order_type == OrderType.BUY else "/order/sell"

        payload = {
            "account_number": self.account_number,
            "stock_code": order.stock_code,
            "quantity": order.quantity,
            "price_type": order.price_type.value,
        }

        if order.price_type == PriceType.LIMIT and order.limit_price:
            payload["limit_price"] = str(order.limit_price)

        data = await self._request("POST", endpoint, json=payload)

        order.status = OrderStatus[data["status"]]
        order.submitted_at = datetime.now(tz=KST)

        if data.get("filled_quantity"):
            order.filled_quantity = data["filled_quantity"]
        if data.get("filled_price"):
            order.filled_price = Decimal(str(data["filled_price"]))
        if data.get("filled_at"):
            order.filled_at = datetime.fromisoformat(data["filled_at"])

        logger.info(f"Order submitted successfully: order_id={order.order_id}, status={order.status.value}")

        return order

    async def get_order_status(self, order_id: str) -> Order:
        """주문 상태 조회."""
        logger.info(f"Fetching order status for {order_id}")

        data = await self._request("GET", f"/order/status/{order_id}")

        return Order(
            order_id=data["order_id"],
            account_number=data["account_number"],
            stock_code=data["stock_code"],
            order_type=OrderType[data["order_type"]],
            price_type=PriceType[data["price_type"]],
            quantity=data["quantity"],
            limit_price=Decimal(str(data["limit_price"])) if data.get("limit_price") else None,
            status=OrderStatus[data["status"]],
            filled_quantity=data.get("filled_quantity", 0),
            filled_price=Decimal(str(data["filled_price"])) if data.get("filled_price") else None,
            created_at=datetime.fromisoformat(data["created_at"]),
            submitted_at=datetime.fromisoformat(data["submitted_at"]) if data.get("submitted_at") else None,
            filled_at=datetime.fromisoformat(data["filled_at"]) if data.get("filled_at") else None
        )

    async def get_account(self) -> Account:
        """계좌 잔고 조회."""
        logger.info(f"Fetching account balance for {self.account_number}")

        data = await self._request("GET", f"/account/balance/{self.account_number}")

        return Account(
            account_number=data["account_number"],
            name=data["name"],
            cash_balance=Decimal(str(data["cash_balance"])),
            total_asset_value=Decimal(str(data["total_asset_value"])),
            total_pnl=Decimal(str(data.get("total_pnl", 0))),
            daily_pnl=Decimal(str(data.get("daily_pnl", 0))),
            daily_loss_limit=Decimal(str(data.get("daily_loss_limit", 0))),
            updated_at=datetime.now(tz=KST)
        )

    async def get_positions(self) -> list[Position]:
        """보유 종목 조회."""
        logger.info(f"Fetching positions for {self.account_number}")

        data = await self._request("GET", f"/account/positions/{self.account_number}")

        positions = []
        for item in data.get("positions", []):
            position = Position(
                account_number=self.account_number,
                stock_code=item["stock_code"],
                quantity=item["quantity"],
                average_buy_price=Decimal(str(item["average_buy_price"])),
                current_price=Decimal(str(item["current_price"])),
                opened_at=datetime.fromisoformat(item["opened_at"]),
                updated_at=datetime.now(tz=KST)
            )
            positions.append(position)

        return positions
