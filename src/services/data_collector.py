"""실시간 시장 데이터 수집 서비스.

T072-T075 구현:
- T072: DataCollector 인터페이스
- T073: StaggeredPricePoller (1초 간격, 종목별 분산 폴링)
- T074: 차트 데이터 캐싱 (30초 TTL, 최대 1000개, 1 req/sec 제약 대응)
- T075: 데이터 수신 타임아웃 감지 및 재연결 (3분 이상 데이터 없을 시 경고)
"""

import asyncio
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from ..config.settings import Settings
from ..models import ChartInterval, Stock
from ..models.chart_data import ChartData
from ..utils.logger import get_logger

KST = ZoneInfo("Asia/Seoul")
logger = get_logger(__name__)


class ChartDataCache:
    """차트 데이터 캐싱 클래스 (T074).

    30초 TTL, 최대 1000개 캐시를 구현합니다 (1 req/sec 제약 대응).
    LRU (Least Recently Used) 정책으로 캐시를 관리합니다.

    Attributes:
        ttl_seconds: 캐시 TTL (초).
        max_size: 최대 캐시 크기.
        cache: 캐시 저장소 (OrderedDict로 LRU 구현).
    """

    def __init__(self, ttl_seconds: int = 30, max_size: int = 1000):
        """차트 데이터 캐시 초기화.

        Args:
            ttl_seconds: 캐시 TTL (기본값: 30초, 1 req/sec 제약 대응).
            max_size: 최대 캐시 크기 (기본값: 1000개).
        """
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self.cache: OrderedDict[str, tuple[datetime, List[ChartData]]] = OrderedDict()

    def _make_key(self, stock_code: str, interval: ChartInterval) -> str:
        """캐시 키 생성.

        Args:
            stock_code: 종목코드.
            interval: 차트 주기.

        Returns:
            캐시 키 문자열.
        """
        return f"{stock_code}:{interval.value}"

    def get(self, stock_code: str, interval: ChartInterval) -> List[ChartData] | None:
        """캐시에서 차트 데이터 조회.

        Args:
            stock_code: 종목코드.
            interval: 차트 주기.

        Returns:
            캐시된 차트 데이터 리스트. 캐시 미스 시 None.
        """
        key = self._make_key(stock_code, interval)

        if key not in self.cache:
            return None

        cached_at, data = self.cache[key]

        # TTL 체크
        elapsed = (datetime.now(tz=KST) - cached_at).total_seconds()
        if elapsed > self.ttl_seconds:
            # 만료된 캐시 제거
            del self.cache[key]
            logger.debug(f"Cache expired for {key} (elapsed: {elapsed:.2f}s)")
            return None

        # LRU: 접근 시 맨 뒤로 이동
        self.cache.move_to_end(key)
        logger.debug(f"Cache hit for {key} (age: {elapsed:.2f}s)")
        return data

    def set(self, stock_code: str, interval: ChartInterval, data: List[ChartData]) -> None:
        """캐시에 차트 데이터 저장.

        Args:
            stock_code: 종목코드.
            interval: 차트 주기.
            data: 저장할 차트 데이터 리스트.
        """
        key = self._make_key(stock_code, interval)

        # 최대 크기 초과 시 가장 오래된 항목 제거 (LRU)
        if len(self.cache) >= self.max_size and key not in self.cache:
            oldest_key = next(iter(self.cache))
            del self.cache[oldest_key]
            logger.debug(f"Cache full, evicted oldest entry: {oldest_key}")

        # 캐시 저장
        self.cache[key] = (datetime.now(tz=KST), data)
        logger.debug(f"Cache set for {key} ({len(data)} items)")

    def clear(self) -> None:
        """캐시 전체 삭제."""
        self.cache.clear()
        logger.info("Chart data cache cleared")

    def get_stats(self) -> Dict[str, int]:
        """캐시 통계 반환.

        Returns:
            캐시 통계 딕셔너리.
        """
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "ttl_seconds": self.ttl_seconds
        }


