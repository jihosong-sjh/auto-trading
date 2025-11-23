"""PositionService: 포지션 CRUD 및 평가 손익 계산 서비스."""

from decimal import Decimal
from typing import Dict, List, Optional, Protocol
from datetime import datetime

from ..models.position import Position
from ..models.stock import Stock
from ..utils.logger import get_logger

logger = get_logger(__name__)


class PositionProvider(Protocol):
    """포지션 정보를 제공하는 인터페이스.

    KiwoomClient 또는 KiwoomSimulator가 이 프로토콜을 구현합니다.
    """

    def get_positions(self) -> List[Position]:
        """현재 보유 중인 모든 포지션을 조회합니다.

        Returns:
            List[Position]: 보유 포지션 목록.
        """
        ...


class PriceProvider(Protocol):
    """주식 현재가를 제공하는 인터페이스.

    KiwoomClient 또는 KiwoomSimulator가 이 프로토콜을 구현합니다.
    """

    async def get_stock_price(self, stock_code: str) -> Stock:
        """종목의 현재가를 조회합니다.

        Args:
            stock_code: 종목코드.

        Returns:
            Stock: 종목 정보.
        """
        ...


class PositionService:
    """포지션 관리 서비스.

    사용자 계좌의 보유 포지션을 조회하고, 평가 손익을 계산합니다.

    Attributes:
        provider: 포지션 정보를 제공하는 KiwoomClient 또는 KiwoomSimulator.
        price_provider: 주식 현재가를 제공하는 KiwoomClient 또는 KiwoomSimulator.
    """

    def __init__(
        self,
        provider: PositionProvider,
        price_provider: Optional[PriceProvider] = None
    ):
        """PositionService 초기화.

        Args:
            provider: KiwoomClient 또는 KiwoomSimulator 인스턴스.
            price_provider: 가격 조회를 위한 인스턴스 (기본값: provider와 동일).
        """
        self.provider = provider
        self.price_provider = price_provider or provider

    def get_all_positions(self) -> List[Position]:
        """모든 보유 포지션을 조회합니다.

        Returns:
            List[Position]: 보유 포지션 목록.

        Example:
            >>> service = PositionService(kiwoom_client)
            >>> positions = service.get_all_positions()
            >>> for pos in positions:
            ...     print(f"{pos.stock_code}: {pos.quantity}주")
        """
        positions = self.provider.get_positions()
        logger.info(f"보유 포지션 조회 완료: {len(positions)}개")
        return positions

    def get_position_by_stock(self, stock_code: str) -> Optional[Position]:
        """특정 종목의 포지션을 조회합니다.

        Args:
            stock_code: 종목코드.

        Returns:
            Optional[Position]: 해당 종목의 포지션, 없으면 None.

        Example:
            >>> position = service.get_position_by_stock("005930")  # 삼성전자
            >>> if position:
            ...     print(f"보유 수량: {position.quantity}")
        """
        positions = self.get_all_positions()

        for position in positions:
            if position.stock_code == stock_code:
                logger.debug(f"포지션 찾음: {stock_code}, 수량={position.quantity}")
                return position

        logger.debug(f"포지션 없음: {stock_code}")
        return None

    def has_position(self, stock_code: str) -> bool:
        """특정 종목의 포지션 보유 여부를 확인합니다.

        Args:
            stock_code: 종목코드.

        Returns:
            bool: 포지션을 보유한 경우 True.

        Example:
            >>> if service.has_position("005930"):
            ...     print("삼성전자 보유 중")
        """
        return self.get_position_by_stock(stock_code) is not None

    def get_positions_by_strategy(self, strategy_name: str) -> List[Position]:
        """특정 전략으로 생성된 포지션들을 조회합니다.

        Args:
            strategy_name: 전략명.

        Returns:
            List[Position]: 해당 전략의 포지션 목록.

        Example:
            >>> positions = service.get_positions_by_strategy("GoldenCross")
            >>> print(f"골든크로스 전략 포지션: {len(positions)}개")
        """
        positions = self.get_all_positions()

        strategy_positions = [
            pos for pos in positions
            if pos.strategy_name == strategy_name
        ]

        logger.info(f"전략 '{strategy_name}' 포지션: {len(strategy_positions)}개")
        return strategy_positions

    def calculate_total_evaluation_amount(self) -> Decimal:
        """모든 포지션의 총 평가 금액을 계산합니다.

        Returns:
            Decimal: 총 평가 금액.

        Example:
            >>> total = service.calculate_total_evaluation_amount()
            >>> print(f"주식 평가액: {total}")
        """
        positions = self.get_all_positions()

        total = sum(
            position.evaluation_amount for position in positions
        )

        logger.debug(f"총 평가 금액: {total:.2f}")
        return total

    def calculate_total_unrealized_pnl(self) -> Decimal:
        """모든 포지션의 총 미실현 손익을 계산합니다.

        Returns:
            Decimal: 총 미실현 손익.

        Example:
            >>> pnl = service.calculate_total_unrealized_pnl()
            >>> print(f"미실현 손익: {pnl:+.2f}")
        """
        positions = self.get_all_positions()

        total_pnl = sum(
            position.unrealized_pnl for position in positions
        )

        logger.debug(f"총 미실현 손익: {total_pnl:+.2f}")
        return total_pnl

    def calculate_average_return_rate(self) -> Decimal:
        """모든 포지션의 평균 수익률을 계산합니다.

        Returns:
            Decimal: 평균 수익률 (0.05 = 5%).

        Example:
            >>> avg_return = service.calculate_average_return_rate()
            >>> print(f"평균 수익률: {avg_return * 100:.2f}%")
        """
        positions = self.get_all_positions()

        if not positions:
            return Decimal("0")

        total_return = sum(
            position.return_rate for position in positions
        )

        avg_return = total_return / len(positions)

        logger.debug(f"평균 수익률: {avg_return * 100:.2f}%")
        return avg_return

    async def update_position_prices(self) -> None:
        """모든 포지션의 현재가를 최신 가격으로 업데이트합니다.

        Example:
            >>> await service.update_position_prices()
            >>> positions = service.get_all_positions()
            >>> # 모든 포지션이 최신 가격으로 업데이트됨
        """
        positions = self.get_all_positions()

        logger.info(f"포지션 가격 업데이트 시작: {len(positions)}개")

        for position in positions:
            try:
                stock = await self.price_provider.get_stock_price(position.stock_code)
                position.update_price(stock.current_price)
                logger.debug(
                    f"{position.stock_code} 가격 업데이트: {stock.current_price}"
                )
            except Exception as e:
                logger.error(
                    f"{position.stock_code} 가격 업데이트 실패: {e}"
                )

    def get_position_concentration(self) -> Dict[str, Decimal]:
        """각 포지션의 집중도(비중)를 계산합니다.

        Returns:
            Dict[str, Decimal]: 종목코드 -> 집중도 (0.0 ~ 1.0).

        Example:
            >>> concentrations = service.get_position_concentration()
            >>> for code, ratio in concentrations.items():
            ...     print(f"{code}: {ratio * 100:.1f}%")
        """
        positions = self.get_all_positions()
        total_value = self.calculate_total_evaluation_amount()

        if total_value == 0:
            return {}

        concentrations = {
            position.stock_code: position.evaluation_amount / total_value
            for position in positions
        }

        logger.debug(f"포지션 집중도 계산 완료: {len(concentrations)}개")
        return concentrations

    def get_losing_positions(self) -> List[Position]:
        """손실 중인 포지션들을 조회합니다.

        Returns:
            List[Position]: 미실현 손익이 음수인 포지션 목록.

        Example:
            >>> losing = service.get_losing_positions()
            >>> print(f"손실 포지션: {len(losing)}개")
        """
        positions = self.get_all_positions()

        losing = [
            pos for pos in positions
            if pos.unrealized_pnl < 0
        ]

        logger.info(f"손실 포지션: {len(losing)}개")
        return losing

    def get_winning_positions(self) -> List[Position]:
        """수익 중인 포지션들을 조회합니다.

        Returns:
            List[Position]: 미실현 손익이 양수인 포지션 목록.

        Example:
            >>> winning = service.get_winning_positions()
            >>> print(f"수익 포지션: {len(winning)}개")
        """
        positions = self.get_all_positions()

        winning = [
            pos for pos in positions
            if pos.unrealized_pnl > 0
        ]

        logger.info(f"수익 포지션: {len(winning)}개")
        return winning

    def get_position_summary(self) -> dict:
        """포지션 요약 정보를 반환합니다.

        Returns:
            dict: 포지션 요약 (총 개수, 평가액, 손익, 수익률 등).

        Example:
            >>> summary = service.get_position_summary()
            >>> print(f"총 {summary['count']}개 포지션")
            >>> print(f"평가액: {summary['total_value']}")
            >>> print(f"손익: {summary['total_pnl']:+.2f}")
        """
        positions = self.get_all_positions()

        summary = {
            "count": len(positions),
            "total_value": self.calculate_total_evaluation_amount(),
            "total_pnl": self.calculate_total_unrealized_pnl(),
            "avg_return_rate": self.calculate_average_return_rate(),
            "winning_count": len(self.get_winning_positions()),
            "losing_count": len(self.get_losing_positions()),
        }

        logger.info(
            f"포지션 요약: {summary['count']}개, "
            f"평가액={summary['total_value']:.2f}, "
            f"손익={summary['total_pnl']:+.2f}"
        )

        return summary
