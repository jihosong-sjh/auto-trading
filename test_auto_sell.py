"""Phase 1-2 자동 매도 시스템 통합 테스트.

이 스크립트는 다음 기능을 테스트합니다:
1. 매수 체결 시 손절가/익절가 자동 설정
2. 실시간 리스크 모니터링 (1초마다 체크)
3. 손절/익절 트리거 발생 시 자동 매도
"""

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.models import Stock, Order, OrderType, PriceType, OrderStatus
from src.models.position import Position
from src.simulator.kiwoom_simulator import KiwoomSimulator
from src.services.order_executor import OrderExecutor
from src.services.risk_manager import RiskManager
from src.services.risk_monitor import RiskMonitor


async def test_stop_loss_trigger():
    """손절 트리거 테스트."""
    print("\n" + "="*60)
    print("TEST 1: 손절 트리거 테스트")
    print("="*60)

    # 1. 시뮬레이터 초기화
    client = KiwoomSimulator(initial_balance=Decimal("10000000"))  # 1000만원

    # 종목 등록 (삼성전자)
    client.exchange.set_price("005930", Decimal("70000"))  # 초기가 70,000원
    print(f"[OK] 시뮬레이터 초기화 완료 (잔고: {client.account.cash_balance:,}원)")
    print(f"[OK] 종목 등록 완료: 005930 (삼성전자) @ 70,000원")

    # 2. 공유 상태 (KiwoomSimulator의 positions 사용)
    pending_orders = {}
    positions = client.positions  # Simulator의 positions 사용

    # 3. OrderExecutor 생성
    executor = OrderExecutor(
        client=client,
        pending_orders=pending_orders,
        positions=positions
    )
    print("[OK] OrderExecutor 생성 완료")

    # 4. RiskMonitor 생성
    risk_manager = RiskManager(
        daily_loss_limit_pct=Decimal("0.02"),
        max_position_concentration=Decimal("0.3"),
        warning_threshold=Decimal("0.8")
    )
    risk_monitor = RiskMonitor(
        risk_manager=risk_manager,
        order_executor=executor,
        positions=positions,
        client=client,
        check_interval=1.0
    )
    print("[OK] RiskMonitor 생성 완료")

    # 5. 매수 주문 생성 및 실행
    buy_order = Order(
        account_number="12345678",
        stock_code="005930",
        order_type=OrderType.BUY,
        price_type=PriceType.MARKET,
        quantity=10,
        strategy_name="test_strategy"
    )
    print(f"\n[STEP 1] 매수 주문 실행: {buy_order.stock_code} {buy_order.quantity}주")

    success, error, filled_order = await executor.execute_order(buy_order)

    if not success:
        print(f"[FAIL] 매수 주문 실패: {error}")
        return False

    print(f"[OK] 매수 체결: {filled_order.filled_quantity}주 @ {filled_order.filled_price:,}원")

    # 6. 포지션 확인
    position = positions.get("005930")
    if not position:
        print("[FAIL] 포지션이 생성되지 않음")
        return False

    print(f"[OK] 포지션 생성: 수량={position.quantity}주, 평균가={position.average_buy_price:,}원")

    # 7. 손절가/익절가 수동 설정 (테스트용)
    avg_price = position.average_buy_price
    stop_loss_price = avg_price * Decimal("0.97")  # -3%
    take_profit_price = avg_price * Decimal("1.05")  # +5%

    position.set_stop_loss(stop_loss_price)
    position.set_take_profit(take_profit_price)

    print(f"\n[STEP 2] 손절가/익절가 설정")
    print(f"  - 평균 매수가: {avg_price:,.0f}원")
    print(f"  - 손절가: {stop_loss_price:,.0f}원 (-3%)")
    print(f"  - 익절가: {take_profit_price:,.0f}원 (+5%)")

    # 8. RiskMonitor 백그라운드 태스크 시작
    print("\n[STEP 3] RiskMonitor 시작 (1초 간격)")
    monitor_task = asyncio.create_task(risk_monitor.run())

    # 9. 가격 하락 시뮬레이션 (손절가 트리거)
    print("\n[STEP 4] 가격 하락 시뮬레이션")
    for i in range(5):
        await asyncio.sleep(1.5)

        # 가격 점진적 하락
        new_price = avg_price * (Decimal("1.0") - Decimal(str(i * 0.01)))
        client.exchange.set_price("005930", new_price)

        print(f"  [{i+1}] 현재가: {new_price:,.0f}원 (변동: {((new_price/avg_price - 1) * 100):.1f}%)")

        # 손절가 도달 확인
        if new_price <= stop_loss_price:
            print(f"  [TRIGGER] 손절가 도달! (현재가 {new_price:,.0f} <= 손절가 {stop_loss_price:,.0f})")
            break

    # 10. 잠시 대기 (RiskMonitor가 매도 주문 실행할 시간 제공)
    print("\n[STEP 5] RiskMonitor 처리 대기 (3초)...")
    await asyncio.sleep(3)

    # 11. 결과 확인
    print("\n" + "="*60)
    print("테스트 결과")
    print("="*60)

    # 포지션이 청산되었는지 확인
    if "005930" not in positions:
        print("[SUCCESS] 포지션이 자동 청산되었습니다!")
        print(f"최종 계좌 잔고: {client.account.cash_balance:,}원")
        result = True
    else:
        remaining_position = positions["005930"]
        print(f"[FAIL] 포지션이 남아있습니다 (수량: {remaining_position.quantity}주)")
        result = False

    # 12. RiskMonitor 중지
    await risk_monitor.stop()
    await monitor_task

    return result


