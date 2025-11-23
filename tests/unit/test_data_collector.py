"""DataCollector 단위 테스트 (T076).

T076 테스트 범위:
- ChartDataCache의 TTL 및 LRU 동작
- StaggeredPricePoller의 분산 폴링 동작
- DataCollector의 타임아웃 감지 로직
- 차트 데이터 캐싱 및 조회
"""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from src.config.settings import Settings
from src.models import ChartInterval, MarketType, Stock
from src.models.chart_data import ChartData
from src.services.data_collector import (
    ChartDataCache,
    DataCollector,
    StaggeredPricePoller,
)

KST = ZoneInfo("Asia/Seoul")


# Mock Kiwoom 클라이언트
class MockKiwoomClient:
    """테스트용 Mock Kiwoom 클라이언트."""

    def __init__(self):
        self.get_stock_price_calls = []
        self.get_chart_data_calls = []
        self.connect_calls = 0

    async def get_stock_price(self, stock_code: str) -> Stock:
        """종목 시세 조회 (Mock).

        Args:
            stock_code: 종목코드.

        Returns:
            Mock Stock 데이터.
        """
        self.get_stock_price_calls.append(stock_code)
        return Stock(
            stock_code=stock_code,
            stock_name=f"종목{stock_code}",
            market=MarketType.KOSPI,
            current_price=Decimal("50000.00"),
            volume=1000000,
            updated_at=datetime.now(tz=KST)
        )

    async def get_chart_data(
        self,
        stock_code: str,
        interval: ChartInterval = ChartInterval.DAY
    ) -> list[ChartData]:
        """차트 데이터 조회 (Mock).

        Args:
            stock_code: 종목코드.
            interval: 차트 주기.

        Returns:
            Mock ChartData 리스트.
        """
        self.get_chart_data_calls.append((stock_code, interval))

        # 가짜 차트 데이터 생성 (최근 5일치)
        chart_data = []
        base_time = datetime.now(tz=KST)

        for i in range(5):
            timestamp = base_time - timedelta(days=i)
            chart_data.append(
                ChartData(
                    stock_code=stock_code,
                    interval=interval,
                    timestamp=timestamp,
                    open_price=Decimal("49000.00"),
                    high_price=Decimal("51000.00"),
                    low_price=Decimal("48000.00"),
                    close_price=Decimal("50000.00"),
                    volume=1000000
                )
            )

        return chart_data

    async def connect(self):
        """재연결 (Mock)."""
        self.connect_calls += 1


# Fixtures
@pytest.fixture
def mock_client():
    """Mock Kiwoom 클라이언트 생성."""
    return MockKiwoomClient()


@pytest.fixture
def mock_config():
    """Mock 설정 생성."""
    return Settings(
        kiwoom_appkey="test_key",
        kiwoom_appsecret="test_secret",
        initial_balance=Decimal("10000000"),
        daily_loss_limit=Decimal("500000"),
        max_position_concentration=Decimal("0.3")
    )


@pytest.fixture
def market_data_queue():
    """시장 데이터 큐 생성."""
    return asyncio.Queue()


# =============================================================================
# ChartDataCache 테스트
# =============================================================================

def test_chart_cache_basic_operations():
    """차트 캐시 기본 동작 테스트.

    검증:
    - 캐시 저장 및 조회
    - 캐시 미스
    """
    cache = ChartDataCache(ttl_seconds=5, max_size=10)

    # 테스트 데이터 생성
    chart_data = [
        ChartData(
            stock_code="005930",
            interval=ChartInterval.DAY,
            timestamp=datetime.now(tz=KST),
            open_price=Decimal("70000"),
            high_price=Decimal("72000"),
            low_price=Decimal("69000"),
            close_price=Decimal("71000"),
            volume=1000000
        )
    ]

    # 캐시 저장
    cache.set("005930", ChartInterval.DAY, chart_data)

    # 캐시 조회 (히트)
    cached = cache.get("005930", ChartInterval.DAY)
    assert cached is not None
    assert len(cached) == 1
    assert cached[0].stock_code == "005930"

    # 캐시 미스
    missed = cache.get("000660", ChartInterval.DAY)
    assert missed is None


