"""Central translation of application exceptions to stable HTTP errors."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from server.request_id import normalize_request_id
from testlogica.prolog_bridge import PrologBridgeError, PrologExecutionError, PrologNotFoundError

logger = logging.getLogger(__name__)


def _response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    request_id = normalize_request_id(getattr(request.state, "request_id", None) or request.headers.get("x-request-id"))
    return JSONResponse(
        status_code=status,
        content={"code": code, "message": message, "request_id": request_id},
        headers={"X-Request-ID": request_id},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        logger.info("Request validation failed: %s", exc.errors())
        return _response(request, 422, "REQUEST_VALIDATION_ERROR", "Payload della richiesta non valido")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return _response(request, exc.status_code, "HTTP_ERROR", str(exc.detail))

    @app.exception_handler(PrologNotFoundError)
    async def prolog_not_found(request: Request, exc: PrologNotFoundError) -> JSONResponse:
        logger.warning("SWI-Prolog unavailable", exc_info=(type(exc), exc, exc.__traceback__))
        return _response(request, 503, "PROLOG_UNAVAILABLE", "Motore logico non disponibile")

    @app.exception_handler(PrologExecutionError)
    async def prolog_execution(request: Request, exc: PrologExecutionError) -> JSONResponse:
        logger.warning("SWI-Prolog execution failed", exc_info=(type(exc), exc, exc.__traceback__))
        return _response(request, 502, "PROLOG_EXECUTION_FAILED", "Esecuzione logica non completata")

    @app.exception_handler(PrologBridgeError)
    async def prolog_bridge(request: Request, exc: PrologBridgeError) -> JSONResponse:
        logger.error("Prolog bridge error", exc_info=(type(exc), exc, exc.__traceback__))
        return _response(request, 500, "PROLOG_BRIDGE_ERROR", "Errore interno del motore logico")

    @app.exception_handler(ValueError)
    async def invalid_input(request: Request, exc: ValueError) -> JSONResponse:
        logger.info("Invalid application input: %s", exc)
        return _response(request, 422, "INVALID_INPUT", str(exc))

    @app.exception_handler(RuntimeError)
    async def generation_failed(request: Request, exc: RuntimeError) -> JSONResponse:
        logger.info("Generation constraints not satisfied: %s", exc)
        return _response(request, 422, "GENERATION_FAILED", str(exc))

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled application error", exc_info=(type(exc), exc, exc.__traceback__))
        return _response(request, 500, "INTERNAL_ERROR", "Errore interno del servizio")
