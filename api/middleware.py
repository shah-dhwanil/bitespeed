# """
# FastAPI middleware for request logging with structlog.
# """
from time import time
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from structlog import get_logger
from structlog.contextvars import bind_contextvars, clear_contextvars

logger = get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class ContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        bind_contextvars(
            request_id=request.state.request_id,
            method=request.method,
            path=request.url.path,
        )
        response = await call_next(request)
        clear_contextvars()
        return response


class LoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, slow_request_threshold_ms: float = 1000.0):
        super().__init__(app)
        self.slow_request_threshold_ms = slow_request_threshold_ms

    async def dispatch(self, request: Request, call_next):
        logger = get_logger()
        logger.info(event="request_recieved")
        start_time = time()
        response = await call_next(request)
        duration_ms = (time() - start_time) * 1000
        logger.info(
            event="response_sent",
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        if duration_ms > self.slow_request_threshold_ms:
            logger.warning(
                "slow_request_detected",
                duration_ms=round(duration_ms, 2),
                threshold_ms=self.slow_request_threshold_ms,
            )
        return response