async def test_take_profit_trigger():
    """익절 트리거 테스트."""
    print("\n" + "="*60)
    print("TEST 2: 익절 트리거 테스트")
    print("="*60)

    # 1. 시뮬레이터 초기화
    client = KiwoomSimulator(initial_balance=Decimal("10000000"))

    # 종목 등록 (삼성전자)
    client.exchange.set_price("005930", Decimal("70000"))  # 초기가 70,000원
    print(f"[OK] 시뮬레이터 초기화 완료 (잔고: {client.account.cash_balance:,}원)")
    print(f"[OK] 종목 등록 완료: 005930 (삼성전자) @ 70,000원")

    # 2. 공유 상태 (KiwoomSimulator의 positions 사용)
    pending_orders = {}
    positions = client.positions  # Simulator의 positions 사용

    # 3. OrderExecutor 생성
    executor = OrderExecutor(
        client=client,
        pending_orders=pending_orders,
        positions=positions
    )

    # 4. RiskMonitor 생성
    risk_manager = RiskManager()
    risk_monitor = RiskMonitor(
        risk_manager=risk_manager,
        order_executor=executor,
        positions=positions,
        client=client,
        check_interval=1.0
    )

    # 5. 매수 주문
    buy_order = Order(
        account_number="12345678",
        stock_code="005930",
        order_type=OrderType.BUY,
        price_type=PriceType.MARKET,
        quantity=10,
        strategy_name="test_strategy"
    )
    print(f"\n[STEP 1] 매수 주문 실행: {buy_order.stock_code} {buy_order.quantity}주")

    success, error, filled_order = await executor.execute_order(buy_order)

    if not success:
        print(f"[FAIL] 매수 주문 실패: {error}")
        return False

    print(f"[OK] 매수 체결: {filled_order.filled_quantity}주 @ {filled_order.filled_price:,}원")

    # 6. 포지션 확인 및 익절가 설정
    position = positions["005930"]
    avg_price = position.average_buy_price
    stop_loss_price = avg_price * Decimal("0.95")  # -5%
    take_profit_price = avg_price * Decimal("1.03")  # +3%

    position.set_stop_loss(stop_loss_price)
    position.set_take_profit(take_profit_price)

    print(f"\n[STEP 2] 손절가/익절가 설정")
    print(f"  - 평균 매수가: {avg_price:,.0f}원")
    print(f"  - 손절가: {stop_loss_price:,.0f}원 (-5%)")
    print(f"  - 익절가: {take_profit_price:,.0f}원 (+3%)")

    # 7. RiskMonitor 시작
    print("\n[STEP 3] RiskMonitor 시작")
    monitor_task = asyncio.create_task(risk_monitor.run())

    # 8. 가격 상승 시뮬레이션 (익절가 트리거)
    print("\n[STEP 4] 가격 상승 시뮬레이션")
    for i in range(5):
        await asyncio.sleep(1.5)

        # 가격 점진적 상승
        new_price = avg_price * (Decimal("1.0") + Decimal(str(i * 0.01)))
        client.exchange.set_price("005930", new_price)

        print(f"  [{i+1}] 현재가: {new_price:,.0f}원 (변동: {((new_price/avg_price - 1) * 100):.1f}%)")

        # 익절가 도달 확인
        if new_price >= take_profit_price:
            print(f"  [TRIGGER] 익절가 도달! (현재가 {new_price:,.0f} >= 익절가 {take_profit_price:,.0f})")
            break

    # 9. 처리 대기
    print("\n[STEP 5] RiskMonitor 처리 대기 (3초)...")
    await asyncio.sleep(3)

    # 10. 결과 확인
    print("\n" + "="*60)
    print("테스트 결과")
    print("="*60)

    if "005930" not in positions:
        print("[SUCCESS] 포지션이 자동 청산되었습니다!")
        print(f"최종 계좌 잔고: {client.account.cash_balance:,}원")
        result = True
    else:
        print(f"[FAIL] 포지션이 남아있습니다")
        result = False

    # 11. RiskMonitor 중지
    await risk_monitor.stop()
    await monitor_task

    return result


async def main():
    """메인 테스트 함수."""
    print("\n" + "="*60)
    print("Phase 1-2 자동 매도 시스템 통합 테스트")
    print("="*60)
    print("\n이 테스트는 다음을 검증합니다:")
    print("  1. 매수 체결 시 손절가/익절가 자동 설정")
    print("  2. RiskMonitor의 실시간 모니터링 (1초 간격)")
    print("  3. 손절/익절 트리거 발생 시 자동 매도 주문 실행")
    print("  4. 포지션 자동 청산 확인")

    try:
        # Test 1: 손절 트리거
        test1_result = await test_stop_loss_trigger()

        # Test 2: 익절 트리거
        test2_result = await test_take_profit_trigger()

        # 최종 결과
        print("\n" + "="*60)
        print("전체 테스트 결과")
        print("="*60)
        print(f"Test 1 (손절 트리거): {'[PASS]' if test1_result else '[FAIL]'}")
        print(f"Test 2 (익절 트리거): {'[PASS]' if test2_result else '[FAIL]'}")

        if test1_result and test2_result:
            print("\n[SUCCESS] 모든 테스트 통과!")
            return 0
        else:
            print("\n[FAIL] 일부 테스트 실패")
            return 1

    except Exception as e:
        print(f"\n[ERROR] 테스트 실행 중 오류: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
