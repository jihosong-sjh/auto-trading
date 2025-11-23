"""저장소 패키지.

데이터 영속성을 담당하는 Repository 패턴을 구현합니다.
"""

from .database import Database, get_database

__all__ = ["Database", "get_database"]
