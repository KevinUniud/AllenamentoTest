"""Cross-cutting HTTP request tracing and timing."""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request

from server.request_id import normalize_request_id

logger = logging.getLogger("testlogica.http")


def register_request_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def trace_request(request: Request, call_next):
        request_id = normalize_request_id(request.headers.get("x-request-id"))
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request method=%s path=%s status=%s duration_ms=%s request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )
        return response