@pytest.mark.asyncio
async def test_chart_cache_ttl_expiration():
    """차트 캐시 TTL 만료 테스트.

    검증:
    - TTL 이내 캐시 히트
    - TTL 초과 캐시 미스
    """
    cache = ChartDataCache(ttl_seconds=1, max_size=10)  # 1초 TTL

    chart_data = [
        ChartData(
            stock_code="005930",
            interval=ChartInterval.DAY,
            timestamp=datetime.now(tz=KST),
            open_price=Decimal("70000"),
            high_price=Decimal("72000"),
            low_price=Decimal("69000"),
            close_price=Decimal("71000"),
            volume=1000000
        )
    ]

    # 캐시 저장
    cache.set("005930", ChartInterval.DAY, chart_data)

    # TTL 이내 조회 (히트)
    cached = cache.get("005930", ChartInterval.DAY)
    assert cached is not None

    # TTL 초과 대기
    await asyncio.sleep(1.5)

    # TTL 초과 조회 (미스)
    expired = cache.get("005930", ChartInterval.DAY)
    assert expired is None


def test_chart_cache_lru_eviction():
    """차트 캐시 LRU 제거 테스트.

    검증:
    - 최대 크기 초과 시 가장 오래된 항목 제거
    - LRU 순서 유지
    """
    cache = ChartDataCache(ttl_seconds=60, max_size=3)  # 최대 3개

    # 4개 저장 (1개는 LRU로 제거되어야 함)
    for i in range(4):
        chart_data = [
            ChartData(
                stock_code=f"00000{i}",
                interval=ChartInterval.DAY,
                timestamp=datetime.now(tz=KST),
                open_price=Decimal("70000"),
                high_price=Decimal("72000"),
                low_price=Decimal("69000"),
                close_price=Decimal("71000"),
                volume=1000000
            )
        ]
        cache.set(f"00000{i}", ChartInterval.DAY, chart_data)

    # 가장 오래된 항목 (000000)은 제거되어야 함
    assert cache.get("000000", ChartInterval.DAY) is None

    # 나머지 3개는 존재
    assert cache.get("000001", ChartInterval.DAY) is not None
    assert cache.get("000002", ChartInterval.DAY) is not None
    assert cache.get("000003", ChartInterval.DAY) is not None

    # 통계 확인
    stats = cache.get_stats()
    assert stats["size"] == 3
    assert stats["max_size"] == 3


# =============================================================================
# StaggeredPricePoller 테스트
# =============================================================================

@pytest.mark.asyncio
async def test_staggered_poller_basic(mock_client, market_data_queue):
    """분산 폴링 기본 동작 테스트.

    검증:
    - 폴링 시작 및 중지
    - 종목별 시세 조회
    - 큐에 데이터 전달
    """
    stock_codes = ["005930", "000660"]

    poller = StaggeredPricePoller(
        client=mock_client,
        stock_codes=stock_codes,
        market_data_queue=market_data_queue,
        interval_seconds=0.5  # 빠른 테스트를 위해 0.5초
    )

    # 폴링 시작
    await poller.start()

    # 데이터 수신 대기 (최소 2개 종목 x 1회 = 2개)
    await asyncio.sleep(1.0)

    # 폴링 중지
    await poller.stop()

    # 큐에 데이터가 들어왔는지 확인
    assert not market_data_queue.empty()

    # 최소 2개 이상의 데이터 수신
    received_data = []
    while not market_data_queue.empty():
        received_data.append(await market_data_queue.get())

    assert len(received_data) >= 2

    # 모든 종목 코드가 폴링되었는지 확인
    stock_codes_received = {stock.stock_code for stock in received_data}
    assert "005930" in stock_codes_received
    assert "000660" in stock_codes_received


@pytest.mark.asyncio
async def test_staggered_poller_empty_stocks(mock_client, market_data_queue):
    """빈 종목 리스트로 폴링 테스트.

    검증:
    - 종목이 없을 때 정상 처리
    """
    poller = StaggeredPricePoller(
        client=mock_client,
        stock_codes=[],  # 빈 리스트
        market_data_queue=market_data_queue,
        interval_seconds=1.0
    )

    await poller.start()
    await asyncio.sleep(0.5)
    await poller.stop()

    # 큐에 데이터가 없어야 함
    assert market_data_queue.empty()


