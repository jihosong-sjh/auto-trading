"""PositionService 단위 테스트."""

import pytest
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo

from src.models.position import Position
from src.models.stock import Stock
from src.services.position_service import PositionService

KST = ZoneInfo("Asia/Seoul")


class FakePositionProvider:
    """테스트용 가짜 PositionProvider.

    실제 API 호출 없이 포지션 목록을 반환합니다.
    """

    def __init__(self, positions: list[Position]):
        """FakePositionProvider 초기화.

        Args:
            positions: 초기 포지션 목록.
        """
        self.positions = positions

    def get_positions(self) -> list[Position]:
        """포지션 목록을 반환합니다.

        Returns:
            List[Position]: 포지션 목록.
        """
        return self.positions


class FakePriceProvider:
    """테스트용 가짜 PriceProvider.

    실제 API 호출 없이 종목 가격을 반환합니다.
    """

    def __init__(self, prices: dict[str, Decimal]):
        """FakePriceProvider 초기화.

        Args:
            prices: 종목코드 -> 가격 매핑.
        """
        self.prices = prices

    async def get_stock_price(self, stock_code: str) -> Stock:
        """종목 가격을 반환합니다.

        Args:
            stock_code: 종목코드.

        Returns:
            Stock: 종목 정보.
        """
        from src.models import MarketType

        price = self.prices.get(stock_code, Decimal("0"))
        return Stock(
            stock_code=stock_code,
            stock_name=f"종목{stock_code}",
            market=MarketType.KOSPI,
            current_price=price,
            volume=0,
            updated_at=datetime.now(tz=KST)
        )


@pytest.fixture
def sample_positions():
    """테스트용 샘플 포지션들."""
    return [
        Position(
            account_number="12345678",
            stock_code="005930",  # 삼성전자
            quantity=100,
            average_buy_price=Decimal("70000.00"),
            current_price=Decimal("72000.00"),
            strategy_name="GoldenCross",
            opened_at=datetime(2025, 11, 20, 10, 0, 0, tzinfo=KST),
            updated_at=datetime.now(tz=KST)
        ),
        Position(
            account_number="12345678",
            stock_code="000660",  # SK하이닉스
            quantity=50,
            average_buy_price=Decimal("120000.00"),
            current_price=Decimal("118000.00"),
            strategy_name="GoldenCross",
            opened_at=datetime(2025, 11, 21, 14, 0, 0, tzinfo=KST),
            updated_at=datetime.now(tz=KST)
        ),
        Position(
            account_number="12345678",
            stock_code="035720",  # 카카오
            quantity=200,
            average_buy_price=Decimal("50000.00"),
            current_price=Decimal("52000.00"),
            strategy_name="Momentum",
            opened_at=datetime(2025, 11, 22, 9, 30, 0, tzinfo=KST),
            updated_at=datetime.now(tz=KST)
        )
    ]


@pytest.fixture
def position_service(sample_positions):
    """테스트용 PositionService 인스턴스."""
    provider = FakePositionProvider(sample_positions)
    return PositionService(provider)


def test_get_all_positions(position_service):
    """모든 포지션 조회 테스트."""
    # When: 모든 포지션 조회
    positions = position_service.get_all_positions()

    # Then: 3개의 포지션이 반환됨
    assert len(positions) == 3
    assert positions[0].stock_code == "005930"
    assert positions[1].stock_code == "000660"
    assert positions[2].stock_code == "035720"


def test_get_position_by_stock_존재하는_종목(position_service):
    """특정 종목 포지션 조회 (존재하는 경우)."""
    # When: 삼성전자 포지션 조회
    position = position_service.get_position_by_stock("005930")

    # Then: 포지션이 반환됨
    assert position is not None
    assert position.stock_code == "005930"
    assert position.quantity == 100


def test_get_position_by_stock_존재하지_않는_종목(position_service):
    """특정 종목 포지션 조회 (존재하지 않는 경우)."""
    # When: 존재하지 않는 종목 조회
    position = position_service.get_position_by_stock("999999")

    # Then: None이 반환됨
    assert position is None


def test_has_position_보유_중(position_service):
    """포지션 보유 여부 확인 (보유 중)."""
    # When: 삼성전자 보유 여부 확인
    has_pos = position_service.has_position("005930")

    # Then: True
    assert has_pos is True


