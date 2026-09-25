"""ASGI entry point for feedback ingestion and chart delivery."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
import time
from collections.abc import AsyncIterator, Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import ValidationError
from pydantic.json_schema import models_json_schema

from feedback_service import __version__
from feedback_service.config import FeedbackSettings, load_settings
from feedback_service.coordinator import FeedbackCoordinator
from feedback_service.metrics import ServiceMetrics
from feedback_service.schemas import ChartManifest, FeedbackReceiptResponse, FeedbackReport
from feedback_service.snapshots import ChartSnapshotPublisher
from feedback_service.storage import (
    FeedbackPayloadError,
    FeedbackQuotaExceededError,
    FeedbackStorageError,
    FeedbackStore,
    IdempotencyConflictError,
)
from feedback_service.worker_status import WorkerStatusStore

# Uvicorn configura esplicitamente questo logger anche quando l'app viene avviata
# con ``uvicorn feedback_service.app:app``. Un logger di modulo resterebbe invece
# al livello WARNING e perderebbe gli eventi HTTP strutturati di livello INFO.
LOGGER = logging.getLogger("uvicorn.error")
_PRIVATE_NO_STORE = {"Cache-Control": "private, no-store"}


def _install_openapi_feedback_contract(service: FastAPI) -> None:
    default_openapi = service.openapi

    def build_openapi() -> dict[str, Any]:
        if service.openapi_schema is not None:
            return service.openapi_schema
        document = default_openapi()
        _, definitions = models_json_schema(
            [(FeedbackReport, "validation")],
            by_alias=True,
            ref_template="#/components/schemas/{model}",
        )
        schemas = document.setdefault("components", {}).setdefault("schemas", {})
        schemas.update(definitions.get("$defs", {}))
        service.openapi_schema = document
        return document

    service.openapi = build_openapi  # type: ignore[method-assign]


def _invalid_json_constant(value: str) -> None:
    raise ValueError(f"Costante JSON non valida: {value}")


async def _read_payload(request: Request, *, max_body_bytes: int) -> dict[str, Any]:
    media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    is_json = media_type == "application/json" or (
        media_type.startswith("application/") and media_type.endswith("+json")
    )
    if not is_json:
        raise HTTPException(status_code=415, detail="Content-Type JSON richiesto")

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError:
            raise HTTPException(status_code=400, detail="Content-Length non valido") from None
        if declared < 0:
            raise HTTPException(status_code=400, detail="Content-Length non valido")
        if declared > max_body_bytes:
            raise HTTPException(status_code=413, detail="Payload feedback troppo grande")

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_body_bytes:
            raise HTTPException(status_code=413, detail="Payload feedback troppo grande")
    try:
        payload = json.loads(body, parse_constant=_invalid_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise HTTPException(status_code=422, detail="Payload feedback non valido") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Payload feedback non valido")
    try:
        json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (UnicodeError, ValueError, RecursionError):
        raise HTTPException(status_code=422, detail="Payload feedback non valido") from None
    return cast(dict[str, Any], payload)


def _new_io_executor() -> Executor:
    return ThreadPoolExecutor(max_workers=2, thread_name_prefix="feedback-io")


def _idempotency_key(request: Request) -> str | None:
    values = request.headers.getlist("idempotency-key")
    if not values:
        return None
    if len(values) != 1:
        raise HTTPException(status_code=400, detail="Idempotency-Key non valida")
    value = values[0]
    try:
        parsed = UUID(value)
    except (AttributeError, ValueError):
        raise HTTPException(status_code=400, detail="Idempotency-Key non valida") from None
    if parsed.version != 4 or str(parsed) != value:
        raise HTTPException(status_code=400, detail="Idempotency-Key non valida")
    return value


def create_app(
    settings: FeedbackSettings | None = None,
    *,
    io_executor_factory: Callable[[], Executor] = _new_io_executor,
) -> FastAPI:
    active_settings = settings or load_settings()
    store = FeedbackStore(
        active_settings.storage_dir,
        retention_days=active_settings.retention_days,
        max_receipts=active_settings.max_receipts,
        max_storage_bytes=active_settings.max_storage_bytes,
        min_free_bytes=active_settings.min_free_bytes,
    )
    publisher = ChartSnapshotPublisher(
        active_settings.charts_dir,
        minimum_aggregate_sessions=active_settings.minimum_aggregate_sessions,
        snapshots_to_keep=active_settings.snapshots_to_keep,
    )
    coordinator = FeedbackCoordinator(active_settings, store, publisher)
    worker_status = WorkerStatusStore(active_settings.charts_dir / "worker-status.json")
    metrics = ServiceMetrics()

    async def run_io(function: Callable[..., Any], *args: Any) -> Any:
        feedback_io_executor = cast(Executor | None, service.state.feedback_io_executor)
        if feedback_io_executor is None:
            raise RuntimeError("Executor feedback non inizializzato")
        if sys.version_info >= (3, 14):
            # CPython 3.14 currently has a reproducible wake-up regression when
            # the same non-default executor is reused through run_in_executor.
            # Polling the concurrent future keeps the event loop responsive and
            # is removed from the normal Python 3.11 container path.
            future = feedback_io_executor.submit(function, *args)
            try:
                while not future.done():
                    await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                future.cancel()
                raise
            return future.result()
        return await asyncio.get_running_loop().run_in_executor(
            feedback_io_executor,
            function,
            *args,
        )

    async def retention_tick() -> int:
        return cast(int, await run_io(coordinator.retention_tick))

    async def invalidate_before_response(purged_receipts: int) -> None:
        if not purged_receipts:
            return
        try:
            await run_io(publisher.invalidate)
        except Exception:
            LOGGER.exception("Impossibile invalidare i grafici dopo la retention")
            raise HTTPException(
                status_code=503,
                detail="Snapshot feedback non invalidabile",
            ) from None

    async def publication_tick() -> None:
        publication_lock = cast(asyncio.Lock | None, service.state.publication_lock)
        if publication_lock is None:
            raise RuntimeError("Scheduler feedback non inizializzato")
        async with publication_lock:
            await run_io(coordinator.publication_tick)

    async def publication_loop() -> None:
        while True:
            await asyncio.sleep(active_settings.publish_interval_seconds)
            try:
                await publication_tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Pubblicazione periodica dei grafici fallita")

    async def retention_loop() -> None:
        while True:
            await asyncio.sleep(active_settings.retention_interval_seconds)
            try:
                await retention_tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Pulizia periodica delle ricevute feedback fallita")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        feedback_io_executor = io_executor_factory()
        application.state.feedback_io_executor = feedback_io_executor
        application.state.publication_lock = asyncio.Lock()
        publication_task: asyncio.Task[None] | None = None
        retention_task: asyncio.Task[None] | None = None
        try:
            await run_io(coordinator.initialize)
            if active_settings.worker_mode == "embedded":
                publication_task = asyncio.create_task(
                    publication_loop(),
                    name="feedback-periodic-publication",
                )
                retention_task = asyncio.create_task(
                    retention_loop(),
                    name="feedback-periodic-retention",
                )
            application.state.publication_task = publication_task
            application.state.retention_task = retention_task
            yield
        finally:
            for task in (publication_task, retention_task):
                if task is not None:
                    task.cancel()
            for task in (publication_task, retention_task):
                if task is None:
                    continue
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            feedback_io_executor.shutdown(wait=True, cancel_futures=True)
            application.state.publication_task = None
            application.state.retention_task = None
            application.state.publication_lock = None
            application.state.feedback_io_executor = None

    service = FastAPI(
        title="TestLogica Feedback Service",
        description=(
            "Riceve il payload storico del quiz senza normalizzarlo e pubblica "
            "periodicamente snapshot versionati dei grafici aggregati. "
            "I payload grezzi non sono esposti."
        ),
        version=__version__,
        openapi_version="3.1.0",
        lifespan=lifespan,
    )
    service.state.settings = active_settings
    service.state.feedback_store = store
    service.state.snapshot_publisher = publisher
    service.state.coordinator = coordinator
    service.state.worker_status = worker_status
    service.state.metrics = metrics
    service.state.feedback_io_executor = None
    service.state.publication_lock = None
    service.state.publication_task = None
    service.state.retention_task = None
    service.state.publication_tick = publication_tick
    service.state.retention_tick = retention_tick

    @service.middleware("http")
    async def request_metadata(request: Request, call_next: Callable[[Request], Any]) -> Response:
        started = time.perf_counter()
        supplied = request.headers.get("x-request-id", "").strip()
        request_id = supplied[:128] if supplied and supplied.isascii() else str(uuid4())
        response = cast(Response, await call_next(request))
        response.headers["X-Request-ID"] = request_id
        LOGGER.info(
            json.dumps(
                {
                    "event": "http_request",
                    "method": request.method,
                    "path": request.url.path,
                    "request_id": request_id,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1_000, 2),
                },
                separators=(",", ":"),
            )
        )
        return response

    def worker_is_ready() -> bool:
        if active_settings.worker_mode == "embedded":
            publication_task = cast(asyncio.Task[None] | None, service.state.publication_task)
            retention_task = cast(asyncio.Task[None] | None, service.state.retention_task)
            return (
                publication_task is not None
                and not publication_task.done()
                and retention_task is not None
                and not retention_task.done()
            )
        return worker_status.is_fresh(
            maximum_age_seconds=active_settings.worker_stale_seconds
        )

    @service.get("/health", tags=["service"])
    async def health() -> dict[str, str]:
        return {"status": "healthy"}

    @service.get("/ready", tags=["service"])
    async def ready() -> dict[str, Any]:
        try:
            storage_ready, charts_ready, snapshot_integrity = await asyncio.wait_for(
                asyncio.gather(
                    run_io(store.check_ready),
                    run_io(publisher.check_ready),
                    run_io(publisher.current_snapshot_integrity),
                ),
                timeout=1.0,
            )
        except (TimeoutError, RuntimeError):
            raise HTTPException(status_code=503, detail="Servizio feedback non pronto") from None
        worker_ready = worker_is_ready()
        if (
            not storage_ready
            or not charts_ready
            or snapshot_integrity == "invalid"
            or not worker_ready
        ):
            raise HTTPException(status_code=503, detail="Servizio feedback non pronto")
        return {
            "status": "ready",
            "worker": active_settings.worker_mode,
        }

    @service.get("/metrics", tags=["service"], include_in_schema=False)
    async def service_metrics() -> Response:
        statistics = await run_io(store.statistics)
        manifest = await run_io(publisher.load_current_manifest)
        content = metrics.render(
            receipt_count=statistics.receipt_count,
            storage_bytes=statistics.byte_count,
            max_receipts=active_settings.max_receipts,
            max_storage_bytes=active_settings.max_storage_bytes,
            snapshot_available=manifest is not None,
            worker_fresh=worker_is_ready(),
        )
        return Response(
            content=content,
            media_type="text/plain; version=0.0.4; charset=utf-8",
            headers=_PRIVATE_NO_STORE,
        )

    @service.post(
        "/api/revisione",
        tags=["feedback"],
        summary="Riceve il report finale del quiz",
        description=(
            "Valida e conserva le chiavi e i valori del body JSON senza rinominarli. "
            "La pubblicazione dei grafici avviene solo allo scadere dell'intervallo "
            "configurato e non ritarda la ricevuta."
        ),
        status_code=201,
        response_model=FeedbackReceiptResponse,
        openapi_extra={
            "parameters": [
                {
                    "name": "Idempotency-Key",
                    "in": "header",
                    "required": False,
                    "description": "UUIDv4 canonico per rendere sicuri i retry.",
                    "schema": {"type": "string", "format": "uuid"},
                }
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/FeedbackReport"},
                    }
                },
            }
        },
    )
    async def submit_feedback(request: Request) -> FeedbackReceiptResponse:
        idempotency_key = _idempotency_key(request)
        try:
            payload = await _read_payload(
                request,
                max_body_bytes=active_settings.max_body_bytes,
            )
        except HTTPException as exc:
            metrics.submission(f"rejected_{exc.status_code}")
            raise
        payload_bytes = len(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        try:
            FeedbackReport.model_validate(payload)
        except ValidationError:
            metrics.submission("rejected_422")
            raise HTTPException(status_code=422, detail="Payload feedback non valido") from None
        try:
            receipt = await run_io(store.save, payload, idempotency_key)
        except IdempotencyConflictError as exc:
            await invalidate_before_response(exc.purged_receipts)
            metrics.submission("conflict")
            raise HTTPException(
                status_code=409,
                detail="Idempotency-Key gia usata con un payload diverso",
            ) from None
        except FeedbackPayloadError as exc:
            await invalidate_before_response(exc.purged_receipts)
            metrics.submission("rejected_422")
            raise HTTPException(status_code=422, detail="Payload feedback non valido") from None
        except FeedbackQuotaExceededError as exc:
            await invalidate_before_response(exc.purged_receipts)
            metrics.submission("quota_exceeded")
            raise HTTPException(
                status_code=507,
                detail="Archivio feedback pieno: riprovare dopo la retention",
            ) from None
        except FeedbackStorageError as exc:
            await invalidate_before_response(exc.purged_receipts)
            metrics.submission("storage_error")
            LOGGER.exception("Impossibile conservare una ricevuta feedback")
            raise HTTPException(status_code=503, detail="Archivio feedback non disponibile") from None
        except (UnicodeError, ValueError):
            raise HTTPException(status_code=422, detail="Payload feedback non valido") from None
        except OSError:
            LOGGER.exception("Impossibile conservare una ricevuta feedback")
            raise HTTPException(status_code=503, detail="Archivio feedback non disponibile") from None
        if receipt.purged_receipts:
            await invalidate_before_response(receipt.purged_receipts)
        metrics.submission(
            "accepted" if receipt.created else "idempotent",
            payload_bytes=payload_bytes,
        )
        return FeedbackReceiptResponse(filename=receipt.filename, receipt_id=receipt.receipt_id)

    @service.get(
        "/api/feedback/charts/manifest",
        tags=["charts"],
        response_model=ChartManifest,
        summary="Restituisce il manifest dello snapshot corrente",
    )
    async def chart_manifest(response: Response) -> ChartManifest:
        manifest = await run_io(publisher.load_current_manifest)
        if manifest is None:
            raise HTTPException(
                status_code=404,
                detail="Grafici non ancora disponibili",
                headers=_PRIVATE_NO_STORE,
            )
        response.headers.update(_PRIVATE_NO_STORE)
        return manifest

    @service.get(
        "/api/feedback/charts/{generation_id}/{category}/{filename}",
        tags=["charts"],
        summary="Restituisce un asset presente nel manifest versionato",
    )
    async def chart_asset(generation_id: str, category: str, filename: str) -> Response:
        content = await run_io(publisher.read_asset, generation_id, category, filename)
        if content is None:
            raise HTTPException(
                status_code=404,
                detail="Grafico non trovato",
                headers=_PRIVATE_NO_STORE,
            )
        return Response(
            content=content,
            media_type="image/png",
            headers={
                **_PRIVATE_NO_STORE,
                "X-Content-Type-Options": "nosniff",
            },
        )

    _install_openapi_feedback_contract(service)
    return service


app = create_app()


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="127.0.0.1", port=5555, access_log=False)