# =============================================================================
# DataCollector 테스트
# =============================================================================

@pytest.mark.asyncio
async def test_data_collector_chart_caching(mock_client, mock_config, market_data_queue):
    """DataCollector 차트 데이터 캐싱 테스트.

    검증:
    - 차트 데이터 조회 및 캐싱
    - 캐시 히트 시 API 호출 생략
    """
    collector = DataCollector(
        config=mock_config,
        client=mock_client,
        market_data_queue=market_data_queue,
        stock_codes=["005930"]
    )

    # 첫 번째 조회 (API 호출)
    chart_data_1 = await collector.get_chart_data("005930", ChartInterval.DAY, use_cache=True)
    assert len(chart_data_1) == 5
    assert len(mock_client.get_chart_data_calls) == 1

    # 두 번째 조회 (캐시 히트, API 호출 없음)
    chart_data_2 = await collector.get_chart_data("005930", ChartInterval.DAY, use_cache=True)
    assert len(chart_data_2) == 5
    assert len(mock_client.get_chart_data_calls) == 1  # 여전히 1회

    # 캐시 무시 조회 (API 호출)
    chart_data_3 = await collector.get_chart_data("005930", ChartInterval.DAY, use_cache=False)
    assert len(chart_data_3) == 5
    assert len(mock_client.get_chart_data_calls) == 2  # 2회로 증가


@pytest.mark.asyncio
async def test_data_collector_timeout_detection(mock_client, mock_config, market_data_queue):
    """DataCollector 타임아웃 감지 테스트.

    검증:
    - 데이터 수신 타임아웃 임계값 확인
    - last_data_received_at 필드가 올바르게 업데이트되는지 확인
    """
    collector = DataCollector(
        config=mock_config,
        client=mock_client,
        market_data_queue=market_data_queue,
        stock_codes=["005930"],
        timeout_seconds=180  # 3분
    )

    # 초기 상태: 데이터 미수신
    assert collector.last_data_received_at is None

    # 시뮬레이션: 데이터 수신
    collector.last_data_received_at = datetime.now(tz=KST)

    # 통계 확인
    stats = collector.get_statistics()
    assert stats["last_data_received_at"] is not None
    assert stats["timeout_threshold"] == 180
    assert stats["seconds_since_last_data"] < 1  # 방금 받았으므로

    # 타임아웃 임계값 확인
    assert collector.timeout_seconds == 180


@pytest.mark.asyncio
async def test_data_collector_statistics(mock_client, mock_config, market_data_queue):
    """DataCollector 통계 반환 테스트.

    검증:
    - 통계 정보 반환
    - 캐시 통계 포함
    """
    collector = DataCollector(
        config=mock_config,
        client=mock_client,
        market_data_queue=market_data_queue,
        stock_codes=["005930", "000660", "035720"]
    )

    # 통계 조회
    stats = collector.get_statistics()

    assert stats["running"] is False
    assert stats["stock_count"] == 3
    assert stats["last_data_received_at"] is None
    assert "cache_stats" in stats

    # 캐시 통계
    cache_stats = stats["cache_stats"]
    assert cache_stats["size"] == 0
    assert cache_stats["max_size"] == 1000
    assert cache_stats["ttl_seconds"] == 5


@pytest.mark.asyncio
async def test_data_collector_update_stock_codes(mock_client, mock_config, market_data_queue):
    """DataCollector 종목 코드 동적 업데이트 테스트.

    검증:
    - 종목 코드 리스트 변경
    """
    collector = DataCollector(
        config=mock_config,
        client=mock_client,
        market_data_queue=market_data_queue,
        stock_codes=["005930"]
    )

    assert len(collector.stock_codes) == 1

    # 종목 코드 업데이트
    new_codes = ["005930", "000660", "035720"]
    collector.update_stock_codes(new_codes)

    assert len(collector.stock_codes) == 3
    assert "000660" in collector.stock_codes
    assert "035720" in collector.stock_codes
