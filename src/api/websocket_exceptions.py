"""WebSocket API 예외 클래스."""

from .exceptions import KiwoomAPIError


class WebSocketError(KiwoomAPIError):
    """WebSocket 관련 기본 예외 클래스."""

    pass


class WebSocketConnectionError(WebSocketError):
    """WebSocket 연결 실패 예외."""

    pass


class WebSocketAuthError(WebSocketError):
    """WebSocket 인증 실패 예외 (토큰 만료/무효)."""

    pass


class WebSocketSubscriptionError(WebSocketError):
    """실시간 시세 등록/해제 실패 예외."""

    pass


class WebSocketMessageError(WebSocketError):
    """메시지 파싱 오류 예외."""

    pass


class WebSocketReconnectError(WebSocketError):
    """재연결 실패 예외."""

    pass
