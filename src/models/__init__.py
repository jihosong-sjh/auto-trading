"""데이터 모델 패키지.

이 패키지는 키움증권 자동매매 시스템의 모든 핵심 엔티티와 Enum을 정의합니다.
"""

from enum import Enum


class OrderType(str, Enum):
    """주문 유형.

    Attributes:
        BUY: 매수 주문.
        SELL: 매도 주문.
    """

    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    """주문 상태.

    Attributes:
        PENDING: 주문 생성됨, 아직 API로 전송되지 않음.
        SUBMITTED: 주문이 브로커 API로 제출됨.
        PARTIALLY_FILLED: 주문이 부분 체결됨.
        FILLED: 주문이 완전 체결됨.
        CANCELLED: 사용자 또는 시스템에 의해 주문이 취소됨.
        REJECTED: 브로커에 의해 주문이 거부됨.
        FAILED: 시스템 오류로 인해 주문이 실패함.
    """

    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class PriceType(str, Enum):
    """주문 가격 유형.

    Attributes:
        MARKET: 시장가 주문 (즉시 현재가로 체결).
        LIMIT: 지정가 주문 (특정 가격 이상/이하에서만 체결).
    """

    MARKET = "MARKET"
    LIMIT = "LIMIT"


class MarketType(str, Enum):
    """주식 시장 구분.

    Attributes:
        KOSPI: 코스피 시장.
        KOSDAQ: 코스닥 시장.
    """

    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"


class ChartInterval(str, Enum):
    """차트 데이터 주기.

    Attributes:
        TICK: 체결 데이터.
        MIN_1: 1분봉.
        MIN_5: 5분봉.
        MIN_30: 30분봉.
        HOUR_1: 1시간봉.
        DAY: 일봉.
        WEEK: 주봉.
        MONTH: 월봉.
    """

    TICK = "TICK"
    MIN_1 = "MIN_1"
    MIN_5 = "MIN_5"
    MIN_30 = "MIN_30"
    HOUR_1 = "HOUR_1"
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"


class SystemMode(str, Enum):
    """시스템 운영 모드.

    Attributes:
        STARTING: 시스템 시작 중.
        RUNNING: 시스템 정상 작동 중.
        PAUSED: 사용자에 의해 일시 중지됨.
        ERROR: 시스템 오류 발생.
        SHUTDOWN: 시스템 종료 중.
        BACKTEST: 백테스트 모드로 실행 중.
    """

    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    SHUTDOWN = "SHUTDOWN"
    BACKTEST = "BACKTEST"


class NotificationType(str, Enum):
    """알림 유형.

    Attributes:
        ORDER_FILLED: 주문 체결 알림.
        ERROR: 오류 경고 알림.
        DAILY_REPORT: 일일 거래 요약 보고서.
        SYSTEM_STATUS: 시스템 상태 변경 알림.
        RISK_ALERT: 위험 관리 경고 (예: 일일 손실 한도).
    """

    ORDER_FILLED = "ORDER_FILLED"
    ERROR = "ERROR"
    DAILY_REPORT = "DAILY_REPORT"
    SYSTEM_STATUS = "SYSTEM_STATUS"
    RISK_ALERT = "RISK_ALERT"


class MarketPhase(str, Enum):
    """장 운영 시간대.

    Attributes:
        PRE_MARKET: 장 시작 전 (09:00 이전).
        OPENING: 장 시작 (09:00-09:05).
        REGULAR: 정규 장 (09:05-15:20).
        CLOSING_SOON: 장 마감 임박 (15:20-15:30).
        CLOSED: 장 마감 (15:30 이후).
        AFTER_HOURS: 시간외 거래.
    """

    PRE_MARKET = "PRE_MARKET"
    OPENING = "OPENING"
    REGULAR = "REGULAR"
    CLOSING_SOON = "CLOSING_SOON"
    CLOSED = "CLOSED"
    AFTER_HOURS = "AFTER_HOURS"


__all__ = [
    "OrderType",
    "OrderStatus",
    "PriceType",
    "MarketType",
    "ChartInterval",
    "SystemMode",
    "NotificationType",
    "MarketPhase",
]
