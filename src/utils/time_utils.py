"""시간대 처리 유틸리티.

KST 타임존 처리 및 장 운영 시간 체크 기능을 제공합니다.
"""

from datetime import datetime, time
from zoneinfo import ZoneInfo
from typing import Optional

# KST 타임존 (한국 표준시)
KST = ZoneInfo("Asia/Seoul")


def get_kst_now() -> datetime:
    """현재 KST 시간을 반환.

    Returns:
        현재 KST 시간 (타임존 정보 포함).

    Example:
        >>> now = get_kst_now()
        >>> print(now.tzinfo)
        Asia/Seoul
    """
    return datetime.now(tz=KST)


def to_kst(dt: datetime) -> datetime:
    """datetime 객체를 KST로 변환.

    Args:
        dt: 변환할 datetime 객체.

    Returns:
        KST로 변환된 datetime 객체.

    Example:
        >>> import datetime
        >>> utc_time = datetime.datetime.now(tz=datetime.timezone.utc)
        >>> kst_time = to_kst(utc_time)
    """
    return dt.astimezone(KST)


def is_market_open(current_time: Optional[datetime] = None) -> bool:
    """현재 시장이 열려 있는지 확인.

    한국 주식 시장 운영 시간: 09:00 ~ 15:30 (KST)

    Args:
        current_time: 확인할 시간 (기본값: 현재 KST 시간).

    Returns:
        시장이 열려 있으면 True, 아니면 False.

    Example:
        >>> from datetime import datetime
        >>> test_time = datetime(2025, 11, 22, 10, 30, 0, tzinfo=KST)
        >>> is_market_open(test_time)
        True
    """
    if current_time is None:
        current_time = get_kst_now()
    
    current_time_only = current_time.time()
    market_open = time(9, 0)
    market_close = time(15, 30)
    
    return market_open <= current_time_only < market_close


def is_in_regular_trading_hours(current_time: Optional[datetime] = None) -> bool:
    """정규 거래 시간대인지 확인.

    정규 거래 시간: 09:05 ~ 15:20 (KST)
    (개장 5분 후 ~ 종가 10분 전)

    Args:
        current_time: 확인할 시간 (기본값: 현재 KST 시간).

    Returns:
        정규 거래 시간대이면 True, 아니면 False.

    Example:
        >>> from datetime import datetime
        >>> test_time = datetime(2025, 11, 22, 15, 25, 0, tzinfo=KST)
        >>> is_in_regular_trading_hours(test_time)
        False
    """
    if current_time is None:
        current_time = get_kst_now()
    
    current_time_only = current_time.time()
    regular_start = time(9, 5)
    regular_end = time(15, 20)
    
    return regular_start <= current_time_only < regular_end


def is_market_opening(current_time: Optional[datetime] = None) -> bool:
    """시장 개장 시간대인지 확인.

    개장 시간: 09:00 ~ 09:05 (KST)

    Args:
        current_time: 확인할 시간 (기본값: 현재 KST 시간).

    Returns:
        개장 시간대이면 True, 아니면 False.

    Example:
        >>> from datetime import datetime
        >>> test_time = datetime(2025, 11, 22, 9, 2, 0, tzinfo=KST)
        >>> is_market_opening(test_time)
        True
    """
    if current_time is None:
        current_time = get_kst_now()
    
    current_time_only = current_time.time()
    opening_start = time(9, 0)
    opening_end = time(9, 5)
    
    return opening_start <= current_time_only < opening_end


def is_market_closing_soon(current_time: Optional[datetime] = None) -> bool:
    """시장 마감 임박 시간대인지 확인.

    마감 임박 시간: 15:20 ~ 15:30 (KST)

    Args:
        current_time: 확인할 시간 (기본값: 현재 KST 시간).

    Returns:
        마감 임박 시간대이면 True, 아니면 False.

    Example:
        >>> from datetime import datetime
        >>> test_time = datetime(2025, 11, 22, 15, 25, 0, tzinfo=KST)
        >>> is_market_closing_soon(test_time)
        True
    """
    if current_time is None:
        current_time = get_kst_now()
    
    current_time_only = current_time.time()
    closing_start = time(15, 20)
    closing_end = time(15, 30)
    
    return closing_start <= current_time_only < closing_end