def test_has_position_보유하지_않음(position_service):
    """포지션 보유 여부 확인 (보유하지 않음)."""
    # When: 존재하지 않는 종목 보유 여부 확인
    has_pos = position_service.has_position("999999")

    # Then: False
    assert has_pos is False


def test_get_positions_by_strategy_GoldenCross(position_service):
    """특정 전략 포지션 조회 (GoldenCross)."""
    # When: GoldenCross 전략 포지션 조회
    positions = position_service.get_positions_by_strategy("GoldenCross")

    # Then: 2개의 포지션 (삼성전자, SK하이닉스)
    assert len(positions) == 2
    assert positions[0].stock_code == "005930"
    assert positions[1].stock_code == "000660"


def test_get_positions_by_strategy_Momentum(position_service):
    """특정 전략 포지션 조회 (Momentum)."""
    # When: Momentum 전략 포지션 조회
    positions = position_service.get_positions_by_strategy("Momentum")

    # Then: 1개의 포지션 (카카오)
    assert len(positions) == 1
    assert positions[0].stock_code == "035720"


def test_get_positions_by_strategy_없는_전략(position_service):
    """존재하지 않는 전략 포지션 조회."""
    # When: 존재하지 않는 전략 조회
    positions = position_service.get_positions_by_strategy("NonExistent")

    # Then: 빈 리스트
    assert len(positions) == 0


def test_calculate_total_evaluation_amount(position_service):
    """총 평가 금액 계산 테스트."""
    # When: 총 평가 금액 계산
    total = position_service.calculate_total_evaluation_amount()

    # Then:
    # 삼성전자: 100주 * 72,000 = 7,200,000
    # SK하이닉스: 50주 * 118,000 = 5,900,000
    # 카카오: 200주 * 52,000 = 10,400,000
    # 합계: 23,500,000
    expected = Decimal("72000") * 100 + Decimal("118000") * 50 + Decimal("52000") * 200
    assert total == expected


def test_calculate_total_unrealized_pnl(position_service):
    """총 미실현 손익 계산 테스트."""
    # When: 총 미실현 손익 계산
    total_pnl = position_service.calculate_total_unrealized_pnl()

    # Then:
    # 삼성전자: (72,000 - 70,000) * 100 = +200,000
    # SK하이닉스: (118,000 - 120,000) * 50 = -100,000
    # 카카오: (52,000 - 50,000) * 200 = +400,000
    # 합계: +500,000
    expected = (
        (Decimal("72000") - Decimal("70000")) * 100 +
        (Decimal("118000") - Decimal("120000")) * 50 +
        (Decimal("52000") - Decimal("50000")) * 200
    )
    assert total_pnl == expected


def test_calculate_average_return_rate(position_service):
    """평균 수익률 계산 테스트."""
    # When: 평균 수익률 계산
    avg_return = position_service.calculate_average_return_rate()

    # Then:
    # 삼성전자: (72,000 - 70,000) / 70,000 = 0.0286 (2.86%)
    # SK하이닉스: (118,000 - 120,000) / 120,000 = -0.0167 (-1.67%)
    # 카카오: (52,000 - 50,000) / 50,000 = 0.04 (4%)
    # 평균: (0.0286 - 0.0167 + 0.04) / 3 = 0.0173 (1.73%)
    samsung_return = (Decimal("72000") - Decimal("70000")) / Decimal("70000")
    sk_return = (Decimal("118000") - Decimal("120000")) / Decimal("120000")
    kakao_return = (Decimal("52000") - Decimal("50000")) / Decimal("50000")
    expected = (samsung_return + sk_return + kakao_return) / 3

    # Decimal 정밀도 허용 오차
    assert abs(avg_return - expected) < Decimal("0.0001")


def test_calculate_average_return_rate_포지션_없음():
    """포지션이 없을 때 평균 수익률은 0."""
    # Given: 빈 포지션 리스트
    provider = FakePositionProvider([])
    service = PositionService(provider)

    # When: 평균 수익률 계산
    avg_return = service.calculate_average_return_rate()

    # Then: 0
    assert avg_return == Decimal("0")


