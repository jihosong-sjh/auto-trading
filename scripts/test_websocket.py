#!/usr/bin/env python
"""WebSocket 연결 테스트 스크립트.

모의투자 서버에서 WebSocket 연결을 테스트합니다.
- 연결/해제 테스트
- 실시간 시세 등록/해제
- 0B(체결), 0D(호가) 데이터 수신 테스트
- 00(주문체결), 04(잔고) 알림 테스트

Usage:
    python scripts/test_websocket.py
    python scripts/test_websocket.py --stocks 005930,000660
    python scripts/test_websocket.py --timeout 30
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

# .env 파일 로드
load_dotenv(project_root / ".env")


async def test_websocket(
    stock_codes: list[str],
    timeout: int = 30,
    verbose: bool = False
):
    """WebSocket 연결 테스트 실행.

    Args:
        stock_codes: 테스트할 종목 코드 목록.
        timeout: 데이터 수신 대기 시간 (초).
        verbose: 상세 로깅 활성화.
    """
    from src.api.kiwoom_client import KiwoomClient
    from src.api.kiwoom_websocket import KiwoomWebSocketClient, RealTimeType
    from src.models.realtime_data import (
        TradeData,
        OrderBookData,
        OrderExecutionData,
        BalanceUpdateData,
    )

    # 통계
    stats = {
        "trade_count": 0,
        "order_book_count": 0,
        "order_execution_count": 0,
        "balance_update_count": 0,
        "errors": [],
    }

    # 콜백 함수 정의
    async def on_trade(data: TradeData):
        stats["trade_count"] += 1
        direction = "BUY" if data.is_buy_trade() else "SELL"
        print(
            f"[0B] {data.stock_code} | "
            f"Price: {data.current_price:>10,} ({data.change_rate:+.2f}%) | "
            f"Vol: {data.volume:>6} ({direction}) | "
            f"Total: {data.cumulative_volume:,}"
        )

    async def on_order_book(data: OrderBookData):
        stats["order_book_count"] += 1
        imbalance = data.get_imbalance_ratio()
        best_ask = data.ask_prices[0] if data.ask_prices else 0
        best_bid = data.bid_prices[0] if data.bid_prices else 0
        print(
            f"[0D] {data.stock_code} | "
            f"Ask: {best_ask:>10,} ({data.total_ask_quantity:>8,}) | "
            f"Bid: {best_bid:>10,} ({data.total_bid_quantity:>8,}) | "
            f"Imbalance: {imbalance:+.2%}"
        )

    async def on_order_execution(data: OrderExecutionData):
        stats["order_execution_count"] += 1
        print(
            f"[00] Order {data.order_id} | "
            f"{data.stock_code} | "
            f"Status: {data.order_status} | "
            f"Filled: {data.filled_quantity}/{data.quantity} @ {data.filled_price:,}"
        )

    async def on_balance_update(data: BalanceUpdateData):
        stats["balance_update_count"] += 1
        action = "NEW" if data.is_new_position() else "CLOSED" if data.is_position_closed() else "UPDATE"
        print(
            f"[04] Balance {action} | "
            f"{data.stock_code} | "
            f"Qty: {data.holding_quantity} @ {data.average_price:,} | "
            f"PnL: {data.realized_pnl:+,.0f}"
        )

    async def on_connect():
        print("\n[Connected] WebSocket connection established")

    async def on_disconnect(reason: str):
        print(f"\n[Disconnected] {reason}")

    async def on_error(error: Exception):
        stats["errors"].append(str(error))
        print(f"\n[Error] {error}")

    # 환경 변수 확인
    api_key = os.getenv("KIWOOM_API_KEY")
    api_secret = os.getenv("KIWOOM_API_SECRET")
    account_number = os.getenv("KIWOOM_ACCOUNT_NUMBER")

    if not all([api_key, api_secret, account_number]):
        print("[ERROR] Missing environment variables:")
        print("  - KIWOOM_API_KEY")
        print("  - KIWOOM_API_SECRET")
        print("  - KIWOOM_ACCOUNT_NUMBER")
        print("\nSet them in .env file or environment")
        return False

    print("=" * 70)
    print("WebSocket Connection Test")
    print("=" * 70)
    print(f"Stock codes: {stock_codes}")
    print(f"Timeout: {timeout} seconds")
    print(f"Mode: Mock (Simulation)")
    print("=" * 70)

    try:
        # REST API 클라이언트 생성 (토큰 관리용)
        print("\n[1/5] Creating REST API client...")
        async with KiwoomClient(
            api_key=api_key,
            api_secret=api_secret,
            account_number=account_number,
            base_url="https://mockapi.kiwoom.com:10000",  # 모의투자
            max_requests_per_second=5
        ) as client:
            print("[OK] REST API client connected")

            # WebSocket 클라이언트 생성
            print("\n[2/5] Creating WebSocket client...")
            ws_client = KiwoomWebSocketClient(
                kiwoom_client=client,
                is_mock=True,  # 모의투자
                auto_reconnect=False,  # 테스트에서는 자동 재연결 비활성화
                heartbeat_interval=30.0,
            )

            # 콜백 등록
            ws_client.on_trade_data = on_trade
            ws_client.on_order_book = on_order_book
            ws_client.on_order_execution = on_order_execution
            ws_client.on_balance_update = on_balance_update
            ws_client.on_connect = on_connect
            ws_client.on_disconnect = on_disconnect
            ws_client.on_error = on_error

            print("[OK] WebSocket client created")

            # WebSocket 연결
            print("\n[3/5] Connecting to WebSocket server...")
            connected = await ws_client.connect()

            if not connected:
                print("[FAILED] WebSocket connection failed")
                return False

            print(f"[OK] Connected to {ws_client.websocket_url}")
            print(f"[OK] Connection state: {ws_client.state.value}")

            # 실시간 시세 등록
            print("\n[4/5] Subscribing to real-time data...")
            subscribed = await ws_client.subscribe(
                stock_codes=stock_codes,
                types=[RealTimeType.TRADE.value, RealTimeType.ORDER_BOOK.value],
                refresh=True
            )

            if subscribed:
                print(f"[OK] Subscribed to {len(stock_codes)} stocks")
                print(f"[OK] Types: 0B (Trade), 0D (Order Book)")
            else:
                print("[WARNING] Subscription may have failed")

            # 데이터 수신 대기
            print(f"\n[5/5] Waiting for real-time data ({timeout} seconds)...")
            print("-" * 70)

            # 백그라운드에서 메시지 수신
            receive_task = asyncio.create_task(ws_client.run_forever())

            # 타임아웃까지 대기
            try:
                await asyncio.wait_for(
                    asyncio.shield(receive_task),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                print("\n" + "-" * 70)
                print(f"[OK] Timeout reached ({timeout} seconds)")

            # 정리
            print("\n[Cleanup] Disconnecting...")
            await ws_client.disconnect()

            # 결과 출력
            print("\n" + "=" * 70)
            print("Test Results")
            print("=" * 70)
            print(f"Trade data (0B) received:       {stats['trade_count']:>5}")
            print(f"Order book data (0D) received:  {stats['order_book_count']:>5}")
            print(f"Order execution (00) received:  {stats['order_execution_count']:>5}")
            print(f"Balance update (04) received:   {stats['balance_update_count']:>5}")
            print(f"Errors:                         {len(stats['errors']):>5}")

            if stats["errors"]:
                print("\nErrors encountered:")
                for err in stats["errors"]:
                    print(f"  - {err}")

            total = (
                stats["trade_count"] +
                stats["order_book_count"] +
                stats["order_execution_count"] +
                stats["balance_update_count"]
            )

            print("\n" + "=" * 70)
            if total > 0:
                print(f"[SUCCESS] Test passed! Received {total} messages")
                return True
            else:
                print("[WARNING] No data received. This may be normal outside market hours.")
                print("         Try during market hours (09:00 - 15:30 KST)")
                return True  # 장 외 시간이면 데이터 없는 게 정상

    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """메인 함수."""
    parser = argparse.ArgumentParser(
        description="WebSocket connection test script"
    )
    parser.add_argument(
        "--stocks",
        type=str,
        default="005930,000660",
        help="Comma-separated stock codes (default: 005930,000660)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Data receive timeout in seconds (default: 30)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()
    stock_codes = [s.strip() for s in args.stocks.split(",")]

    # 로깅 설정
    import logging
    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # 테스트 실행
    success = asyncio.run(
        test_websocket(
            stock_codes=stock_codes,
            timeout=args.timeout,
            verbose=args.verbose
        )
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