def can_place_buy_order(current_time: Optional[datetime] = None) -> tuple[bool, Optional[str]]:
    """매수 주문 가능 여부 확인.

    규칙:
    - 시장이 열려 있어야 함
    - 마감 10분 전부터 신규 매수 차단

    Args:
        current_time: 확인할 시간 (기본값: 현재 KST 시간).

    Returns:
        (가능 여부, 불가능한 경우 사유) 튜플.

    Example:
        >>> from datetime import datetime
        >>> test_time = datetime(2025, 11, 22, 15, 25, 0, tzinfo=KST)
        >>> can_place_buy_order(test_time)
        (False, '...')
    """
    if current_time is None:
        current_time = get_kst_now()
    
    if not is_market_open(current_time):
        return False, "Market is closed"
    
    if is_market_closing_soon(current_time):
        return False, "Buy orders blocked 10 minutes before market close"
    
    return True, None


def can_place_sell_order(current_time: Optional[datetime] = None) -> tuple[bool, Optional[str]]:
    """매도 주문 가능 여부 확인.

    규칙:
    - 시장이 열려 있어야 함

    Args:
        current_time: 확인할 시간 (기본값: 현재 KST 시간).

    Returns:
        (가능 여부, 불가능한 경우 사유) 튜플.

    Example:
        >>> from datetime import datetime
        >>> test_time = datetime(2025, 11, 22, 10, 0, 0, tzinfo=KST)
        >>> can_place_sell_order(test_time)
        (True, None)
    """
    if current_time is None:
        current_time = get_kst_now()
    
    if not is_market_open(current_time):
        return False, "Market is closed"
    
    return True, None


def get_market_phase(current_time: Optional[datetime] = None) -> str:
    """현재 시장 운영 단계를 반환.

    Returns:
        시장 운영 단계 문자열:
        - "PRE_MARKET": 장 시작 전
        - "OPENING": 개장 시간
        - "REGULAR": 정규 거래 시간
        - "CLOSING_SOON": 마감 임박
        - "CLOSED": 장 마감 후

    Args:
        current_time: 확인할 시간 (기본값: 현재 KST 시간).

    Example:
        >>> from datetime import datetime
        >>> test_time = datetime(2025, 11, 22, 14, 0, 0, tzinfo=KST)
        >>> get_market_phase(test_time)
        'REGULAR'
    """
    if current_time is None:
        current_time = get_kst_now()
    
    current_time_only = current_time.time()
    
    if current_time_only < time(9, 0):
        return "PRE_MARKET"
    elif time(9, 0) <= current_time_only < time(9, 5):
        return "OPENING"
    elif time(9, 5) <= current_time_only < time(15, 20):
        return "REGULAR"
    elif time(15, 20) <= current_time_only < time(15, 30):
        return "CLOSING_SOON"
    else:
        return "CLOSED"


def seconds_until_market_open(current_time: Optional[datetime] = None) -> Optional[int]:
    """시장 개장까지 남은 시간(초) 계산.

    Args:
        current_time: 기준 시간 (기본값: 현재 KST 시간).

    Returns:
        개장까지 남은 시간(초). 이미 개장했거나 장 운영 중이면 None 반환.
    """
    if current_time is None:
        current_time = get_kst_now()
    
    if is_market_open(current_time):
        return None
    
    market_open_today = current_time.replace(hour=9, minute=0, second=0, microsecond=0)
    
    if current_time < market_open_today:
        delta = market_open_today - current_time
        return int(delta.total_seconds())
    
    from datetime import timedelta
    market_open_tomorrow = market_open_today + timedelta(days=1)
    delta = market_open_tomorrow - current_time
    return int(delta.total_seconds())


def seconds_until_market_close(current_time: Optional[datetime] = None) -> Optional[int]:
    """시장 마감까지 남은 시간(초) 계산.

    Args:
        current_time: 기준 시간 (기본값: 현재 KST 시간).

    Returns:
        마감까지 남은 시간(초). 이미 마감했으면 None 반환.
    """
    if current_time is None:
        current_time = get_kst_now()
    
    if not is_market_open(current_time):
        return None
    
    market_close_today = current_time.replace(hour=15, minute=30, second=0, microsecond=0)
    
    delta = market_close_today - current_time
    return int(delta.total_seconds())
