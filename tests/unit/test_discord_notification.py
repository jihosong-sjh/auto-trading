"""Discord 알림 테스트 스크립트."""

import asyncio
import os
from dotenv import load_dotenv
from src.services.notifier import DiscordNotifier, NotificationManager
from src.models import Notification, NotificationType

# .env 파일 로드
load_dotenv()


async def test_discord_notification():
    """Discord 알림 전송 테스트."""
    print("=" * 60)
    print("Discord 알림 테스트 시작")
    print("=" * 60)

    # 1. 환경 변수 확인
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    enabled = os.getenv("DISCORD_NOTIFICATION_ENABLED", "false").lower() == "true"

    print(f"\n[설정 확인]")
    print(f"DISCORD_NOTIFICATION_ENABLED: {enabled}")
    print(f"DISCORD_WEBHOOK_URL: {webhook_url[:50]}..." if webhook_url else "Not set")

    if not enabled:
        print("\n[ERROR] Discord 알림이 비활성화되어 있습니다.")
        print("Please set DISCORD_NOTIFICATION_ENABLED=true in .env")
        return

    if not webhook_url:
        print("\n[ERROR] Discord Webhook URL이 설정되지 않았습니다.")
        return

    # 2. DiscordNotifier 생성
    print(f"\n[DiscordNotifier 생성]")
    notifier = DiscordNotifier(webhook_url=webhook_url)

    if not notifier.is_configured():
        print("[ERROR] Discord 설정이 올바르지 않습니다.")
        return

    print("[SUCCESS] Discord 설정 완료")

    # 3. 테스트 알림 전송 - 시스템 상태
    print(f"\n[테스트 1] 시스템 상태 알림 전송 중...")
    notification1 = Notification(
        notification_type=NotificationType.SYSTEM_STATUS,
        title="시스템 테스트 알림",
        message="Discord 알림 시스템이 정상적으로 작동하고 있습니다!",
        metadata={
            "테스트 항목": "Discord Webhook",
            "상태": "정상",
        }
    )

    success1 = await notifier.send(notification1)
    print(f"[RESULT] 전송 {'성공' if success1 else '실패'}")

    # 4. 테스트 알림 전송 - 주문 체결
    print(f"\n[테스트 2] 주문 체결 알림 전송 중...")
    notification2 = Notification(
        notification_type=NotificationType.ORDER_FILLED,
        title="매수 주문 체결",
        message="삼성전자 10주가 70,000원에 매수 체결되었습니다.",
        metadata={
            "종목명": "삼성전자",
            "종목코드": "005930",
            "주문유형": "BUY",
            "수량": "10주",
            "가격": "70,000원",
            "체결금액": "700,000원",
        }
    )

    success2 = await notifier.send(notification2)
    print(f"[RESULT] 전송 {'성공' if success2 else '실패'}")

    # 5. 테스트 알림 전송 - 위험 경고
    print(f"\n[테스트 3] 위험 경고 알림 전송 중...")
    notification3 = Notification(
        notification_type=NotificationType.RISK_ALERT,
        title="위험 경고: 일일 손실 한도 근접",
        message="일일 손실이 4.8%에 도달했습니다. 설정된 한도(5%)에 근접했습니다.",
        metadata={
            "현재 손실률": "4.8%",
            "설정 한도": "5.0%",
            "잔여 여유": "0.2%",
        }
    )

    success3 = await notifier.send(notification3)
    print(f"[RESULT] 전송 {'성공' if success3 else '실패'}")

    # 6. NotificationManager를 사용한 테스트
    print(f"\n[테스트 4] NotificationManager 사용 테스트...")
    manager = NotificationManager()
    manager.add_notifier(notifier)

    results = await manager.send_daily_report(
        report_content="오늘의 거래가 종료되었습니다. 총 수익률: +2.3%",
        metadata={
            "거래일": "2025-11-24",
            "총 거래 건수": "5건",
            "총 수익률": "+2.3%",
            "실현 손익": "+230,000원",
            "최고 수익 종목": "삼성전자 (+5.2%)",
            "최저 수익 종목": "SK하이닉스 (-1.1%)",
        }
    )

    print(f"[RESULT] NotificationManager 전송 결과: {results}")

    # 7. 최종 결과
    print("\n" + "=" * 60)
    print("테스트 완료!")
    print("=" * 60)
    print(f"총 테스트: 4개")
    print(f"성공: {sum([success1, success2, success3, any(results.values())])}개")
    print("\nDiscord 채널을 확인하여 알림이 도착했는지 확인하세요.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_discord_notification())