class PriceCache:
    """적응형 TTL을 가진 가격 데이터 캐싱 클래스.

    시장 변동성과 API 부하에 따라 TTL을 동적으로 조정합니다.
    1 req/sec 제약 환경에서 API 호출을 최소화합니다.

    Attributes:
        base_ttl: 기본 TTL (초).
        max_ttl: 최대 TTL (초).
        min_ttl: 최소 TTL (초).
        cache: 가격 캐시 저장소.
        volatility_threshold: 변동성 임계값 (%).
    """

    def __init__(
        self,
        base_ttl: int = 2,
        max_ttl: int = 10,
        min_ttl: int = 1
    ):
        """적응형 가격 캐시 초기화.

        Args:
            base_ttl: 기본 TTL (기본값: 2초).
            max_ttl: 최대 TTL (기본값: 10초).
            min_ttl: 최소 TTL (기본값: 1초).
        """
        self.base_ttl = base_ttl
        self.max_ttl = max_ttl
        self.min_ttl = min_ttl
        self.cache: Dict[str, tuple[datetime, float, float]] = {}  # (cached_at, price, volatility)
        self.volatility_threshold = 1.0  # 1% 변동성을 기준으로 함

    def _calculate_volatility(self, stock_code: str, current_price: float) -> float:
        """가격 변동성 계산.

        Args:
            stock_code: 종목코드.
            current_price: 현재 가격.

        Returns:
            변동성 (%).
        """
        if stock_code not in self.cache:
            return 0.0

        _, prev_price, _ = self.cache[stock_code]
        if prev_price <= 0:
            return 0.0

        volatility = abs((current_price - prev_price) / prev_price * 100)
        return volatility

    def _get_adaptive_ttl(self, volatility: float) -> int:
        """변동성에 따른 적응형 TTL 계산.

        Args:
            volatility: 가격 변동성 (%).

        Returns:
            조정된 TTL (초).
        """
        if volatility > self.volatility_threshold * 2:
            # 높은 변동성: 짧은 TTL
            return self.min_ttl
        elif volatility > self.volatility_threshold:
            # 중간 변동성: 기본 TTL
            return self.base_ttl
        else:
            # 낮은 변동성: 긴 TTL (API 부하 최소화)
            return self.max_ttl

    def get(self, stock_code: str) -> float | None:
        """캐시에서 가격 조회.

        Args:
            stock_code: 종목코드.

        Returns:
            캐시된 가격. 캐시 미스 시 None.
        """
        if stock_code not in self.cache:
            logger.debug(f"Price cache miss for {stock_code}")
            return None

        cached_at, price, volatility = self.cache[stock_code]
        ttl = self._get_adaptive_ttl(volatility)

        elapsed = (datetime.now(tz=KST) - cached_at).total_seconds()
        if elapsed > ttl:
            logger.debug(f"Price cache expired for {stock_code} (elapsed: {elapsed:.2f}s, ttl: {ttl}s)")
            del self.cache[stock_code]
            return None

        logger.debug(f"Price cache hit for {stock_code} (age: {elapsed:.2f}s, ttl: {ttl}s, volatility: {volatility:.2f}%)")
        return price

    def set(self, stock_code: str, price: float) -> None:
        """캐시에 가격 저장.

        Args:
            stock_code: 종목코드.
            price: 저장할 가격.
        """
        volatility = self._calculate_volatility(stock_code, price)
        self.cache[stock_code] = (datetime.now(tz=KST), price, volatility)

        ttl = self._get_adaptive_ttl(volatility)
        logger.debug(f"Price cached for {stock_code}: {price:,.0f} (volatility: {volatility:.2f}%, ttl: {ttl}s)")

    def clear(self) -> None:
        """캐시 전체 삭제."""
        self.cache.clear()
        logger.info("Price cache cleared")

    def get_stats(self) -> Dict[str, Any]:
        """캐시 통계 정보 반환.

        Returns:
            캐시 통계 딕셔너리.
        """
        return {
            "size": len(self.cache),
            "base_ttl": self.base_ttl,
            "max_ttl": self.max_ttl,
            "min_ttl": self.min_ttl,
            "stocks": list(self.cache.keys())
        }


