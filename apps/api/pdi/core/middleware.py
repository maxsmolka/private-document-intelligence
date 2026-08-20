import logging
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("pdi.request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid4()))
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["x-frame-options"] = "SAMEORIGIN"
        response.headers["referrer-policy"] = "no-referrer"
        logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "operation": f"{request.method} {request.url.path}",
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return response
