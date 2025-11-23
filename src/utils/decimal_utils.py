"""Decimal 계산 헬퍼 함수.

부동소수점 오차를 방지하기 위한 Decimal 기반 금융 계산 유틸리티를 제공합니다.
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext
from typing import Union

# Decimal 정밀도 설정 (소수점 10자리)
getcontext().prec = 10


def to_decimal(value: Union[int, float, str, Decimal]) -> Decimal:
    """다양한 타입을 Decimal로 변환.

    Args:
        value: 변환할 값 (int, float, str, Decimal).

    Returns:
        Decimal 객체.

    Example:
        >>> to_decimal(72000)
        Decimal('72000')
        >>> to_decimal("72000.50")
        Decimal('72000.50')
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def safe_divide(numerator: Decimal, denominator: Decimal, default: Decimal = Decimal("0")) -> Decimal:
    """안전한 나눗셈 (0으로 나누기 방지).

    Args:
        numerator: 분자.
        denominator: 분모.
        default: 분모가 0일 때 반환할 기본값.

    Returns:
        나눗셈 결과 또는 기본값.

    Example:
        >>> safe_divide(Decimal("100"), Decimal("0"))
        Decimal('0')
        >>> safe_divide(Decimal("100"), Decimal("10"))
        Decimal('10')
    """
    if denominator == 0:
        return default
    return numerator / denominator


def round_decimal(value: Decimal, decimal_places: int = 2) -> Decimal:
    """Decimal을 지정된 소수점 자리에서 반올림.

    Args:
        value: 반올림할 값.
        decimal_places: 소수점 자리수.

    Returns:
        반올림된 Decimal 값.

    Example:
        >>> round_decimal(Decimal("72000.4567"), 2)
        Decimal('72000.46')
    """
    quantize_str = "0." + "0" * decimal_places
    return value.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)


def calculate_profit_loss(
    quantity: int,
    buy_price: Decimal,
    sell_price: Decimal
) -> Decimal:
    """실현 손익 계산.

    Args:
        quantity: 거래 수량.
        buy_price: 평균 매수가.
        sell_price: 매도가.

    Returns:
        실현 손익 (양수: 수익, 음수: 손실).

    Example:
        >>> calculate_profit_loss(100, Decimal("70000"), Decimal("72000"))
        Decimal('200000')
    """
    return (sell_price - buy_price) * quantity


def calculate_return_rate(buy_price: Decimal, sell_price: Decimal) -> Decimal:
    """수익률 계산.

    Args:
        buy_price: 매수가.
        sell_price: 매도가.

    Returns:
        수익률 (0.05 = 5%, -0.03 = -3%).

    Example:
        >>> calculate_return_rate(Decimal("70000"), Decimal("73500"))
        Decimal('0.05')
    """
    if buy_price == 0:
        return Decimal("0")
    return (sell_price - buy_price) / buy_price


def calculate_average_price(
    existing_quantity: int,
    existing_avg_price: Decimal,
    additional_quantity: int,
    additional_price: Decimal
) -> Decimal:
    """추가 매수 시 평균 매수가 재계산.

    Args:
        existing_quantity: 기존 보유 수량.
        existing_avg_price: 기존 평균 매수가.
        additional_quantity: 추가 매수 수량.
        additional_price: 추가 매수가.

    Returns:
        새로운 평균 매수가.

    Example:
        >>> calculate_average_price(100, Decimal("70000"), 50, Decimal("72000"))
        Decimal('70666.67')
    """
    total_cost = (existing_avg_price * existing_quantity) + (additional_price * additional_quantity)
    total_quantity = existing_quantity + additional_quantity
    
    if total_quantity == 0:
        return Decimal("0")
    
    avg_price = total_cost / total_quantity
    return round_decimal(avg_price, 2)


def calculate_position_value(quantity: int, current_price: Decimal) -> Decimal:
    """포지션 평가액 계산.

    Args:
        quantity: 보유 수량.
        current_price: 현재가.

    Returns:
        평가액 (현재가 × 수량).

    Example:
        >>> calculate_position_value(100, Decimal("72000"))
        Decimal('7200000')
    """
    return current_price * quantity


def calculate_unrealized_pnl(
    quantity: int,
    average_buy_price: Decimal,
    current_price: Decimal
) -> Decimal:
    """미실현 손익 계산.

    Args:
        quantity: 보유 수량.
        average_buy_price: 평균 매수가.
        current_price: 현재가.

    Returns:
        미실현 손익 (양수: 수익, 음수: 손실).

    Example:
        >>> calculate_unrealized_pnl(100, Decimal("70000"), Decimal("72000"))
        Decimal('200000')
    """
    return (current_price - average_buy_price) * quantity


def calculate_percentage(part: Decimal, total: Decimal) -> Decimal:
    """비율 계산 (퍼센트).

    Args:
        part: 부분 값.
        total: 전체 값.

    Returns:
        비율 (0 ~ 1.0). 0.3 = 30%.

    Example:
        >>> calculate_percentage(Decimal("3000000"), Decimal("10000000"))
        Decimal('0.3')
    """
    if total == 0:
        return Decimal("0")
    return part / total


def is_price_within_range(
    current_price: Decimal,
    target_price: Decimal,
    tolerance_percent: Decimal = Decimal("0.01")
) -> bool:
    """현재가가 목표가의 허용 범위 내에 있는지 확인.

    Args:
        current_price: 현재가.
        target_price: 목표가.
        tolerance_percent: 허용 오차 비율 (기본값 1%).

    Returns:
        허용 범위 내에 있으면 True.

    Example:
        >>> is_price_within_range(Decimal("72000"), Decimal("72500"), Decimal("0.01"))
        True
    """
    if target_price == 0:
        return False
    
    diff = abs(current_price - target_price)
    diff_percent = diff / target_price
    
    return diff_percent <= tolerance_percent


def format_krw(amount: Decimal) -> str:
    """Decimal 금액을 한국 원화 형식으로 포맷.

    Args:
        amount: 금액.

    Returns:
        포맷팅된 문자열 (예: "7,200,000원").

    Example:
        >>> format_krw(Decimal("7200000"))
        '7,200,000원'
    """
    # 소수점 제거 (원화는 정수 단위)
    amount_int = int(amount)
    formatted = f"{amount_int:,}"
    return f"{formatted}원"


def format_percent(rate: Decimal, decimal_places: int = 2) -> str:
    """비율을 퍼센트 형식으로 포맷.

    Args:
        rate: 비율 (0.05 = 5%).
        decimal_places: 소수점 자리수.

    Returns:
        포맷팅된 문자열 (예: "5.00%").

    Example:
        >>> format_percent(Decimal("0.05"))
        '5.00%'
        >>> format_percent(Decimal("-0.03"))
        '-3.00%'
    """
    percent = rate * 100
    rounded = round_decimal(percent, decimal_places)
    return f"{rounded}%"