class StaggeredPricePoller:
    """종목별 분산 폴링 클래스 (T073).

    1초 간격으로 종목들을 균등하게 분산하여 폴링합니다.
    예: 3개 종목이면 0ms, 333ms, 666ms에 각각 폴링하여 API 부하 분산.

    Attributes:
        client: Kiwoom API 클라이언트.
        stock_codes: 감시 대상 종목 코드 리스트.
        interval_seconds: 전체 폴링 주기 (기본값: 1초).
        market_data_queue: 수집된 데이터를 전달할 큐.
        running: 폴링 실행 여부.
        tasks: 각 종목별 폴링 태스크 리스트.
    """

    def __init__(
        self,
        client: Any,
        stock_codes: List[str],
        market_data_queue: asyncio.Queue,
        interval_seconds: float = 1.0,
        price_cache: PriceCache | None = None
    ):
        """StaggeredPricePoller 초기화.

        Args:
            client: Kiwoom API 클라이언트.
            stock_codes: 감시 대상 종목 코드 리스트.
            market_data_queue: 수집된 데이터를 전달할 큐.
            interval_seconds: 전체 폴링 주기 (기본값: 1초).
            price_cache: 가격 캐시 (선택사항, 1 req/sec 제약 대응).
        """
        self.client = client
        self.stock_codes = stock_codes
        self.interval_seconds = interval_seconds
        self.market_data_queue = market_data_queue
        self.price_cache = price_cache

        self.running = False
        self.tasks: List[asyncio.Task] = []

    async def start(self) -> None:
        """폴링 시작.

        각 종목을 균등한 간격으로 분산하여 폴링 태스크를 생성합니다.
        """
        if self.running:
            logger.warning("StaggeredPricePoller is already running")
            return

        self.running = True
        num_stocks = len(self.stock_codes)

        if num_stocks == 0:
            logger.warning("No stock codes to poll")
            return

        # 종목별 지연 시간 계산 (균등 분산)
        stagger_delay = self.interval_seconds / num_stocks if num_stocks > 1 else 0

        logger.info(
            f"Starting StaggeredPricePoller: {num_stocks} stocks, "
            f"interval={self.interval_seconds}s, stagger={stagger_delay:.3f}s"
        )

        for idx, stock_code in enumerate(self.stock_codes):
            initial_delay = idx * stagger_delay
            task = asyncio.create_task(
                self._poll_stock(stock_code, initial_delay)
            )
            self.tasks.append(task)

    async def stop(self) -> None:
        """폴링 중지.

        모든 폴링 태스크를 취소하고 종료를 기다립니다.
        """
        if not self.running:
            return

        self.running = False
        logger.info(f"Stopping StaggeredPricePoller ({len(self.tasks)} tasks)")

        # 모든 태스크 취소
        for task in self.tasks:
            task.cancel()

        # 모든 태스크 종료 대기
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        logger.info("StaggeredPricePoller stopped")

    async def _poll_stock(self, stock_code: str, initial_delay: float) -> None:
        """개별 종목 폴링 루프.

        Args:
            stock_code: 종목코드.
            initial_delay: 초기 지연 시간 (분산 폴링용).
        """
        # 초기 지연 (분산 폴링)
        if initial_delay > 0:
            await asyncio.sleep(initial_delay)

        logger.debug(f"Started polling for {stock_code} (delay: {initial_delay:.3f}s)")

        try:
            while self.running:
                try:
                    # 캐시 확인 (1 req/sec 제약 대응)
                    if self.price_cache:
                        cached_price = self.price_cache.get(stock_code)
                        if cached_price is not None:
                            # 캐시 히트: API 호출 없이 캐시된 데이터 사용
                            from ..models import Stock
                            stock = Stock(
                                code=stock_code,
                                name="",  # 캐시에서는 이름 정보 없음
                                current_price=cached_price,
                                change=0.0,
                                change_rate=0.0,
                                volume=0
                            )
                            await self.market_data_queue.put(stock)
                            logger.debug(f"[CACHE HIT] {stock_code}: {cached_price:,.0f}")
                        else:
                            # 캐시 미스: API 호출
                            stock = await self.client.get_stock_price(stock_code)
                            # 캐시에 저장
                            self.price_cache.set(stock_code, stock.current_price)
                            await self.market_data_queue.put(stock)
                            logger.debug(f"[API CALL] {stock_code}: {stock.current_price:,.0f}")
                    else:
                        # 캐시 없음: 기존 로직
                        stock = await self.client.get_stock_price(stock_code)
                        await self.market_data_queue.put(stock)
                        logger.debug(f"Polled {stock_code}: {stock.current_price}")

                except Exception as e:
                    logger.error(f"Error polling {stock_code}: {e}")

                # 다음 폴링까지 대기
                await asyncio.sleep(self.interval_seconds)

        except asyncio.CancelledError:
            logger.debug(f"Polling cancelled for {stock_code}")
            raise


