"""Dashboard module for real-time Position/P&L visualization.

This module provides:
- FastAPI backend for REST API and WebSocket
- Redis Pub/Sub integration for real-time data
- React frontend (dashboard-ui/)
"""

from .app import create_app

__all__ = ["create_app"]
