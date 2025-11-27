"""WebSocket 데이터 변환 유틸리티.

키움증권 WebSocket API 응답을 내부 모델로 변환합니다.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from ..models import MarketType
from ..models.order_book import OrderBook, OrderBookLevel
from ..models.realtime_data import (
    BalanceUpdateData,
    OrderBookData,
    OrderExecutionData,
    TradeData,
)
from ..models.stock import Stock

KST = ZoneInfo("Asia/Seoul")


class WebSocketDataTransformer:
    """WebSocket 메시지를 내부 모델로 변환하는 클래스."""

    def __init__(self, stock_name_cache: Optional[Dict[str, str]] = None):
        """변환기 초기화.

        Args:
            stock_name_cache: 종목코드 -> 종목명 캐시 (선택).
        """
        self.stock_name_cache = stock_name_cache or {}

    def parse_price(self, price_str: str) -> Decimal:
        """가격 문자열을 Decimal로 변환.

        키움 API는 가격에 부호(+/-)가 포함되어 있습니다.
        절대값으로 변환합니다.

        Args:
            price_str: 가격 문자열 (예: '+20800', '-20800', '20800').

        Returns:
            절대값 Decimal.
        """
        if not price_str:
            return Decimal("0")
        try:
            # 부호 제거 후 절대값으로 변환
            cleaned = price_str.lstrip("+-")
            return Decimal(cleaned) if cleaned else Decimal("0")
        except InvalidOperation:
            return Decimal("0")

    def parse_int(self, value_str: str) -> int:
        """정수 문자열을 int로 변환.

        Args:
            value_str: 정수 문자열.

        Returns:
            정수 값.
        """
        if not value_str:
            return 0
        try:
            # 부호 제거 후 변환
            cleaned = value_str.lstrip("+-")
            return int(cleaned) if cleaned else 0
        except ValueError:
            return 0

    def parse_volume_with_sign(self, volume_str: str) -> tuple[int, str]:
        """거래량 문자열을 파싱 (부호 포함).

        Args:
            volume_str: 거래량 문자열 (예: '+82', '-150').

        Returns:
            (절대값, 부호) 튜플.
        """
        if not volume_str:
            return 0, "+"

        sign = "+"
        if volume_str.startswith("-"):
            sign = "-"
        elif volume_str.startswith("+"):
            sign = "+"

        try:
            value = abs(int(volume_str.lstrip("+-") or "0"))
            return value, sign
        except ValueError:
            return 0, "+"

    def parse_timestamp(self, time_str: str) -> datetime:
        """시간 문자열을 datetime으로 변환.

        Args:
            time_str: 시간 문자열 (예: '165208' = 16:52:08).

        Returns:
            KST datetime.
        """
        now = datetime.now(KST)
        if not time_str or len(time_str) < 6:
            return now

        try:
            hour = int(time_str[0:2])
            minute = int(time_str[2:4])
            second = int(time_str[4:6])
            return now.replace(hour=hour, minute=minute, second=second, microsecond=0)
        except (ValueError, IndexError):
            return now

    def parse_trade_data(self, item: str, values: Dict[str, Any]) -> TradeData:
        """0B (주식체결) 메시지를 TradeData로 변환.

        Args:
            item: 종목코드.
            values: 실시간 값 딕셔너리.

        Returns:
            TradeData 객체.
        """
        volume, volume_sign = self.parse_volume_with_sign(values.get("15", ""))

        return TradeData(
            stock_code=item,
            current_price=self.parse_price(values.get("10", "0")),
            price_change=self.parse_price(values.get("11", "0")),
            change_rate=Decimal(values.get("12", "0") or "0"),
            volume=volume,
            volume_sign=volume_sign,
            cumulative_volume=self.parse_int(values.get("13", "0")),
            cumulative_amount=Decimal(values.get("14", "0") or "0"),
            trade_strength=Decimal(values.get("228", "0") or "0"),
            best_ask=self.parse_price(values.get("27", "0")),
            best_bid=self.parse_price(values.get("28", "0")),
            open_price=self.parse_price(values.get("16", "0")),
            high_price=self.parse_price(values.get("17", "0")),
            low_price=self.parse_price(values.get("18", "0")),
            market_phase=values.get("290", "2"),
            timestamp=self.parse_timestamp(values.get("20", "")),
        )

    def parse_order_book_data(self, item: str, values: Dict[str, Any]) -> OrderBookData:
        """0D (주식호가잔량) 메시지를 OrderBookData로 변환.

        Args:
            item: 종목코드.
            values: 실시간 값 딕셔너리.

        Returns:
            OrderBookData 객체.
        """
        # 매도호가 (41~50), 매도수량 (61~70)
        ask_prices = [
            self.parse_price(values.get(str(41 + i), "0")) for i in range(10)
        ]
        ask_quantities = [
            self.parse_int(values.get(str(61 + i), "0")) for i in range(10)
        ]

        # 매수호가 (51~60), 매수수량 (71~80)
        bid_prices = [
            self.parse_price(values.get(str(51 + i), "0")) for i in range(10)
        ]
        bid_quantities = [
            self.parse_int(values.get(str(71 + i), "0")) for i in range(10)
        ]

        return OrderBookData(
            stock_code=item,
            ask_prices=ask_prices,
            ask_quantities=ask_quantities,
            bid_prices=bid_prices,
            bid_quantities=bid_quantities,
            total_ask_quantity=self.parse_int(values.get("121", "0")),
            total_bid_quantity=self.parse_int(values.get("125", "0")),
            expected_price=self.parse_price(values.get("23", "0")),
            expected_volume=self.parse_int(values.get("24", "0")),
            timestamp=self.parse_timestamp(values.get("21", "")),
        )

    def parse_order_execution_data(
        self, item: str, values: Dict[str, Any]
    ) -> OrderExecutionData:
        """00 (주문체결) 메시지를 OrderExecutionData로 변환.

        Args:
            item: 종목코드.
            values: 실시간 값 딕셔너리.

        Returns:
            OrderExecutionData 객체.
        """
        return OrderExecutionData(
            account_number=values.get("9201", ""),
            order_id=values.get("9203", ""),
            original_order_id=values.get("904", ""),
            stock_code=values.get("9001", item),
            stock_name=values.get("302", ""),
            order_status=values.get("913", ""),
            order_type=values.get("905", ""),
            trade_type=values.get("906", ""),
            side=values.get("907", ""),
            quantity=self.parse_int(values.get("900", "0")),
            price=self.parse_price(values.get("901", "0")),
            unfilled_quantity=self.parse_int(values.get("902", "0")),
            filled_amount=self.parse_price(values.get("903", "0")),
            filled_price=self.parse_price(values.get("910", "0")),
            filled_quantity=self.parse_int(values.get("911", "0")),
            unit_filled_price=self.parse_price(values.get("914", "0")),
            unit_filled_quantity=self.parse_int(values.get("915", "0")),
            reject_reason=values.get("919", ""),
            current_price=self.parse_price(values.get("10", "0")),
            timestamp=self.parse_timestamp(values.get("908", "")),
        )

    def parse_balance_update_data(
        self, item: str, values: Dict[str, Any]
    ) -> BalanceUpdateData:
        """04 (잔고) 메시지를 BalanceUpdateData로 변환.

        Args:
            item: 종목코드.
            values: 실시간 값 딕셔너리.

        Returns:
            BalanceUpdateData 객체.
        """
        return BalanceUpdateData(
            account_number=values.get("9201", ""),
            stock_code=values.get("9001", item),
            stock_name=values.get("302", ""),
            action=values.get("843", "I"),
            side=values.get("907", ""),
            holding_quantity=self.parse_int(values.get("930", "0")),
            average_price=self.parse_price(values.get("931", "0")),
            total_purchase_amount=self.parse_price(values.get("932", "0")),
            orderable_quantity=self.parse_int(values.get("933", "0")),
            current_price=self.parse_price(values.get("10", "0")),
            best_ask=self.parse_price(values.get("27", "0")),
            best_bid=self.parse_price(values.get("28", "0")),
            realized_pnl=self.parse_price(values.get("990", "0")),
            realized_pnl_rate=Decimal(values.get("991", "0") or "0"),
            timestamp=self.parse_timestamp(values.get("20", "")),
        )

    def trade_to_stock(self, trade: TradeData) -> Stock:
        """TradeData를 Stock 모델로 변환 (market_data_queue용).

        Args:
            trade: 체결 데이터.

        Returns:
            Stock 객체.
        """
        stock_name = self.stock_name_cache.get(
            trade.stock_code, f"Stock_{trade.stock_code}"
        )

        return Stock(
            stock_code=trade.stock_code,
            stock_name=stock_name,
            market=self._infer_market(trade.stock_code),
            current_price=trade.current_price,
            open_price=trade.open_price if trade.open_price > 0 else None,
            high_price=trade.high_price if trade.high_price > 0 else None,
            low_price=trade.low_price if trade.low_price > 0 else None,
            volume=trade.cumulative_volume,
            change=trade.price_change,
            change_rate=trade.change_rate,
            updated_at=trade.timestamp,
        )

    def order_book_data_to_model(self, data: OrderBookData) -> OrderBook:
        """OrderBookData를 OrderBook 모델로 변환.

        Args:
            data: 호가 데이터.

        Returns:
            OrderBook 객체.
        """
        # 매도 호가 레벨 (0이 아닌 것만)
        ask_levels = [
            OrderBookLevel(price=price, quantity=qty)
            for price, qty in zip(data.ask_prices, data.ask_quantities)
            if price > 0
        ]

        # 매수 호가 레벨 (0이 아닌 것만)
        bid_levels = [
            OrderBookLevel(price=price, quantity=qty)
            for price, qty in zip(data.bid_prices, data.bid_quantities)
            if price > 0
        ]

        return OrderBook(
            stock_code=data.stock_code,
            ask_levels=ask_levels,
            bid_levels=bid_levels,
            total_ask_quantity=data.total_ask_quantity,
            total_bid_quantity=data.total_bid_quantity,
            timestamp=data.timestamp,
        )

    def _infer_market(self, stock_code: str) -> MarketType:
        """종목코드에서 시장 추론.

        Args:
            stock_code: 6자리 종목코드.

        Returns:
            시장 타입 (KOSPI/KOSDAQ).
        """
        try:
            code_num = int(stock_code)
            return MarketType.KOSPI if code_num < 100000 else MarketType.KOSDAQ
        except ValueError:
            return MarketType.KOSPI

    def update_stock_name_cache(self, stock_code: str, stock_name: str) -> None:
        """종목명 캐시 업데이트.

        Args:
            stock_code: 종목코드.
            stock_name: 종목명.
        """
        self.stock_name_cache[stock_code] = stock_name
