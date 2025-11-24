"""일일 거래 리포트 생성기.

이 모듈은 일일 거래 내역, 손익, 승률 등을 계산하여
사용자에게 전송할 리포트를 생성합니다.
"""

from decimal import Decimal
from datetime import datetime, time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from ..models.order import Order, OrderStatus, OrderType
from ..models.position import Position
from ..models.account import Account
from ..repositories.order_repository import OrderRepository
from ..utils.logger import get_logger

KST = ZoneInfo("Asia/Seoul")
logger = get_logger(__name__)


@dataclass
class DailyReportData:
    """일일 리포트 데이터.

    Attributes:
        report_date: 리포트 날짜 (KST)
        total_orders: 총 주문 수
        buy_orders: 매수 주문 수
        sell_orders: 매도 주문 수
        filled_orders: 체결된 주문 수
        cancelled_orders: 취소된 주문 수
        total_buy_amount: 총 매수 금액
        total_sell_amount: 총 매도 금액
        realized_pnl: 실현 손익
        unrealized_pnl: 미실현 손익
        total_pnl: 총 손익 (실현 + 미실현)
        win_count: 수익 거래 수
        loss_count: 손실 거래 수
        win_rate: 승률 (%)
        active_positions: 활성 포지션 수
        cash_balance: 현금 잔고
        total_asset_value: 총 평가액
        return_rate: 수익률 (%)
    """
    report_date: datetime
    total_orders: int
    buy_orders: int
    sell_orders: int
    filled_orders: int
    cancelled_orders: int
    total_buy_amount: Decimal
    total_sell_amount: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    win_count: int
    loss_count: int
    win_rate: Decimal
    active_positions: int
    cash_balance: Decimal
    total_asset_value: Decimal
    return_rate: Decimal


