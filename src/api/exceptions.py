"""키움증권 API 예외 클래스."""

from typing import Any


class KiwoomAPIError(Exception):
    """키움증권 API 오류 기본 클래스."""

    def __init__(self, message: str, status_code: int | None = None, response_data: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data or {}


class InsufficientBalanceError(KiwoomAPIError):
    """예수금 부족 오류."""
    pass


class InvalidStockCodeError(KiwoomAPIError):
    """잘못된 종목 코드 오류."""
    pass


class APITimeoutError(KiwoomAPIError):
    """API 타임아웃 오류."""
    pass


class RateLimitExceededError(KiwoomAPIError):
    """Rate Limit 초과 오류."""
    pass
