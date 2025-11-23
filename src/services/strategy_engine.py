"""전략 엔진 모듈.

이 모듈은 전략을 동적으로 로드하고 관리하는 기능을 제공합니다.
"""

import importlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Type
from decimal import Decimal

import yaml
from pydantic import BaseModel, Field

from ..models.strategy import BaseStrategy


logger = logging.getLogger(__name__)


class StrategyConfig(BaseModel):
    """전략 설정 모델.

    Attributes:
        strategy_name: 전략 고유 이름
        enabled: 전략 활성화 여부
        class_path: 전략 클래스 경로 (예: "src.strategies.golden_cross.GoldenCrossStrategy")
        parameters: 전략별 파라미터
    """

    strategy_name: str = Field(..., min_length=1, max_length=100)
    enabled: bool = Field(default=True)
    class_path: str = Field(..., description="Strategy class path")
    parameters: Dict[str, any] = Field(default_factory=dict)

    class Config:
        """Pydantic 설정."""

        frozen = False


class StrategyEngine:
    """전략 엔진.

    YAML 파일에서 전략 설정을 로드하고, importlib을 사용하여 동적으로 전략 클래스를 생성합니다.

    Attributes:
        config_path: 전략 설정 YAML 파일 경로
        strategies: 로드된 전략 인스턴스 딕셔너리 (strategy_name -> BaseStrategy)
        strategy_configs: 전략 설정 딕셔너리 (strategy_name -> StrategyConfig)
    """

    def __init__(self, config_path: Optional[Path] = None):
        """전략 엔진 초기화.

        Args:
            config_path: 전략 설정 YAML 파일 경로. None이면 기본 경로 사용.
        """
        self.config_path = config_path or Path("config/strategies.yaml")
        self.strategies: Dict[str, BaseStrategy] = {}
        self.strategy_configs: Dict[str, StrategyConfig] = {}

    def load_strategies_from_yaml(self) -> List[StrategyConfig]:
        """YAML 파일에서 전략 설정 로드.

        Returns:
            전략 설정 리스트

        Raises:
            FileNotFoundError: 설정 파일이 존재하지 않는 경우
            yaml.YAMLError: YAML 파싱 오류
            ValueError: 설정 검증 오류
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"Strategy config file not found: {self.config_path}")

        logger.info(f"Loading strategies from {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f)

        if not config_data or "strategies" not in config_data:
            raise ValueError("Invalid strategy config: 'strategies' key not found")

        strategy_configs = []
        for strategy_dict in config_data["strategies"]:
            try:
                config = StrategyConfig(**strategy_dict)
                strategy_configs.append(config)
                logger.info(f"Loaded strategy config: {config.strategy_name}")
            except Exception as e:
                logger.error(f"Failed to load strategy config: {e}")
                raise

        return strategy_configs

    def import_strategy_class(self, class_path: str) -> Type[BaseStrategy]:
        """전략 클래스 동적 import.

        Args:
            class_path: 전략 클래스 경로 (예: "src.strategies.golden_cross.GoldenCrossStrategy")

        Returns:
            전략 클래스

        Raises:
            ImportError: 모듈 또는 클래스를 찾을 수 없는 경우
            ValueError: 클래스가 BaseStrategy를 상속하지 않는 경우

        Example:
            >>> engine = StrategyEngine()
            >>> cls = engine.import_strategy_class("src.strategies.golden_cross.GoldenCrossStrategy")
            >>> isinstance(cls, type) and issubclass(cls, BaseStrategy)
            True
        """
        try:
            # class_path를 모듈 경로와 클래스 이름으로 분리
            module_path, class_name = class_path.rsplit(".", 1)

            # 모듈 import
            module = importlib.import_module(module_path)

            # 클래스 가져오기
            strategy_class = getattr(module, class_name)

            # BaseStrategy 상속 확인
            if not issubclass(strategy_class, BaseStrategy):
                raise ValueError(
                    f"Class {class_name} does not inherit from BaseStrategy"
                )

            logger.info(f"Successfully imported strategy class: {class_path}")
            return strategy_class

        except ImportError as e:
            logger.error(f"Failed to import strategy class {class_path}: {e}")
            raise
        except AttributeError as e:
            logger.error(f"Class {class_name} not found in module {module_path}: {e}")
            raise ImportError(f"Class {class_name} not found in module {module_path}")

    def create_strategy_instance(
        self, strategy_class: Type[BaseStrategy], parameters: Dict[str, any]
    ) -> BaseStrategy:
        """전략 인스턴스 생성.

        Args:
            strategy_class: 전략 클래스
            parameters: 전략 파라미터

        Returns:
            전략 인스턴스

        Raises:
            TypeError: 파라미터가 잘못된 경우
        """
        try:
            # 전략 클래스 생성자에 파라미터 전달
            strategy_instance = strategy_class(**parameters)
            logger.info(f"Created strategy instance: {strategy_class.__name__}")
            return strategy_instance

        except TypeError as e:
            logger.error(f"Failed to create strategy instance: {e}")
            raise

    def load_and_initialize_strategies(self) -> Dict[str, BaseStrategy]:
        """전략 설정을 로드하고 인스턴스 생성.

        Returns:
            전략 인스턴스 딕셔너리 (strategy_name -> BaseStrategy)

        Raises:
            FileNotFoundError: 설정 파일이 존재하지 않는 경우
            ImportError: 전략 클래스를 import할 수 없는 경우
            ValueError: 설정 검증 오류
        """
        # YAML에서 전략 설정 로드
        strategy_configs = self.load_strategies_from_yaml()

        # 각 전략 인스턴스 생성
        strategies = {}
        for config in strategy_configs:
            # 비활성화된 전략은 스킵
            if not config.enabled:
                logger.info(f"Skipping disabled strategy: {config.strategy_name}")
                continue

            try:
                # 전략 클래스 import
                strategy_class = self.import_strategy_class(config.class_path)

                # 전략 인스턴스 생성
                strategy_instance = self.create_strategy_instance(
                    strategy_class, config.parameters
                )

                # 저장
                strategies[config.strategy_name] = strategy_instance
                self.strategy_configs[config.strategy_name] = config

                logger.info(f"Initialized strategy: {config.strategy_name}")

            except Exception as e:
                logger.error(
                    f"Failed to initialize strategy {config.strategy_name}: {e}"
                )
                raise

        self.strategies = strategies
        return strategies

    def get_strategy(self, strategy_name: str) -> Optional[BaseStrategy]:
        """전략 인스턴스 조회.

        Args:
            strategy_name: 전략 이름

        Returns:
            전략 인스턴스. 존재하지 않으면 None.
        """
        return self.strategies.get(strategy_name)

    def enable_strategy(self, strategy_name: str) -> None:
        """전략 활성화.

        Args:
            strategy_name: 전략 이름

        Raises:
            KeyError: 전략이 존재하지 않는 경우
        """
        if strategy_name not in self.strategy_configs:
            raise KeyError(f"Strategy not found: {strategy_name}")

        config = self.strategy_configs[strategy_name]
        config.enabled = True

        # 비활성화 상태였다면 다시 초기화
        if strategy_name not in self.strategies:
            strategy_class = self.import_strategy_class(config.class_path)
            strategy_instance = self.create_strategy_instance(
                strategy_class, config.parameters
            )
            self.strategies[strategy_name] = strategy_instance

        logger.info(f"Enabled strategy: {strategy_name}")

    def disable_strategy(self, strategy_name: str) -> None:
        """전략 비활성화.

        Args:
            strategy_name: 전략 이름

        Raises:
            KeyError: 전략이 존재하지 않는 경우
        """
        if strategy_name not in self.strategy_configs:
            raise KeyError(f"Strategy not found: {strategy_name}")

        config = self.strategy_configs[strategy_name]
        config.enabled = False

        # 인스턴스 제거
        if strategy_name in self.strategies:
            del self.strategies[strategy_name]

        logger.info(f"Disabled strategy: {strategy_name}")

    def get_active_strategies(self) -> List[str]:
        """활성 전략 목록 조회.

        Returns:
            활성 전략 이름 리스트
        """
        return list(self.strategies.keys())

    def reload_strategies(self) -> Dict[str, BaseStrategy]:
        """전략 재로드.

        YAML 설정 파일을 다시 읽고 모든 전략을 재초기화합니다.

        Returns:
            전략 인스턴스 딕셔너리
        """
        logger.info("Reloading all strategies")

        # 기존 전략 제거
        self.strategies.clear()
        self.strategy_configs.clear()

        # 전략 재로드
        return self.load_and_initialize_strategies()