class DailyReportGenerator:
    """일일 거래 리포트 생성기.

    당일 거래 내역, 손익, 승률 등을 계산하여 리포트를 생성합니다.
    """

    def __init__(
        self,
        order_repository: OrderRepository,
        initial_balance: Optional[Decimal] = None
    ):
        """DailyReportGenerator 초기화.

        Args:
            order_repository: 주문 저장소
            initial_balance: 초기 자금 (수익률 계산용)
        """
        self.order_repository = order_repository
        self.initial_balance = initial_balance
        logger.info("DailyReportGenerator initialized")

    async def generate_daily_report(
        self,
        account: Account,
        positions: List[Position],
        target_date: Optional[datetime] = None
    ) -> DailyReportData:
        """일일 리포트 생성.

        Args:
            account: 계좌 정보
            positions: 현재 포지션 목록
            target_date: 리포트 대상 날짜 (기본값: 오늘)

        Returns:
            생성된 일일 리포트 데이터
        """
        if target_date is None:
            target_date = datetime.now(tz=KST)

        # 날짜의 시작과 끝 시간 설정
        start_of_day = datetime.combine(
            target_date.date(),
            time(0, 0, 0),
            tzinfo=KST
        )
        end_of_day = datetime.combine(
            target_date.date(),
            time(23, 59, 59),
            tzinfo=KST
        )

        logger.info(
            f"Generating daily report for {target_date.date()}"
        )

        # 당일 주문 조회
        daily_orders = await self.order_repository.get_orders_by_date_range(
            account.account_number,
            start_of_day,
            end_of_day
        )

        # 주문 통계 계산
        total_orders = len(daily_orders)
        buy_orders = sum(1 for o in daily_orders if o.order_type == OrderType.BUY)
        sell_orders = sum(1 for o in daily_orders if o.order_type == OrderType.SELL)
        filled_orders = sum(
            1 for o in daily_orders if o.status == OrderStatus.FILLED
        )
        cancelled_orders = sum(
            1 for o in daily_orders if o.status == OrderStatus.CANCELLED
        )

        # 매수/매도 금액 계산
        total_buy_amount = sum(
            o.calculate_total_cost()
            for o in daily_orders
            if o.order_type == OrderType.BUY and o.status == OrderStatus.FILLED
        )

        total_sell_amount = sum(
            o.calculate_total_cost()
            for o in daily_orders
            if o.order_type == OrderType.SELL and o.status == OrderStatus.FILLED
        )

        # 실현 손익 계산 (매도 금액 - 해당 포지션의 매수 원가)
        realized_pnl = await self._calculate_realized_pnl(daily_orders)

        # 미실현 손익 계산
        unrealized_pnl = sum(
            position.unrealized_pnl for position in positions
        )

        # 총 손익
        total_pnl = realized_pnl + unrealized_pnl

        # 승률 계산
        win_count, loss_count = await self._calculate_win_loss_count(daily_orders)
        win_rate = self._calculate_win_rate(win_count, loss_count)

        # 수익률 계산
        return_rate = self._calculate_return_rate(
            account.total_asset_value,
            self.initial_balance
        )

        report_data = DailyReportData(
            report_date=target_date,
            total_orders=total_orders,
            buy_orders=buy_orders,
            sell_orders=sell_orders,
            filled_orders=filled_orders,
            cancelled_orders=cancelled_orders,
            total_buy_amount=total_buy_amount,
            total_sell_amount=total_sell_amount,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_pnl=total_pnl,
            win_count=win_count,
            loss_count=loss_count,
            win_rate=win_rate,
            active_positions=len(positions),
            cash_balance=account.cash_balance,
            total_asset_value=account.total_asset_value,
            return_rate=return_rate
        )

        logger.info(
            f"Daily report generated: {total_orders} orders, "
            f"PnL: {total_pnl:,.0f}원, Win rate: {win_rate:.2f}%"
        )

        return report_data

    async def _calculate_realized_pnl(self, orders: List[Order]) -> Decimal:
        """실현 손익 계산.

        매도 주문에서 발생한 손익을 계산합니다.
        간단한 구현: 매도금액 - 매수금액

        Args:
            orders: 주문 목록

        Returns:
            실현 손익
        """
        # 체결된 매도 주문의 금액 합계
        sell_amount = sum(
            o.calculate_total_cost()
            for o in orders
            if o.order_type == OrderType.SELL and o.status == OrderStatus.FILLED
        )

        # 체결된 매수 주문의 금액 합계
        buy_amount = sum(
            o.calculate_total_cost()
            for o in orders
            if o.order_type == OrderType.BUY and o.status == OrderStatus.FILLED
        )

        # 실현 손익 = 매도 금액 - 매수 금액
        return sell_amount - buy_amount

    async def _calculate_win_loss_count(
        self,
        orders: List[Order]
    ) -> tuple[int, int]:
        """승리/패배 거래 수 계산.

        매도 주문을 기준으로 수익/손실 거래를 카운트합니다.

        Args:
            orders: 주문 목록

        Returns:
            (승리 거래 수, 패배 거래 수)
        """
        sell_orders = [
            o for o in orders
            if o.order_type == OrderType.SELL and o.status == OrderStatus.FILLED
        ]

        if not sell_orders:
            return 0, 0

        # 종목별로 매수/매도 주문을 그룹화하여 손익 계산
        # 간단한 구현: 각 매도 주문의 체결가와 평균 매수가를 비교
        # (실제로는 포지션 히스토리를 사용해야 하지만, 여기서는 단순화)

        # 매수 주문으로부터 종목별 평균 매수가 계산
        stock_buy_prices: Dict[str, Decimal] = {}
        for order in orders:
            if order.order_type == OrderType.BUY and order.status == OrderStatus.FILLED:
                if order.filled_price:
                    stock_buy_prices[order.stock_code] = order.filled_price

        win_count = 0
        loss_count = 0

        for sell_order in sell_orders:
            if sell_order.stock_code in stock_buy_prices:
                buy_price = stock_buy_prices[sell_order.stock_code]
                sell_price = sell_order.filled_price or Decimal("0")

                if sell_price > buy_price:
                    win_count += 1
                elif sell_price < buy_price:
                    loss_count += 1
                # 동일 가격은 카운트하지 않음

        return win_count, loss_count

    def _calculate_win_rate(self, win_count: int, loss_count: int) -> Decimal:
        """승률 계산.

        Args:
            win_count: 승리 거래 수
            loss_count: 패배 거래 수

        Returns:
            승률 (0-100)
        """
        total_trades = win_count + loss_count
        if total_trades == 0:
            return Decimal("0")

        return (Decimal(win_count) / Decimal(total_trades)) * Decimal("100")

    def _calculate_return_rate(
        self,
        current_value: Decimal,
        initial_value: Optional[Decimal]
    ) -> Decimal:
        """수익률 계산.

        Args:
            current_value: 현재 총 평가액
            initial_value: 초기 자금

        Returns:
            수익률 (%)
        """
        if initial_value is None or initial_value == 0:
            return Decimal("0")

        return ((current_value - initial_value) / initial_value) * Decimal("100")

    def format_report_text(self, report_data: DailyReportData) -> str:
        """리포트를 텍스트 형식으로 포맷팅.

        Args:
            report_data: 리포트 데이터

        Returns:
            포맷팅된 리포트 텍스트
        """
        lines = [
            f"=== {report_data.report_date.strftime('%Y-%m-%d')} Daily Trading Report ===",
            "",
            "[Order Statistics]",
            f"Total Orders: {report_data.total_orders}",
            f"  - Buy: {report_data.buy_orders}",
            f"  - Sell: {report_data.sell_orders}",
            f"  - Filled: {report_data.filled_orders}",
            f"  - Cancelled: {report_data.cancelled_orders}",
            "",
            "[Trading Amount]",
            f"Total Buy Amount: {report_data.total_buy_amount:,.0f} KRW",
            f"Total Sell Amount: {report_data.total_sell_amount:,.0f} KRW",
            "",
            "[PnL Summary]",
            f"Realized PnL: {report_data.realized_pnl:+,.0f} KRW",
            f"Unrealized PnL: {report_data.unrealized_pnl:+,.0f} KRW",
            f"Total PnL: {report_data.total_pnl:+,.0f} KRW",
            "",
            "[Performance]",
            f"Win Trades: {report_data.win_count}",
            f"Loss Trades: {report_data.loss_count}",
            f"Win Rate: {report_data.win_rate:.2f}%",
            f"Return Rate: {report_data.return_rate:+.2f}%",
            "",
            "[Account Status]",
            f"Active Positions: {report_data.active_positions}",
            f"Cash Balance: {report_data.cash_balance:,.0f} KRW",
            f"Total Asset Value: {report_data.total_asset_value:,.0f} KRW",
            "",
            "========================================"
        ]

        return "\n".join(lines)

    def format_report_html(self, report_data: DailyReportData) -> str:
        """리포트를 HTML 형식으로 포맷팅.

        Args:
            report_data: 리포트 데이터

        Returns:
            포맷팅된 HTML 리포트
        """
        pnl_color = "green" if report_data.total_pnl >= 0 else "red"
        return_color = "green" if report_data.return_rate >= 0 else "red"

        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
                h1 {{ color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }}
                h2 {{ color: #555; margin-top: 20px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
                th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background-color: #f2f2f2; }}
                .positive {{ color: green; }}
                .negative {{ color: red; }}
                .neutral {{ color: gray; }}
            </style>
        </head>
        <body>
            <h1>{report_data.report_date.strftime('%Y-%m-%d')} Daily Trading Report</h1>

            <h2>Order Statistics</h2>
            <table>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>Total Orders</td><td>{report_data.total_orders}</td></tr>
                <tr><td>Buy Orders</td><td>{report_data.buy_orders}</td></tr>
                <tr><td>Sell Orders</td><td>{report_data.sell_orders}</td></tr>
                <tr><td>Filled Orders</td><td>{report_data.filled_orders}</td></tr>
                <tr><td>Cancelled Orders</td><td>{report_data.cancelled_orders}</td></tr>
            </table>

            <h2>Trading Amount</h2>
            <table>
                <tr><th>Type</th><th>Amount (KRW)</th></tr>
                <tr><td>Total Buy</td><td>{report_data.total_buy_amount:,.0f}</td></tr>
                <tr><td>Total Sell</td><td>{report_data.total_sell_amount:,.0f}</td></tr>
            </table>

            <h2>PnL Summary</h2>
            <table>
                <tr><th>Type</th><th>Amount (KRW)</th></tr>
                <tr><td>Realized PnL</td><td style="color: {pnl_color};">{report_data.realized_pnl:+,.0f}</td></tr>
                <tr><td>Unrealized PnL</td><td>{report_data.unrealized_pnl:+,.0f}</td></tr>
                <tr><td><strong>Total PnL</strong></td><td style="color: {pnl_color};"><strong>{report_data.total_pnl:+,.0f}</strong></td></tr>
            </table>

            <h2>Performance</h2>
            <table>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>Win Trades</td><td class="positive">{report_data.win_count}</td></tr>
                <tr><td>Loss Trades</td><td class="negative">{report_data.loss_count}</td></tr>
                <tr><td>Win Rate</td><td>{report_data.win_rate:.2f}%</td></tr>
                <tr><td>Return Rate</td><td style="color: {return_color};"><strong>{report_data.return_rate:+.2f}%</strong></td></tr>
            </table>

            <h2>Account Status</h2>
            <table>
                <tr><th>Item</th><th>Value</th></tr>
                <tr><td>Active Positions</td><td>{report_data.active_positions}</td></tr>
                <tr><td>Cash Balance</td><td>{report_data.cash_balance:,.0f} KRW</td></tr>
                <tr><td><strong>Total Asset Value</strong></td><td><strong>{report_data.total_asset_value:,.0f} KRW</strong></td></tr>
            </table>
        </body>
        </html>
        """

        return html
