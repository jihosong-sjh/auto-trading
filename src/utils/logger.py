"""로깅 설정 모듈.

이 모듈은 시스템 전체에서 사용할 로깅 설정을 제공합니다.
Google Style Docstring을 사용하며, logging 모듈을 기반으로 합니다.
"""

import logging
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


class KSTFormatter(logging.Formatter):
    """KST 타임존을 사용하는 로그 포맷터."""

    def formatTime(self, record, datefmt=None):
        """로그 레코드의 시간을 KST로 포맷팅.

        Args:
            record: 로그 레코드.
            datefmt: 날짜 포맷 문자열 (선택 사항).

        Returns:
            KST 기준으로 포맷팅된 시간 문자열.
        """
        dt = datetime.fromtimestamp(record.created, tz=KST)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat()


def setup_logger(
    name: str,
    log_level: str = "INFO",
    log_file: Optional[Path] = None,
    console_output: bool = True,
) -> logging.Logger:
    """로거를 설정하고 반환.

    Args:
        name: 로거 이름 (보통 __name__ 사용).
        log_level: 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: 로그 파일 경로 (선택 사항). 지정 시 파일에도 로그 기록.
        console_output: 콘솔 출력 여부.

    Returns:
        설정된 로거 인스턴스.

    Example:
        >>> logger = setup_logger(__name__, log_level="DEBUG")
        >>> logger.info("시스템 시작")
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper()))

    # 기존 핸들러 제거 (중복 방지)
    logger.handlers.clear()

    # 로그 포맷 설정
    log_format = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    formatter = KSTFormatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")

    # 콘솔 핸들러
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # 파일 핸들러
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # 로거 전파 방지 (루트 로거와 중복 방지)
    logger.propagate = False

    return logger


def get_logger(name: str) -> logging.Logger:
    """기존 로거를 가져오거나 기본 설정으로 새 로거 생성.

    Args:
        name: 로거 이름.

    Returns:
        로거 인스턴스.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.warning("경고 메시지")
    """
    logger = logging.getLogger(name)
    
    # 이미 설정된 로거면 그대로 반환
    if logger.handlers:
        return logger
    
    # 설정되지 않은 로거면 기본 설정 적용
    return setup_logger(name)


def log_order_execution(
    logger: logging.Logger,
    order_id: str,
    stock_code: str,
    order_type: str,
    quantity: int,
    price: str,
    status: str,
) -> None:
    """주문 실행 로그를 기록.

    주문 실행과 관련된 중요 정보를 INFO 레벨로 기록합니다.

    Args:
        logger: 로거 인스턴스.
        order_id: 주문 ID.
        stock_code: 종목 코드.
        order_type: 주문 유형 (BUY/SELL).
        quantity: 주문 수량.
        price: 주문 가격.
        status: 주문 상태.

    Example:
        >>> logger = get_logger(__name__)
        >>> log_order_execution(
        ...     logger, "order-123", "005930", "BUY", 100, "72000", "FILLED"
        ... )
    """
    logger.info(
        f"[ORDER] ID={order_id} | Stock={stock_code} | Type={order_type} | "
        f"Qty={quantity} | Price={price} | Status={status}"
    )


def log_strategy_signal(
    logger: logging.Logger,
    strategy_name: str,
    stock_code: str,
    signal_type: str,
    reason: str,
) -> None:
    """전략 시그널 로그를 기록.

    전략이 매수/매도 시그널을 생성할 때 기록합니다.

    Args:
        logger: 로거 인스턴스.
        strategy_name: 전략 이름.
        stock_code: 종목 코드.
        signal_type: 시그널 유형 (BUY/SELL).
        reason: 시그널 발생 이유.

    Example:
        >>> logger = get_logger(__name__)
        >>> log_strategy_signal(
        ...     logger, "Golden Cross", "005930", "BUY", "SMA(5) crossed above SMA(20)"
        ... )
    """
    logger.info(
        f"[SIGNAL] Strategy={strategy_name} | Stock={stock_code} | "
        f"Type={signal_type} | Reason={reason}"
    )


def log_error_with_context(
    logger: logging.Logger,
    error_message: str,
    context: dict,
    exc_info: bool = True,
) -> None:
    """에러 로그를 컨텍스트와 함께 기록.

    Args:
        logger: 로거 인스턴스.
        error_message: 에러 메시지.
        context: 에러 발생 시 컨텍스트 정보.
        exc_info: 예외 트레이스백 포함 여부.

    Example:
        >>> logger = get_logger(__name__)
        >>> try:
        ...     result = 1 / 0
        ... except Exception as e:
        ...     log_error_with_context(
        ...         logger, "Division by zero", {"operation": "divide", "value": 1}
        ...     )
    """
    context_str = " | ".join([f"{k}={v}" for k, v in context.items()])
    logger.error(f"[ERROR] {error_message} | Context: {context_str}", exc_info=exc_info)