class SmartPricePoller:
    """우선순위 기반 스마트 폴링 클래스.

    포지션 보유 여부와 시그널 근접도를 기반으로 폴링 빈도를 조정합니다.
    1 req/sec 제약 환경에서 중요한 종목을 우선적으로 모니터링합니다.

    Attributes:
        client: Kiwoom API 클라이언트.
        stock_codes: 감시 대상 종목 코드 리스트.
        market_data_queue: 수집된 데이터를 전달할 큐.
        price_cache: 가격 캐시.
        positions: 현재 포지션 정보 (stock_code -> position).
        signal_scores: 시그널 점수 (stock_code -> score).
    """

    def __init__(
        self,
        client: Any,
        stock_codes: List[str],
        market_data_queue: asyncio.Queue,
        price_cache: PriceCache | None = None
    ):
        """SmartPricePoller 초기화.

        Args:
            client: Kiwoom API 클라이언트.
            stock_codes: 감시 대상 종목 코드 리스트.
            market_data_queue: 수집된 데이터를 전달할 큐.
            price_cache: 가격 캐시.
        """
        self.client = client
        self.stock_codes = stock_codes
        self.market_data_queue = market_data_queue
        self.price_cache = price_cache
        self.running = False
        self.tasks: List[asyncio.Task] = []

        # 우선순위 정보
        self.positions: Dict[str, Any] = {}  # 포지션 정보
        self.signal_scores: Dict[str, float] = {}  # 시그널 점수 (0.0 ~ 1.0)

    def update_positions(self, positions: Dict[str, Any]) -> None:
        """포지션 정보 업데이트.

        Args:
            positions: 포지션 딕셔너리 (stock_code -> position).
        """
        self.positions = positions
        logger.debug(f"Updated positions for {len(positions)} stocks")

    def update_signal_scores(self, scores: Dict[str, float]) -> None:
        """시그널 점수 업데이트.

        Args:
            scores: 시그널 점수 딕셔너리 (stock_code -> score).
        """
        self.signal_scores = scores
        logger.debug(f"Updated signal scores: {scores}")

    def _get_polling_interval(self, stock_code: str) -> float:
        """종목별 폴링 간격 계산 (우선순위 기반).

        Args:
            stock_code: 종목코드.

        Returns:
            폴링 간격 (초).
        """
        # 포지션 있음: 1초 간격 (최우선)
        if stock_code in self.positions:
            return 1.0

        # 시그널 점수 높음 (> 0.7): 5초 간격
        signal_score = self.signal_scores.get(stock_code, 0.0)
        if signal_score > 0.7:
            return 5.0

        # 시그널 점수 중간 (0.3 ~ 0.7): 15초 간격
        if signal_score > 0.3:
            return 15.0

        # 시그널 점수 낮음 (< 0.3): 30초 간격
        return 30.0

    async def _poll_stock_smart(self, stock_code: str) -> None:
        """개별 종목 스마트 폴링 루프.

        Args:
            stock_code: 종목코드.
        """
        logger.debug(f"Started smart polling for {stock_code}")

        try:
            while self.running:
                try:
                    # 동적 폴링 간격 계산
                    interval = self._get_polling_interval(stock_code)

                    # 캐시 확인
                    if self.price_cache:
                        cached_price = self.price_cache.get(stock_code)
                        if cached_price is not None:
                            # 캐시 히트
                            from ..models import Stock
                            stock = Stock(
                                code=stock_code,
                                name="",
                                current_price=cached_price,
                                change=0.0,
                                change_rate=0.0,
                                volume=0
                            )
                            await self.market_data_queue.put(stock)
                            logger.debug(f"[SMART CACHE HIT] {stock_code}: {cached_price:,.0f} (interval: {interval}s)")
                        else:
                            # 캐시 미스: API 호출
                            stock = await self.client.get_stock_price(stock_code)
                            self.price_cache.set(stock_code, stock.current_price)
                            await self.market_data_queue.put(stock)
                            logger.debug(f"[SMART API CALL] {stock_code}: {stock.current_price:,.0f} (interval: {interval}s)")
                    else:
                        # 캐시 없음
                        stock = await self.client.get_stock_price(stock_code)
                        await self.market_data_queue.put(stock)
                        logger.debug(f"[SMART POLL] {stock_code}: {stock.current_price} (interval: {interval}s)")

                except Exception as e:
                    logger.error(f"Error in smart polling {stock_code}: {e}")

                # 동적 간격으로 대기
                interval = self._get_polling_interval(stock_code)
                await asyncio.sleep(interval)

        except asyncio.CancelledError:
            logger.debug(f"Smart polling cancelled for {stock_code}")
            raise

    async def start(self) -> None:
        """스마트 폴링 시작."""
        if self.running:
            logger.warning("SmartPricePoller is already running")
            return

        self.running = True

        # 각 종목별 폴링 태스크 생성
        for stock_code in self.stock_codes:
            task = asyncio.create_task(self._poll_stock_smart(stock_code))
            self.tasks.append(task)

        logger.info(f"Started SmartPricePoller for {len(self.stock_codes)} stocks")

    async def stop(self) -> None:
        """스마트 폴링 중단."""
        if not self.running:
            logger.warning("SmartPricePoller is not running")
            return

        self.running = False

        # 모든 태스크 취소
        for task in self.tasks:
            task.cancel()

        # 모든 태스크 완료 대기
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()

        logger.info("Stopped SmartPricePoller")

    def get_stats(self) -> Dict[str, Any]:
        """폴링 통계 정보 반환.

        Returns:
            통계 딕셔너리.
        """
        stats = {}
        for stock_code in self.stock_codes:
            interval = self._get_polling_interval(stock_code)
            priority = "HIGH" if stock_code in self.positions else \
                      "MEDIUM" if self.signal_scores.get(stock_code, 0.0) > 0.3 else \
                      "LOW"
            stats[stock_code] = {
                "interval": interval,
                "priority": priority,
                "has_position": stock_code in self.positions,
                "signal_score": self.signal_scores.get(stock_code, 0.0)
            }
        return stats


