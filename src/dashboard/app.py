"""FastAPI application factory for Dashboard.

Creates and configures the FastAPI app with:
- CORS middleware for React frontend
- REST API routes for positions/portfolio/trades
- WebSocket endpoint for real-time updates
- Static file serving for production build
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ..cache.redis_manager import RedisManager
from ..config.settings import Settings
from ..utils.logger import get_logger
from .routes.api import router as api_router
from .routes.websocket import router as ws_router
from .services.data_subscriber import DashboardDataSubscriber

logger = get_logger(__name__)

# Global subscriber instance (set during app startup)
_subscriber: Optional[DashboardDataSubscriber] = None


def get_subscriber() -> DashboardDataSubscriber:
    """Get the global subscriber instance."""
    if _subscriber is None:
        raise RuntimeError("DashboardDataSubscriber not initialized")
    return _subscriber


def create_app(
    settings: Optional[Settings] = None,
    redis_manager: Optional[RedisManager] = None,
) -> FastAPI:
    """Create and configure FastAPI application.

    Args:
        settings: Application settings (uses default if None)
        redis_manager: Redis manager (creates new if None)

    Returns:
        Configured FastAPI app
    """
    global _subscriber

    if settings is None:
        from ..config.settings import get_settings
        settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Application lifespan handler."""
        global _subscriber

        # Startup
        logger.info("Starting Dashboard API server...")

        # Initialize Redis connection
        nonlocal redis_manager
        if redis_manager is None:
            redis_manager = RedisManager(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_db,
                password=settings.redis_password,
            )
            await redis_manager.initialize()

        # Initialize subscriber
        _subscriber = DashboardDataSubscriber(redis_manager)
        await _subscriber.start()

        # Store in app state for access in routes
        app.state.subscriber = _subscriber
        app.state.redis_manager = redis_manager
        app.state.settings = settings

        logger.info(f"Dashboard API server started on {settings.dashboard_host}:{settings.dashboard_port}")

        yield

        # Shutdown
        logger.info("Stopping Dashboard API server...")

        if _subscriber:
            await _subscriber.stop()
            _subscriber = None

        if redis_manager:
            await redis_manager.close()

        logger.info("Dashboard API server stopped")

    # Create app
    app = FastAPI(
        title="Kiwoom Auto-Trading Dashboard API",
        description="Real-time Position/P&L Dashboard API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.dashboard_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(api_router, prefix="/api", tags=["API"])
    app.include_router(ws_router, tags=["WebSocket"])

    # Health check endpoint
    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        subscriber = app.state.subscriber
        return {
            "status": "healthy",
            "websocket_clients": subscriber.client_count if subscriber else 0,
        }

    # Mount static files for production (React build)
    # The React build should be in dashboard-ui/dist/
    static_dir = Path(__file__).parent.parent.parent / "dashboard-ui" / "dist"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
        logger.info(f"Serving static files from {static_dir}")

    return app


async def run_dashboard_server(
    settings: Optional[Settings] = None,
    redis_manager: Optional[RedisManager] = None,
) -> None:
    """Run the dashboard server standalone.

    Args:
        settings: Application settings
        redis_manager: Redis manager
    """
    import uvicorn

    if settings is None:
        from ..config.settings import get_settings
        settings = get_settings()

    app = create_app(settings=settings, redis_manager=redis_manager)

    config = uvicorn.Config(
        app,
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()
