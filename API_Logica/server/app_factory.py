"""FastAPI application construction and cross-cutting middleware."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.errors import register_exception_handlers
from server.middleware import register_request_middleware
from server.openapi_docs import OPENAPI_TAGS
from testlogica.config import CORS_ORIGINS, configure_logging

API_VERSION = "1.4.0"


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="TestLogica API",
        summary="OpenAPI 3.1 per generator.py e PrologBridge",
        description=(
            "API HTTP che espone le funzioni pubbliche del generatore di esercizi "
            "logici e i metodi pubblici del bridge Prolog. "
            "La specifica OpenAPI e generata in formato 3.1.0 e documenta endpoint distinti per ogni funzione esposta."
        ),
        version=API_VERSION,
        openapi_version="3.1.0",
        openapi_tags=OPENAPI_TAGS,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(CORS_ORIGINS),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "X-Request-ID"],
    )
    register_exception_handlers(app)
    register_request_middleware(app)
    return app
