"""시뮬레이터 모듈.

실제 Kiwoom API 없이도 전략을 테스트할 수 있는 In-Memory Fake Object를 제공합니다.
"""

from .fake_exchange import FakeExchange
from .kiwoom_simulator import KiwoomSimulator

__all__ = ["FakeExchange", "KiwoomSimulator"]
