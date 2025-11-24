"""AccountService 단위 테스트."""

import pytest
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo

from src.models.account import Account
from src.services.account_service import AccountService

KST = ZoneInfo("Asia/Seoul")


class FakeAccountProvider:
    """테스트용 가짜 AccountProvider.

    실제 API 호출 없이 계좌 정보를 반환합니다.
    """

    def __init__(self, initial_account: Account):
        """FakeAccountProvider 초기화.

        Args:
            initial_account: 초기 계좌 정보.
        """
        self.account = initial_account

    async def get_account(self) -> Account:
        """계좌 정보를 반환합니다.

        Returns:
            Account: 계좌 정보 복사본.
        """
        # NOTE: 매번 새로운 인스턴스를 반환 (실제 API 동작과 유사)
        return Account(
            account_number=self.account.account_number,
            name=self.account.name,
            cash_balance=self.account.cash_balance,
            total_asset_value=self.account.total_asset_value,
            total_pnl=self.account.total_pnl,
            daily_pnl=self.account.daily_pnl,
            daily_loss_limit=self.account.daily_loss_limit,
            updated_at=self.account.updated_at
        )


@pytest.fixture
def sample_account():
    """테스트용 샘플 계좌."""
    return Account(
        account_number="12345678",
        name="테스트 계좌",
        cash_balance=Decimal("10000000.00"),  # 1천만원
        total_asset_value=Decimal("15000000.00"),  # 1천5백만원
        total_pnl=Decimal("500000.00"),  # 50만원 수익
        daily_pnl=Decimal("0.00"),
        daily_loss_limit=Decimal("750000.00"),  # 75만원 손실 한도
        updated_at=datetime.now(tz=KST)
    )


@pytest.fixture
def account_service(sample_account):
    """테스트용 AccountService 인스턴스."""
    provider = FakeAccountProvider(sample_account)
    return AccountService(provider)


@pytest.mark.asyncio
async def test_get_account_첫_조회(account_service, sample_account):
    """계좌 정보 첫 조회 시 캐시에 저장되는지 확인."""
    # When: 계좌 정보 조회
    account = await account_service.get_account()
    
    # Then: 계좌 정보가 반환되고 캐시에 저장됨
    assert account.account_number == "12345678"
    assert account.cash_balance == Decimal("10000000.00")
    assert account_service.cached_account is not None


@pytest.mark.asyncio
async def test_get_account_캐시_사용(account_service, sample_account):
    """두 번째 조회 시 캐시를 사용하는지 확인."""
    # Given: 첫 번째 조회로 캐시에 저장
    await account_service.get_account()
    
    # 계좌 잔고를 변경
    sample_account.cash_balance = Decimal("5000000.00")
    
    # When: 두 번째 조회 (refresh=False)
    account = await account_service.get_account(refresh=False)
    
    # Then: 캐시된 값(1천만원)이 반환됨
    assert account.cash_balance == Decimal("10000000.00")


@pytest.mark.asyncio
async def test_get_account_강제_갱신(account_service, sample_account):
    """refresh=True 시 최신 정보를 가져오는지 확인."""
    # Given: 첫 번째 조회로 캐시에 저장
    await account_service.get_account()
    
    # 계좌 잔고를 변경
    sample_account.cash_balance = Decimal("5000000.00")
    
    # When: 강제 갱신
    account = await account_service.get_account(refresh=True)
    
    # Then: 변경된 값(5백만원)이 반환됨
    assert account.cash_balance == Decimal("5000000.00")


@pytest.mark.asyncio
async def test_refresh_account(account_service, sample_account):
    """refresh_account 메서드가 정상 작동하는지 확인."""
    # Given: 첫 번째 조회
    await account_service.get_account()
    
    # 계좌 잔고를 변경
    sample_account.cash_balance = Decimal("8000000.00")
    
    # When: refresh_account 호출
    account = await account_service.refresh_account()
    
    # Then: 최신 정보가 반환됨
    assert account.cash_balance == Decimal("8000000.00")


@pytest.mark.asyncio
async def test_update_daily_pnl_수익_발생(account_service):
    """일일 손익 업데이트 (수익) 테스트."""
    # Given: 계좌 정보 조회
    await account_service.get_account()
    
    # When: 50만원 수익 발생
    await account_service.update_daily_pnl(Decimal("500000.00"))
    
    # Then: 일일 손익이 업데이트됨
    account = await account_service.get_account()
    assert account.daily_pnl == Decimal("500000.00")