@pytest.mark.asyncio
async def test_update_position_prices(sample_positions):
    """포지션 가격 업데이트 테스트."""
    # Given: 포지션 서비스와 가격 제공자 생성
    position_provider = FakePositionProvider(sample_positions)
    price_provider = FakePriceProvider({
        "005930": Decimal("75000.00"),  # 삼성전자 가격 상승
        "000660": Decimal("115000.00"),  # SK하이닉스 가격 하락
        "035720": Decimal("53000.00")   # 카카오 가격 상승
    })
    service = PositionService(position_provider, price_provider)

    # When: 포지션 가격 업데이트
    await service.update_position_prices()

    # Then: 모든 포지션의 현재가가 업데이트됨
    positions = service.get_all_positions()
    assert positions[0].current_price == Decimal("75000.00")
    assert positions[1].current_price == Decimal("115000.00")
    assert positions[2].current_price == Decimal("53000.00")


def test_get_position_concentration(position_service):
    """포지션 집중도 계산 테스트."""
    # When: 포지션 집중도 계산
    concentrations = position_service.get_position_concentration()

    # Then: 각 포지션의 비중 계산
    # 총 평가액: 23,500,000
    # 삼성전자: 7,200,000 / 23,500,000 = 0.3064 (30.64%)
    # SK하이닉스: 5,900,000 / 23,500,000 = 0.2511 (25.11%)
    # 카카오: 10,400,000 / 23,500,000 = 0.4426 (44.26%)
    assert len(concentrations) == 3

    total = Decimal("23500000")
    assert abs(concentrations["005930"] - (Decimal("7200000") / total)) < Decimal("0.0001")
    assert abs(concentrations["000660"] - (Decimal("5900000") / total)) < Decimal("0.0001")
    assert abs(concentrations["035720"] - (Decimal("10400000") / total)) < Decimal("0.0001")


def test_get_position_concentration_포지션_없음():
    """포지션이 없을 때 집중도는 빈 딕셔너리."""
    # Given: 빈 포지션 리스트
    provider = FakePositionProvider([])
    service = PositionService(provider)

    # When: 집중도 계산
    concentrations = service.get_position_concentration()

    # Then: 빈 딕셔너리
    assert concentrations == {}


def test_get_losing_positions(position_service):
    """손실 포지션 조회 테스트."""
    # When: 손실 포지션 조회
    losing = position_service.get_losing_positions()

    # Then: SK하이닉스만 손실 (-100,000원)
    assert len(losing) == 1
    assert losing[0].stock_code == "000660"
    assert losing[0].unrealized_pnl < 0


def test_get_winning_positions(position_service):
    """수익 포지션 조회 테스트."""
    # When: 수익 포지션 조회
    winning = position_service.get_winning_positions()

    # Then: 삼성전자, 카카오가 수익
    assert len(winning) == 2
    assert winning[0].stock_code == "005930"
    assert winning[1].stock_code == "035720"
    assert all(pos.unrealized_pnl > 0 for pos in winning)


def test_get_position_summary(position_service):
    """포지션 요약 정보 테스트."""
    # When: 포지션 요약 조회
    summary = position_service.get_position_summary()

    # Then: 요약 정보가 올바르게 계산됨
    assert summary["count"] == 3
    assert summary["total_value"] == Decimal("23500000")
    assert summary["total_pnl"] == Decimal("500000")
    assert summary["winning_count"] == 2
    assert summary["losing_count"] == 1

    # 평균 수익률 확인
    samsung_return = (Decimal("72000") - Decimal("70000")) / Decimal("70000")
    sk_return = (Decimal("118000") - Decimal("120000")) / Decimal("120000")
    kakao_return = (Decimal("52000") - Decimal("50000")) / Decimal("50000")
    expected_avg_return = (samsung_return + sk_return + kakao_return) / 3
    assert abs(summary["avg_return_rate"] - expected_avg_return) < Decimal("0.0001")


def test_get_position_summary_포지션_없음():
    """포지션이 없을 때 요약 정보."""
    # Given: 빈 포지션 리스트
    provider = FakePositionProvider([])
    service = PositionService(provider)

    # When: 요약 조회
    summary = service.get_position_summary()

    # Then: 모든 값이 0
    assert summary["count"] == 0
    assert summary["total_value"] == Decimal("0")
    assert summary["total_pnl"] == Decimal("0")
    assert summary["avg_return_rate"] == Decimal("0")
    assert summary["winning_count"] == 0
    assert summary["losing_count"] == 0
