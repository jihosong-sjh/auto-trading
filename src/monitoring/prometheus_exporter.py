"""Prometheus HTTP Exporter.

Phase 7: Performance Monitoring
Prometheus 메트릭을 HTTP 엔드포인트로 노출합니다.
"""

import asyncio
from typing import Optional

try:
    from aiohttp import web
except ImportError:
    web = None

from ..utils.logger import get_logger
from .metrics_collector import MetricsCollector

logger = get_logger(__name__)


class PrometheusExporter:
    """Prometheus HTTP Exporter.

    Features:
    - HTTP 엔드포인트로 메트릭 노출 (/metrics)
    - 헬스체크 엔드포인트 (/health)
    - 비동기 웹 서버 (aiohttp)
    """

    def __init__(
        self,
        metrics_collector: MetricsCollector,
        host: str = "0.0.0.0",
        port: int = 9090,
    ):
        """Prometheus Exporter를 초기화합니다.

        Args:
            metrics_collector: 메트릭 수집기
            host: 바인딩할 호스트 (기본값: 0.0.0.0)
            port: 바인딩할 포트 (기본값: 9090)
        """
        self.metrics_collector = metrics_collector
        self.host = host
        self.port = port

        if web is None:
            logger.warning("aiohttp not installed. HTTP exporter will not be available.")
            self.enabled = False
        else:
            self.enabled = True

        self.app: Optional[web.Application] = None
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None

        logger.info(
            f"PrometheusExporter initialized (enabled={self.enabled}, "
            f"endpoint=http://{host}:{port}/metrics)"
        )

    async def start(self):
        """HTTP 서버를 시작합니다."""
        if not self.enabled:
            logger.warning("HTTP exporter is disabled. Install aiohttp to enable.")
            return

        try:
            # aiohttp 앱 생성
            self.app = web.Application()

            # 라우트 등록
            self.app.router.add_get("/metrics", self._handle_metrics)
            self.app.router.add_get("/health", self._handle_health)

            # 서버 시작
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()

            self.site = web.TCPSite(self.runner, self.host, self.port)
            await self.site.start()

            logger.info(
                f"Prometheus exporter started at http://{self.host}:{self.port}/metrics"
            )

        except Exception as e:
            logger.error(f"Failed to start Prometheus exporter: {e}", exc_info=True)
            raise

    async def stop(self):
        """HTTP 서버를 종료합니다."""
        if not self.enabled:
            return

        try:
            if self.runner:
                await self.runner.cleanup()
                logger.info("Prometheus exporter stopped")

        except Exception as e:
            logger.error(f"Failed to stop Prometheus exporter: {e}", exc_info=True)

    async def _handle_metrics(self, request: web.Request) -> web.Response:
        """메트릭 엔드포인트 핸들러."""
        try:
            # 메트릭 수집
            metrics_data = self.metrics_collector.export_metrics()

            # Prometheus 텍스트 형식으로 응답 (aiohttp 호환)
            return web.Response(
                body=metrics_data,
                content_type="text/plain",
                charset="utf-8",
                headers={"X-Content-Type-Options": "nosniff"},
            )

        except Exception as e:
            logger.error(f"Failed to export metrics: {e}", exc_info=True)
            return web.Response(
                text=f"Error exporting metrics: {e}",
                status=500,
            )

    async def _handle_health(self, request: web.Request) -> web.Response:
        """헬스체크 엔드포인트 핸들러."""
        try:
            # 메트릭 수집기 상태 확인
            summary = self.metrics_collector.get_metrics_summary()

            return web.json_response(
                {
                    "status": "healthy",
                    "metrics_enabled": summary.get("enabled", False),
                    "metrics_count": (
                        summary.get("counters", 0)
                        + summary.get("gauges", 0)
                        + summary.get("histograms", 0)
                        + summary.get("summaries", 0)
                    ),
                }
            )

        except Exception as e:
            logger.error(f"Health check failed: {e}", exc_info=True)
            return web.json_response(
                {
                    "status": "unhealthy",
                    "error": str(e),
                },
                status=500,
            )