class DataCollector:
    """실시간 시장 데이터 수집 서비스 (T072-T075).

    주요 기능:
    - T072: DataCollector 인터페이스 구현
    - T073: StaggeredPricePoller를 사용한 1초 간격 분산 폴링
    - T074: 차트 데이터 5초 TTL 캐싱 (최대 1000개)
    - T075: 데이터 수신 타임아웃 감지 (3분) 및 재연결 로직

    Attributes:
        config: 시스템 설정.
        client: Kiwoom API 클라이언트.
        market_data_queue: 수집된 시세 데이터를 전달할 큐.
        stock_codes: 감시 대상 종목 코드 리스트.
        chart_cache: 차트 데이터 캐시.
        price_poller: 분산 폴링 인스턴스.
        last_data_received_at: 마지막 데이터 수신 시간.
        timeout_seconds: 타임아웃 임계값 (기본값: 180초 = 3분).
        running: 실행 여부.
        monitor_task: 타임아웃 모니터링 태스크.
    """

    def __init__(
        self,
        config: Settings,
        client: Any,
        market_data_queue: asyncio.Queue,
        stock_codes: List[str] | None = None,
        timeout_seconds: int = 180
    ):
        """DataCollector 초기화.

        Args:
            config: 시스템 설정.
            client: Kiwoom API 클라이언트.
            market_data_queue: 수집된 시세 데이터를 전달할 큐.
            stock_codes: 감시 대상 종목 코드 리스트 (None이면 설정에서 로드).
            timeout_seconds: 데이터 수신 타임아웃 (기본값: 180초 = 3분).
        """
        self.config = config
        self.client = client
        self.market_data_queue = market_data_queue
        self.stock_codes = stock_codes or []
        self.timeout_seconds = timeout_seconds

        # T074: 차트 데이터 캐시 (30초 TTL, 최대 1000개, 1 req/sec 제약 대응)
        self.chart_cache = ChartDataCache(ttl_seconds=30, max_size=1000)

        # 가격 캐시 추가 (적응형 TTL, 1 req/sec 제약 대응)
        self.price_cache = PriceCache(base_ttl=2, max_ttl=10, min_ttl=1)

        # T073: 분산 폴링 인스턴스
        self.price_poller = StaggeredPricePoller(
            client=client,
            stock_codes=self.stock_codes,
            market_data_queue=market_data_queue,
            interval_seconds=1.0,
            price_cache=self.price_cache  # PriceCache 전달
        )

        # 스마트 폴링 인스턴스 (선택적 사용)
        self.smart_poller: SmartPricePoller | None = None
        self.use_smart_polling = False  # 스마트 폴링 사용 여부

        # T075: 타임아웃 감지용
        self.last_data_received_at: datetime | None = None
        self.running = False
        self.monitor_task: asyncio.Task | None = None

    def update_stock_codes(self, stock_codes: List[str]) -> None:
        """감시 대상 종목 코드 업데이트.

        실행 중에도 종목 리스트를 동적으로 변경할 수 있습니다.

        Args:
            stock_codes: 새로운 종목 코드 리스트.
        """
        self.stock_codes = stock_codes
        # Update StaggeredPricePoller's stock codes as well
        if self.price_poller:
            self.price_poller.stock_codes = stock_codes
        # Update SmartPricePoller's stock codes if active
        if self.smart_poller:
            self.smart_poller.stock_codes = stock_codes
        logger.info(f"Updated stock codes: {len(stock_codes)} stocks")

    def enable_smart_polling(self, enabled: bool = True) -> None:
        """스마트 폴링 활성화/비활성화.

        Args:
            enabled: True면 스마트 폴링 활성화, False면 기본 폴링 사용.
        """
        self.use_smart_polling = enabled
        if enabled and not self.smart_poller:
            # 스마트 폴링 인스턴스 생성
            self.smart_poller = SmartPricePoller(
                client=self.client,
                stock_codes=self.stock_codes,
                market_data_queue=self.market_data_queue,
                price_cache=self.price_cache
            )
            logger.info("Smart polling enabled")
        elif not enabled:
            logger.info("Smart polling disabled, using standard polling")

    def update_positions(self, positions: Dict[str, Any]) -> None:
        """포지션 정보 업데이트 (스마트 폴링용).

        Args:
            positions: 포지션 딕셔너리 (stock_code -> position).
        """
        if self.smart_poller:
            self.smart_poller.update_positions(positions)
            logger.debug(f"Updated positions for smart polling: {len(positions)} stocks")

    def update_signal_scores(self, scores: Dict[str, float]) -> None:
        """시그널 점수 업데이트 (스마트 폴링용).

        Args:
            scores: 시그널 점수 딕셔너리 (stock_code -> score).
        """
        if self.smart_poller:
            self.smart_poller.update_signal_scores(scores)
            logger.debug(f"Updated signal scores for smart polling: {scores}")

    async def get_chart_data(
        self,
        stock_code: str,
        interval: ChartInterval = ChartInterval.DAY,
        use_cache: bool = True
    ) -> List[ChartData]:
        """차트 데이터 조회 (캐싱 지원).

        Args:
            stock_code: 종목코드.
            interval: 차트 주기.
            use_cache: 캐시 사용 여부 (기본값: True).

        Returns:
            차트 데이터 리스트.
        """
        # 캐시 조회
        if use_cache:
            cached_data = self.chart_cache.get(stock_code, interval)
            if cached_data is not None:
                return cached_data

        # API 호출
        logger.debug(f"Fetching chart data from API: {stock_code}, {interval.value}")
        chart_data = await self.client.get_chart_data(stock_code, interval=interval)

        # 캐시 저장
        if use_cache:
            self.chart_cache.set(stock_code, interval, chart_data)

        return chart_data

    async def run(self) -> None:
        """데이터 수집 루프 실행.

        T073 StaggeredPricePoller를 시작하고,
        T075 타임아웃 모니터링을 실행합니다.
        """
        if self.running:
            logger.warning("DataCollector is already running")
            return

        self.running = True
        logger.info(
            f"DataCollector started: {len(self.stock_codes)} stocks, "
            f"timeout={self.timeout_seconds}s"
        )

        try:
            # T073: 폴링 시작 (스마트 폴링 또는 기본 폴링)
            if self.use_smart_polling and self.smart_poller:
                await self.smart_poller.start()
                logger.info("Using SmartPricePoller for data collection")
            else:
                await self.price_poller.start()
                logger.info("Using StaggeredPricePoller for data collection")

            # T075: 타임아웃 모니터링 시작
            self.monitor_task = asyncio.create_task(self._monitor_timeout())

            # 데이터 수신 루프
            while self.running:
                try:
                    # 큐에서 데이터 수신 대기 (1초 타임아웃)
                    stock = await asyncio.wait_for(
                        self.market_data_queue.get(),
                        timeout=1.0
                    )

                    # T075: 마지막 데이터 수신 시간 업데이트
                    self.last_data_received_at = datetime.now(tz=KST)

                    # 여기서 추가 처리 가능 (예: 전략 엔진으로 전달)
                    logger.debug(f"Received market data: {stock.stock_code}")

                except asyncio.TimeoutError:
                    # 큐에 데이터 없음 (정상 동작)
                    continue

                except Exception as e:
                    logger.error(f"Error in data collection loop: {e}")
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            logger.info("DataCollector cancelled")
            raise

        finally:
            await self._cleanup()

    async def stop(self) -> None:
        """데이터 수집 중지."""
        if not self.running:
            return

        logger.info("Stopping DataCollector")
        self.running = False

        # 정리 작업은 run()의 finally에서 수행

    async def _cleanup(self) -> None:
        """정리 작업."""
        self.running = False

        # T073: 폴링 중지 (스마트 폴링 또는 기본 폴링)
        if self.use_smart_polling and self.smart_poller:
            await self.smart_poller.stop()
        else:
            await self.price_poller.stop()

        # T075: 모니터링 태스크 취소
        if self.monitor_task and not self.monitor_task.done():
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass

        logger.info("DataCollector stopped and cleaned up")

    async def _monitor_timeout(self) -> None:
        """데이터 수신 타임아웃 모니터링 (T075).

        3분 이상 데이터를 수신하지 못하면 경고 로그를 출력하고,
        재연결을 시도합니다.
        """
        logger.info(f"Timeout monitor started (threshold: {self.timeout_seconds}s)")

        try:
            while self.running:
                await asyncio.sleep(10)  # 10초마다 체크

                if self.last_data_received_at is None:
                    # 아직 데이터를 한 번도 받지 못함
                    logger.debug("No data received yet")
                    continue

                # 마지막 데이터 수신 이후 경과 시간 계산
                elapsed = (datetime.now(tz=KST) - self.last_data_received_at).total_seconds()

                if elapsed > self.timeout_seconds:
                    logger.warning(
                        f"Data reception timeout detected! "
                        f"No data for {elapsed:.0f}s (threshold: {self.timeout_seconds}s)"
                    )

                    # 재연결 시도
                    await self._attempt_reconnect()

                    # 재연결 후 타이머 리셋
                    self.last_data_received_at = datetime.now(tz=KST)

                elif elapsed > self.timeout_seconds * 0.8:
                    # 80% 도달 시 경고
                    logger.warning(
                        f"Approaching data timeout: {elapsed:.0f}s / {self.timeout_seconds}s"
                    )

        except asyncio.CancelledError:
            logger.debug("Timeout monitor cancelled")
            raise

        except Exception as e:
            logger.error(f"Error in timeout monitor: {e}")

    async def _attempt_reconnect(self) -> None:
        """API 재연결 시도 (T075).

        클라이언트가 재연결 메서드를 제공하는 경우 호출합니다.
        """
        logger.info("Attempting to reconnect to API")

        try:
            # KiwoomClient에 reconnect 메서드가 있으면 호출
            if hasattr(self.client, "connect"):
                await self.client.connect()
                logger.info("Reconnection successful")
            else:
                logger.warning("Client does not support reconnection")

        except Exception as e:
            logger.error(f"Reconnection failed: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """데이터 수집 통계 반환.

        Returns:
            통계 정보 딕셔너리.
        """
        stats = {
            "running": self.running,
            "stock_count": len(self.stock_codes),
            "last_data_received_at": self.last_data_received_at.isoformat() if self.last_data_received_at else None,
            "cache_stats": self.chart_cache.get_stats()
        }

        if self.last_data_received_at:
            elapsed = (datetime.now(tz=KST) - self.last_data_received_at).total_seconds()
            stats["seconds_since_last_data"] = int(elapsed)
            stats["timeout_threshold"] = self.timeout_seconds

        return stats