@pytest.mark.asyncio
async def test_update_daily_pnl_손실_발생(account_service):
    """일일 손익 업데이트 (손실) 테스트."""
    # Given: 계좌 정보 조회
    await account_service.get_account()
    
    # When: 30만원 손실 발생
    await account_service.update_daily_pnl(Decimal("-300000.00"))
    
    # Then: 일일 손익이 업데이트됨
    account = await account_service.get_account()
    assert account.daily_pnl == Decimal("-300000.00")


@pytest.mark.asyncio
async def test_update_daily_pnl_누적(account_service):
    """일일 손익이 누적되는지 확인."""
    # Given: 계좌 정보 조회
    await account_service.get_account()
    
    # When: 여러 번 손익 발생
    await account_service.update_daily_pnl(Decimal("100000.00"))
    await account_service.update_daily_pnl(Decimal("200000.00"))
    await account_service.update_daily_pnl(Decimal("-50000.00"))
    
    # Then: 손익이 누적됨 (10만 + 20만 - 5만 = 25만)
    account = await account_service.get_account()
    assert account.daily_pnl == Decimal("250000.00")


@pytest.mark.asyncio
async def test_update_daily_pnl_계좌_없음(account_service):
    """계좌 정보 없이 update_daily_pnl 호출 시 에러 발생."""
    # When & Then: RuntimeError 발생
    with pytest.raises(RuntimeError, match="계좌 정보가 없습니다"):
        await account_service.update_daily_pnl(Decimal("100000.00"))


@pytest.mark.asyncio
async def test_calculate_daily_pnl(account_service):
    """당일 손익 계산 테스트 (실현 + 미실현)."""
    # Given: 계좌 정보 조회 및 실현 손익 설정
    await account_service.get_account()
    await account_service.update_daily_pnl(Decimal("100000.00"))  # 실현 손익 10만원
    
    # When: 미실현 손익 20만원 포함하여 계산
    total_pnl = await account_service.calculate_daily_pnl(Decimal("200000.00"))
    
    # Then: 실현 + 미실현 = 30만원
    assert total_pnl == Decimal("300000.00")


@pytest.mark.asyncio
async def test_is_daily_loss_limit_exceeded_초과하지_않음(account_service):
    """일일 손실 한도를 초과하지 않은 경우."""
    # Given: 계좌 정보 조회
    await account_service.get_account()
    
    # 30만원 손실 (한도: 75만원)
    await account_service.update_daily_pnl(Decimal("-300000.00"))
    
    # When: 한도 초과 여부 확인
    exceeded = await account_service.is_daily_loss_limit_exceeded()
    
    # Then: 초과하지 않음
    assert exceeded is False


@pytest.mark.asyncio
async def test_is_daily_loss_limit_exceeded_초과(account_service):
    """일일 손실 한도를 초과한 경우."""
    # Given: 계좌 정보 조회
    await account_service.get_account()
    
    # 80만원 손실 (한도: 75만원)
    await account_service.update_daily_pnl(Decimal("-800000.00"))
    
    # When: 한도 초과 여부 확인
    exceeded = await account_service.is_daily_loss_limit_exceeded()
    
    # Then: 초과함
    assert exceeded is True


@pytest.mark.asyncio
async def test_get_available_cash(account_service):
    """사용 가능한 예수금 조회."""
    # When: 예수금 조회
    cash = await account_service.get_available_cash()
    
    # Then: 1천만원
    assert cash == Decimal("10000000.00")


@pytest.mark.asyncio
async def test_get_total_asset_value(account_service):
    """총 평가 금액 조회."""
    # When: 총 평가 금액 조회
    total = await account_service.get_total_asset_value()
    
    # Then: 1천5백만원
    assert total == Decimal("15000000.00")


@pytest.mark.asyncio
async def test_get_total_pnl(account_service):
    """총 손익 조회."""
    # When: 총 손익 조회
    pnl = await account_service.get_total_pnl()
    
    # Then: 50만원 수익
    assert pnl == Decimal("500000.00")


@pytest.mark.asyncio
async def test_clear_cache(account_service, sample_account):
    """캐시 삭제 테스트."""
    # Given: 계좌 정보 조회로 캐시 생성
    await account_service.get_account()
    assert account_service.cached_account is not None
    
    # When: 캐시 삭제
    account_service.clear_cache()
    
    # Then: 캐시가 삭제됨
    assert account_service.cached_account is None
    
    # 다음 조회 시 다시 캐시됨
    account = await account_service.get_account()
    assert account_service.cached_account is not None
