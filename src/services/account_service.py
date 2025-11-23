"""AccountService: 계좌 정보 조회, 업데이트, 일일 손익 계산 서비스."""

from decimal import Decimal
from typing import Optional, Protocol
from datetime import datetime

from ..models.account import Account
from ..utils.logger import get_logger

logger = get_logger(__name__)


class AccountProvider(Protocol):
    """계좌 정보를 제공하는 인터페이스.
    
    KiwoomClient 또는 KiwoomSimulator가 이 프로토콜을 구현합니다.
    """

    async def get_account(self) -> Account:
        """계좌 정보를 조회합니다.
        
        Returns:
            Account: 계좌 정보.
        """
        ...


class AccountService:
    """계좌 상태 관리 서비스.
    
    사용자 계좌의 잔고, 평가액, 손익을 조회하고 업데이트합니다.
    
    Attributes:
        provider: 계좌 정보를 제공하는 KiwoomClient 또는 KiwoomSimulator.
        cached_account: 캐시된 계좌 정보.
    """

    def __init__(self, provider: AccountProvider):
        """AccountService 초기화.
        
        Args:
            provider: KiwoomClient 또는 KiwoomSimulator 인스턴스.
        """
        self.provider = provider
        self.cached_account: Optional[Account] = None
        self._daily_pnl_reset_date: Optional[datetime] = None

    async def get_account(self, refresh: bool = False) -> Account:
        """계좌 정보를 조회합니다.
        
        Args:
            refresh: True이면 캐시를 무시하고 최신 정보를 가져옵니다.
        
        Returns:
            Account: 계좌 정보.
        
        Example:
            >>> service = AccountService(kiwoom_client)
            >>> account = await service.get_account()
            >>> print(f"예수금: {account.cash_balance}")
        """
        if refresh or self.cached_account is None:
            self.cached_account = await self.provider.get_account()
            logger.info(
                f"계좌 정보 조회 완료: {self.cached_account.account_number}, "
                f"예수금={self.cached_account.cash_balance}, "
                f"총 평가액={self.cached_account.total_asset_value}"
            )
        
        return self.cached_account

    async def refresh_account(self) -> Account:
        """계좌 정보를 강제로 갱신합니다.
        
        Returns:
            Account: 최신 계좌 정보.
        """
        return await self.get_account(refresh=True)

    async def update_daily_pnl(self, pnl_change: Decimal) -> None:
        """당일 손익을 업데이트합니다.
        
        Args:
            pnl_change: 손익 변동액 (양수=이익, 음수=손실).
        
        Raises:
            RuntimeError: 계좌 정보가 없을 경우.
        
        Example:
            >>> await service.update_daily_pnl(Decimal("50000"))  # 5만원 이익
        """
        if self.cached_account is None:
            raise RuntimeError("계좌 정보가 없습니다. get_account()를 먼저 호출하세요.")
        
        # 날짜가 바뀌면 일일 손익 초기화
        now = datetime.now(self.cached_account.updated_at.tzinfo)
        if self._daily_pnl_reset_date is None:
            self._daily_pnl_reset_date = now.date()
        elif now.date() > self._daily_pnl_reset_date:
            logger.info(f"날짜 변경 감지: {self._daily_pnl_reset_date} -> {now.date()}, 일일 손익 초기화")
            self.cached_account.daily_pnl = Decimal("0")
            self._daily_pnl_reset_date = now.date()
        
        self.cached_account.daily_pnl += pnl_change
        logger.info(f"당일 손익 업데이트: {pnl_change:+.2f}, 누적={self.cached_account.daily_pnl:.2f}")

    async def calculate_daily_pnl(self, positions_unrealized_pnl: Decimal) -> Decimal:
        """당일 손익을 계산합니다.
        
        Args:
            positions_unrealized_pnl: 현재 보유 포지션의 미실현 손익 합계.
        
        Returns:
            Decimal: 당일 손익 (실현 손익 + 미실현 손익).
        
        Example:
            >>> unrealized = sum(pos.unrealized_pnl for pos in positions)
            >>> daily_pnl = await service.calculate_daily_pnl(unrealized)
        """
        account = await self.get_account()
        
        # 당일 손익 = 현재 일일 손익 (실현) + 미실현 손익
        # NOTE: 실제 환경에서는 당일 체결된 주문의 실현 손익만 계산해야 함
        total_daily_pnl = account.daily_pnl + positions_unrealized_pnl
        
        logger.debug(
            f"당일 손익 계산: 실현={account.daily_pnl:.2f}, "
            f"미실현={positions_unrealized_pnl:.2f}, "
            f"합계={total_daily_pnl:.2f}"
        )
        
        return total_daily_pnl

    async def is_daily_loss_limit_exceeded(self) -> bool:
        """일일 손실 한도 초과 여부를 확인합니다.
        
        Returns:
            bool: 일일 손실 한도를 초과한 경우 True.
        
        Example:
            >>> if await service.is_daily_loss_limit_exceeded():
            ...     print("경고: 일일 손실 한도 초과!")
        """
        account = await self.get_account()
        exceeded = account.is_daily_loss_limit_exceeded()
        
        if exceeded:
            logger.warning(
                f"일일 손실 한도 초과! 당일 손익={account.daily_pnl:.2f}, "
                f"한도={-account.daily_loss_limit:.2f}"
            )
        
        return exceeded

    async def get_available_cash(self) -> Decimal:
        """매수 가능한 현금(예수금)을 반환합니다.
        
        Returns:
            Decimal: 사용 가능한 예수금.
        
        Example:
            >>> available = await service.get_available_cash()
            >>> print(f"매수 가능 금액: {available}")
        """
        account = await self.get_account()
        return account.cash_balance

    async def get_total_asset_value(self) -> Decimal:
        """총 평가 금액을 반환합니다.
        
        Returns:
            Decimal: 총 평가 금액 (예수금 + 주식 평가액).
        
        Example:
            >>> total = await service.get_total_asset_value()
            >>> print(f"총 자산: {total}")
        """
        account = await self.get_account()
        return account.total_asset_value

    async def get_total_pnl(self) -> Decimal:
        """총 손익을 반환합니다.
        
        Returns:
            Decimal: 총 손익 (실현 + 미실현).
        
        Example:
            >>> pnl = await service.get_total_pnl()
            >>> print(f"총 손익: {pnl:+.2f}")
        """
        account = await self.get_account()
        return account.total_pnl

    def clear_cache(self) -> None:
        """캐시된 계좌 정보를 삭제합니다.
        
        Example:
            >>> service.clear_cache()
            >>> account = await service.get_account()  # 새로 조회됨
        """
        logger.debug("계좌 정보 캐시 삭제")
        self.cached_account = None
