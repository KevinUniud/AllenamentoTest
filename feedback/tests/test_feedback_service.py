from __future__ import annotations

import asyncio
import copy
import json
import math
import os
import stat
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx

from feedback_service.analytics import wilson_interval
from feedback_service.app import create_app
from feedback_service.chart_generator import CHART_SPECS, ChartArtifact, ChartGenerator
from feedback_service.config import FeedbackSettings, load_settings
from feedback_service.data_processor import DataProcessor
from feedback_service.schemas import FeedbackReport
from feedback_service.snapshots import ChartSnapshotPublisher, SnapshotInvalidatedError
from feedback_service.storage import FeedbackStore, IdempotencyConflictError


def report(index: int = 1, *, correct: int = 1, age: str | None = "22") -> dict[str, Any]:
    rating = ((index - 1) % 5) + 1
    initial: dict[str, Any] = {
        "Tempo inizio esercitazione": f"2026/08/{index:02d} 12:00:00",
        "Tempo totale": f"{index + 2}.00s",
        "Totale domande": 2,
        "Totale domande corrette": correct,
        "Totale domande errate": 2 - correct,
        "Opzioni attive": {
            "showFormulas": False,
            "colorAtoms": index % 2 == 0,
            "spokenLanguage": False,
            "showWrongActionImages": False,
        },
        "Istituto di appartenenza": "Università",
        "Indirizzo": "STEM",
    }
    if age is not None:
        initial["Età"] = age
    questions: list[dict[str, Any]] = []
    for number in range(1, 3):
        is_correct = number <= correct
        questions.append(
            {
                f"Domanda nº {number}": {
                    "Tipologia": "Equivalenza" if number == 1 else "Negazione",
                    "Tempo impiegato per rispondere": f"{index + number / 10:.2f}s",
                    "Risposta è corretta": "Sì" if is_correct else "No",
                    "Domanda": f"Domanda {number}",
                    "Risposte": "p | q",
                    "Riposta utente": "p" if is_correct else "q",
                    "Riposta corretta": "p",
                }
            }
        )
    return {
        "Initial Data": initial,
        "Domande": questions,
        "Feedback": {
            "Aspettative test": str(rating),
            "Utilità ausili": str(6 - rating),
            "Utilità lezioni": str(rating),
            "Difficoltà test": str(rating),
            "Controllo": str(6 - rating),
        },
    }


def zero_report() -> dict[str, Any]:
    return {
        "Initial Data": {
            "Tempo inizio esercitazione": "2026/08/01 12:00:00",
            "Tempo totale": "0.00s",
            "Totale domande": 0,
            "Totale domande corrette": 0,
            "Totale domande errate": 0,
            "Opzioni attive": {},
        },
        "Domande": [],
        "Feedback": {
            "Aspettative test": "3",
            "Utilità ausili": "3",
            "Utilità lezioni": "3",
            "Difficoltà test": "3",
            "Controllo": "3",
        },
    }


def settings(
    root: Path,
    *,
    retention_days: int = 365,
    interval: int = 86_400,
) -> FeedbackSettings:
    return FeedbackSettings(
        storage_dir=root / "receipts",
        charts_dir=root / "charts",
        retention_days=retention_days,
        max_body_bytes=4_096,
        minimum_aggregate_sessions=3,
        snapshots_to_keep=3,
        publish_interval_seconds=interval,
        retention_interval_seconds=3_600,
        worker_mode="embedded",
    )


def publish_store_dataset(
    publisher: ChartSnapshotPublisher,
    store: FeedbackStore,
) -> Any:
    dataset = store.snapshot_dataset()
    return publisher.publish(dataset.payloads, source_token=dataset.source_token)


class FastChartGenerator:
    calls = 0

    def __init__(
        self,
        data_processor: DataProcessor,
        output_dir: Path,
        *,
        minimum_aggregate_sessions: int,
    ) -> None:
        del data_processor, minimum_aggregate_sessions
        self.output_dir = output_dir

    def generate_all_charts(self) -> list[ChartArtifact]:
        type(self).calls += 1
        artifacts: list[ChartArtifact] = []
        for spec in CHART_SPECS:
            path = self.output_dir / spec.category / spec.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\x89PNG\r\n\x1a\n" + spec.chart_id.encode("ascii"))
            artifacts.append(ChartArtifact(spec=spec, path=path, status="ready"))
        return artifacts


class CapturingChartGenerator(ChartGenerator):
    titles: dict[str, str] = {}

    def _save(
        self,
        fig: Any,
        spec: Any,
        *,
        status: Any = "ready",
    ) -> ChartArtifact:
        titles = [axis.get_title() for axis in fig.axes if axis.get_title()]
        if fig._suptitle is not None:  # noqa: SLF001 - regression-only inspection
            titles.append(fig._suptitle.get_text())  # noqa: SLF001
        self.titles[spec.chart_id] = " ".join(titles)
        return super()._save(fig, spec, status=status)


class FeedbackCoreTests(unittest.TestCase):
    def test_wilson_interval_is_bounded_and_contains_observed_accuracy(self) -> None:
        lower, upper = wilson_interval(50, 100)
        self.assertLess(lower, 50)
        self.assertGreater(upper, 50)
        self.assertGreaterEqual(lower, 0)
        self.assertLessEqual(upper, 100)
        self.assertEqual(wilson_interval(0, 0), (0.0, 0.0))

    def test_derived_categories_are_bounded_without_changing_raw_payload(self) -> None:
        payload = report()
        original = copy.deepcopy(payload)
        first = payload["Domande"][0]["Domanda nº 1"]
        second = payload["Domande"][1]["Domanda nº 2"]
        first["Tipologia"] = "truth-value"
        second["Tipologia"] = "Categoria arbitraria molto specifica"

        metrics = DataProcessor([payload]).extract_metrics()

        self.assertEqual(
            [item["tipologia"] for item in metrics["by_session"][0]["responses"]],
            ["valori di verita", "altro"],
        )
        self.assertEqual(metrics["unknown_question_types"], 1)
        expected = copy.deepcopy(original)
        expected["Domande"][0]["Domanda nº 1"]["Tipologia"] = "truth-value"
        expected["Domande"][1]["Domanda nº 2"]["Tipologia"] = (
            "Categoria arbitraria molto specifica"
        )
        self.assertEqual(payload, expected)

    def test_untrusted_times_and_demographics_are_bounded_only_in_derived_metrics(self) -> None:
        payload = report()
        payload["Initial Data"]["Tempo inizio esercitazione"] = (
            "9999-12-31T23:59:59-23:59"
        )
        payload["Initial Data"]["Tempo totale"] = "infs"
        payload["Initial Data"]["Istituto di appartenenza"] = "Istituto privato Mario Rossi"
        payload["Initial Data"]["Indirizzo"] = "Indirizzo personale non previsto"
        payload["Domande"][0]["Domanda nº 1"]["Tempo impiegato per rispondere"] = "1e309s"
        payload["Domande"][1]["Domanda nº 2"]["Tempo impiegato per rispondere"] = (
            f"{'9' * 60}:00"
        )
        original = copy.deepcopy(payload)

        FeedbackReport.model_validate(payload)
        metrics = DataProcessor([payload]).extract_metrics()
        session = metrics["by_session"][0]
        derived_times = [elapsed for _, elapsed in metrics["response_times"]]

        self.assertEqual(session["total_time"], 0.0)
        self.assertIsNone(session["datetime"])
        self.assertEqual(session["institution"], "altro")
        self.assertEqual(session["study_area"], "altro")
        self.assertEqual(derived_times, [0.0, 0.0])
        self.assertTrue(all(math.isfinite(value) for value in derived_times))
        self.assertEqual(
            set(DataProcessor([payload]).get_demographic_segments()["by_institution"]),
            {"altro"},
        )
        self.assertEqual(payload, original)

    def test_known_demographic_labels_use_a_closed_derived_taxonomy(self) -> None:
        payloads = [report(index) for index in range(1, 4)]
        payloads[0]["Initial Data"]["Istituto di appartenenza"] = "Laurea a ciclo unico"
        payloads[1]["Initial Data"]["Istituto di appartenenza"] = "Università"
        payloads[2]["Initial Data"]["Istituto di appartenenza"] = "valore arbitrario"
        payloads[0]["Initial Data"]["Indirizzo"] = "Non STEM"
        payloads[1]["Initial Data"]["Indirizzo"] = "STEM"
        payloads[2]["Initial Data"]["Indirizzo"] = "ambito identificante"

        sessions = DataProcessor(payloads).extract_metrics()["by_session"]

        self.assertEqual(
            [session["institution"] for session in sessions],
            ["ciclo unico", "universita", "altro"],
        )
        self.assertEqual(
            [session["study_area"] for session in sessions],
            ["non stem", "stem", "altro"],
        )

    def test_schema_store_zero_report_and_concurrent_idempotency(self) -> None:
        self.assertEqual(FeedbackSettings(Path("a"), Path("b")).minimum_aggregate_sessions, 10)
        self.assertEqual(FeedbackSettings(Path("a"), Path("b")).publish_interval_seconds, 86_400)
        zero = zero_report()
        original_zero = copy.deepcopy(zero)
        FeedbackReport.model_validate(zero)
        self.assertEqual(zero, original_zero)

        with tempfile.TemporaryDirectory() as temporary:
            store = FeedbackStore(Path(temporary), retention_days=365)
            payload = report()
            key = str(uuid4())
            with ThreadPoolExecutor(max_workers=12) as executor:
                receipts = list(executor.map(lambda _: store.save(payload, key), range(30)))
            self.assertEqual({item.receipt_id for item in receipts}, {UUID(key)})
            self.assertEqual(sum(item.created for item in receipts), 1)
            self.assertEqual(store.statistics().receipt_count, 1)
            self.assertTrue(store.database_path.is_file())
            self.assertEqual(store.snapshot_payloads(), [payload])

            changed = copy.deepcopy(payload)
            changed["Domande"][0]["Domanda nº 1"]["Domanda"] = "Diversa"
            with self.assertRaises(IdempotencyConflictError):
                store.save(changed, key)

            corrupt = Path(temporary) / f"{uuid4()}.json"
            corrupt.write_bytes(b"\xff")
            self.assertEqual(store.snapshot_payloads(), [payload])

    def test_interval_environment_is_explicit_and_strictly_bounded(self) -> None:
        with patch.dict(
            os.environ,
            {"FEEDBACK_PUBLISH_INTERVAL_SECONDS": "7"},
        ):
            self.assertEqual(load_settings().publish_interval_seconds, 7)
        with patch.dict(
            os.environ,
            {"FEEDBACK_PUBLISH_INTERVAL_SECONDS": "0"},
        ):
            with self.assertRaises(RuntimeError):
                load_settings()

    def test_missing_age_and_all_sensitive_series_use_k_aggregates(self) -> None:
        reports = [report(index) for index in range(1, 7)]
        reports[1]["Initial Data"].pop("Età")
        processor = DataProcessor(reports[:2])
        metrics = processor.extract_metrics()
        self.assertEqual([item["age"] for item in metrics["by_session"]], [22, None])

        for offset, payload in enumerate(reports):
            cohort = 1 if offset < 3 else 2
            payload["Initial Data"]["Tempo inizio esercitazione"] = (
                f"2026/08/0{cohort} 12:00:0{offset}"
            )
            payload["Initial Data"]["Opzioni attive"] = {
                "showFormulas": cohort == 2,
                "colorAtoms": cohort == 2,
                "spokenLanguage": cohort == 2,
                "showWrongActionImages": cohort == 2,
            }
            payload["Feedback"]["Difficoltà test"] = str(cohort)

        CapturingChartGenerator.titles = {}
        with tempfile.TemporaryDirectory() as temporary:
            publisher = ChartSnapshotPublisher(
                Path(temporary),
                minimum_aggregate_sessions=3,
                snapshots_to_keep=3,
            )
            with patch("feedback_service.snapshots.ChartGenerator", CapturingChartGenerator):
                manifest = publisher.publish(reports)
            assert manifest is not None
            self.assertEqual(len(manifest.charts), 22)
            self.assertEqual(
                {entry.id for entry in manifest.charts},
                {spec.chart_id for spec in CHART_SPECS},
            )
            sensitive = {
                "timings.timeline_risposte",
                "accuracy.difficolta_vs_risultato",
                "behavioral.opzioni_vs_performance",
                "behavioral.heatmap_sessioni_tipologie",
                "temporal.accuracy_timeline",
                "temporal.velocity_timeline",
                "advanced.regression_tempo_accuracy",
                "advanced.learning_curve",
                "advanced.performance_projection",
            }
            entries = {entry.id: entry for entry in manifest.charts}
            self.assertTrue(all(entries[item].status == "ready" for item in sensitive))
            for chart_id in sensitive:
                title = CapturingChartGenerator.titles[chart_id].casefold()
                self.assertTrue(any(word in title for word in ("aggregat", "globale", "coorte")))
                self.assertNotIn("test 1", title)
                self.assertNotIn("sessione 1", title)
            public = publisher.current_manifest_path.read_text(encoding="utf-8")
            self.assertNotIn("source_sha256", public)
            self.assertNotIn("Initial Data", public)
            self.assertNotIn("session_id", public)
            snapshot_root = publisher.snapshots_dir / str(manifest.generation_id)
            self.assertEqual(stat.S_IMODE(snapshot_root.stat().st_mode), 0o700)
            for path in snapshot_root.rglob("*"):
                expected_mode = 0o700 if path.is_dir() else 0o600
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), expected_mode, path)

    def test_snapshot_retention_same_dataset_and_shrink_invalidation(self) -> None:
        reports = [report(index) for index in range(1, 7)]
        FastChartGenerator.calls = 0
        with tempfile.TemporaryDirectory() as temporary:
            publisher = ChartSnapshotPublisher(
                Path(temporary),
                minimum_aggregate_sessions=3,
                snapshots_to_keep=3,
            )
            with patch("feedback_service.snapshots.ChartGenerator", FastChartGenerator):
                first = publisher.publish(reports[:3])
                same = publisher.publish(reports[:3])
                second = publisher.publish(reports[:4])
                third = publisher.publish(reports[:5])
                fourth = publisher.publish(reports[:6])
                assert all(item is not None for item in (first, same, second, third, fourth))
                assert first is not None and same is not None
                assert second is not None and third is not None and fourth is not None
                self.assertEqual(first.generation_id, same.generation_id)
                self.assertEqual(FastChartGenerator.calls, 4)
                retained = {
                    path.name
                    for path in publisher.snapshots_dir.iterdir()
                    if path.is_dir()
                }
                self.assertEqual(
                    retained,
                    {str(second.generation_id), str(third.generation_id), str(fourth.generation_id)},
                )
                entry = second.charts[0]
                self.assertIsNotNone(
                    publisher.read_asset(
                        str(second.generation_id), entry.category, entry.filename
                    )
                )
                after_shrink = publisher.publish(reports[:4])
                assert after_shrink is not None
                self.assertEqual(
                    {path.name for path in publisher.snapshots_dir.iterdir() if path.is_dir()},
                    {str(after_shrink.generation_id)},
                )
                self.assertIsNone(
                    publisher.read_asset(
                        str(fourth.generation_id),
                        fourth.charts[0].category,
                        fourth.charts[0].filename,
                    )
                )
                self.assertIsNone(publisher.publish(reports[:2]))
                self.assertIsNone(publisher.load_current_manifest())
                self.assertFalse(list(publisher.snapshots_dir.iterdir()))

    def test_equal_count_replacement_is_published_from_persistent_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = create_app(settings(Path(temporary), retention_days=1))
            store: FeedbackStore = app.state.feedback_store
            publisher: ChartSnapshotPublisher = app.state.snapshot_publisher
            future = time.time() + (10 * 86_400)
            store.save(report(1), created_at=future)
            store.save(report(2), created_at=future)
            store.save(report(3), created_at=time.time() - (2 * 86_400))

            before = store.snapshot_dataset()
            FastChartGenerator.calls = 0
            with patch("feedback_service.snapshots.ChartGenerator", FastChartGenerator):
                first = publisher.publish(
                    before.payloads,
                    source_token=before.source_token,
                )
                assert first is not None

                replacement = store.save(report(4), created_at=future)
                after = store.snapshot_dataset()
                self.assertEqual(replacement.purged_receipts, 1)
                self.assertEqual(len(after.payloads), len(before.payloads))
                self.assertGreater(after.revision, before.revision)
                self.assertNotEqual(after.source_token, before.source_token)

                # Simulate a process crash after the DB commit and before the
                # HTTP process can invalidate the chart publisher.
                result = app.state.coordinator.publication_tick()
                second = publisher.load_current_manifest()
                assert second is not None
                self.assertEqual(result.action, "published")
                self.assertNotEqual(second.generation_id, first.generation_id)
                self.assertEqual(second.session_count, first.session_count)
                self.assertTrue(
                    publisher.current_snapshot_matches(
                        after.source_token,
                        len(after.payloads),
                    )
                )
                self.assertEqual(FastChartGenerator.calls, 2)

    def test_crash_between_manifest_and_private_source_state_never_marks_unchanged(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = create_app(settings(Path(temporary)))
            store: FeedbackStore = app.state.feedback_store
            publisher: ChartSnapshotPublisher = app.state.snapshot_publisher
            for index in range(1, 4):
                store.save(report(index))

            FastChartGenerator.calls = 0
            with patch("feedback_service.snapshots.ChartGenerator", FastChartGenerator):
                first = publish_store_dataset(publisher, store)
                assert first is not None
                store.save(report(4))
                changed = store.snapshot_dataset()

                with (
                    patch.object(
                        publisher,
                        "_atomic_source_state",
                        side_effect=RuntimeError("simulated crash"),
                    ),
                    self.assertRaises(RuntimeError),
                ):
                    publisher.publish(
                        changed.payloads,
                        source_token=changed.source_token,
                    )

                self.assertEqual(publisher.current_snapshot_integrity(), "invalid")
                self.assertFalse(
                    publisher.current_snapshot_matches(
                        changed.source_token,
                        len(changed.payloads),
                    )
                )
                repaired = app.state.coordinator.publication_tick()
                current = publisher.load_current_manifest()
                assert current is not None
                self.assertEqual(repaired.action, "published")
                self.assertNotEqual(current.generation_id, first.generation_id)
                self.assertTrue(
                    publisher.current_snapshot_matches(
                        changed.source_token,
                        len(changed.payloads),
                    )
                )
                public_manifest = publisher.current_manifest_path.read_text(
                    encoding="utf-8"
                )
                self.assertNotIn("source_token", public_manifest)
                self.assertEqual(FastChartGenerator.calls, 3)


class FeedbackHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_never_renders_and_manual_periodic_tick_publishes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            active_settings = settings(Path(temporary))
            app = create_app(active_settings)
            publisher: ChartSnapshotPublisher = app.state.snapshot_publisher
            store: FeedbackStore = app.state.feedback_store
            FastChartGenerator.calls = 0
            with patch("feedback_service.snapshots.ChartGenerator", FastChartGenerator):
                async with app.router.lifespan_context(app):
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(
                        transport=transport,
                        base_url="http://feedback",
                    ) as client:
                        first_payload = report(1, correct=0)
                        first_key = str(uuid4())
                        first = await client.post(
                            "/api/revisione",
                            json=first_payload,
                            headers={"Idempotency-Key": first_key},
                        )
                        retry = await client.post(
                            "/api/revisione",
                            json=first_payload,
                            headers={"Idempotency-Key": first_key},
                        )
                        zero = await client.post(
                            "/api/revisione",
                            json=zero_report(),
                            headers={"Idempotency-Key": str(uuid4())},
                        )
                        third_payload = report(3, correct=2)
                        third = await client.post(
                            "/api/revisione",
                            json=third_payload,
                            headers={"Idempotency-Key": str(uuid4())},
                        )
                        self.assertEqual(FastChartGenerator.calls, 0)
                        self.assertIsNone(publisher.load_current_manifest())

                        await app.state.publication_tick()
                        manifest = publisher.load_current_manifest()
                        assert manifest is not None
                        self.assertEqual(FastChartGenerator.calls, 1)
                        await app.state.publication_tick()
                        self.assertEqual(FastChartGenerator.calls, 1)

                        manifest_response = await client.get(
                            "/api/feedback/charts/manifest"
                        )
                        entry = manifest.charts[0]
                        asset = await client.get(entry.url)
                        openapi = (await client.get("/openapi.json")).json()

                        changed = copy.deepcopy(first_payload)
                        changed["Domande"][0]["Domanda nº 1"]["Domanda"] = "Diversa"
                        conflict = await client.post(
                            "/api/revisione",
                            json=changed,
                            headers={"Idempotency-Key": first_key},
                        )
                        invalid_key = await client.post(
                            "/api/revisione",
                            json=first_payload,
                            headers={"Idempotency-Key": "invalid"},
                        )
                        surrogate_payload = copy.deepcopy(third_payload)
                        surrogate_payload["Domande"][0]["Domanda nº 1"]["Domanda"] = "\ud800"
                        surrogate = await client.post(
                            "/api/revisione",
                            content=json.dumps(surrogate_payload, ensure_ascii=True).encode(),
                            headers={"Content-Type": "application/json"},
                        )

                    self.assertEqual(first.status_code, 201)
                    self.assertEqual(retry.json(), first.json())
                    self.assertEqual(first.json()["filename"], f"{first_key}.json")
                    self.assertEqual(zero.status_code, 201)
                    self.assertEqual(third.status_code, 201)
                    self.assertEqual(conflict.status_code, 409)
                    self.assertEqual(invalid_key.status_code, 400)
                    self.assertEqual(surrogate.status_code, 422)
                    self.assertEqual(len(store.snapshot_payloads()), 3)
                    self.assertEqual(manifest_response.headers["cache-control"], "private, no-store")
                    self.assertNotIn("source_sha256", manifest_response.json())
                    self.assertEqual(asset.status_code, 200)
                    self.assertEqual(asset.headers["cache-control"], "private, no-store")
                    operation = openapi["paths"]["/api/revisione"]["post"]
                    self.assertIn("requestBody", operation)
                    self.assertEqual(operation["parameters"][0]["name"], "Idempotency-Key")

    async def test_scheduler_waits_for_interval_survives_failure_and_ready_tracks_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = create_app(settings(Path(temporary), interval=1))
            store: FeedbackStore = app.state.feedback_store
            for index in range(1, 4):
                store.save(report(index))
            publisher: ChartSnapshotPublisher = app.state.snapshot_publisher
            original_publish = publisher.publish
            publish_calls = 0

            def flaky_publish(
                payloads: list[dict[str, Any]],
                expected_epoch: int | None = None,
                *,
                source_token: str | None = None,
            ) -> Any:
                nonlocal publish_calls
                publish_calls += 1
                if publish_calls == 1:
                    raise RuntimeError("transient render failure")
                return original_publish(
                    payloads,
                    expected_epoch,
                    source_token=source_token,
                )

            FastChartGenerator.calls = 0
            with (
                patch("feedback_service.snapshots.ChartGenerator", FastChartGenerator),
                patch.object(publisher, "publish", side_effect=flaky_publish),
            ):
                async with app.router.lifespan_context(app):
                    self.assertIsNone(publisher.load_current_manifest())
                    self.assertEqual(FastChartGenerator.calls, 0)
                    await asyncio.sleep(1.15)
                    self.assertFalse(app.state.publication_task.done())
                    self.assertIsNone(publisher.load_current_manifest())
                    deadline = time.monotonic() + 2.0
                    while publisher.load_current_manifest() is None and time.monotonic() < deadline:
                        await asyncio.sleep(0.1)
                    self.assertIsNotNone(publisher.load_current_manifest())
                    self.assertEqual(FastChartGenerator.calls, 1)
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(
                        transport=transport,
                        base_url="http://feedback",
                    ) as client:
                        ready = await client.get("/ready")
                    self.assertEqual(ready.status_code, 200)
                    self.assertFalse(app.state.retention_task.done())

            self.assertIsNone(app.state.publication_task)
            self.assertIsNone(app.state.retention_task)
            self.assertIsNone(app.state.feedback_io_executor)

    async def test_post_purge_invalidates_without_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            active_settings = settings(Path(temporary), retention_days=1)
            app = create_app(active_settings)
            store: FeedbackStore = app.state.feedback_store
            future = time.time() + (10 * 86_400)
            store.save(report(1), created_at=future)
            store.save(report(2), created_at=future)
            store.save(report(3))
            publisher: ChartSnapshotPublisher = app.state.snapshot_publisher
            FastChartGenerator.calls = 0
            with patch("feedback_service.snapshots.ChartGenerator", FastChartGenerator):
                manifest = publish_store_dataset(publisher, store)
                assert manifest is not None
                self.assertEqual(FastChartGenerator.calls, 1)
                async with app.router.lifespan_context(app):
                    transport = httpx.ASGITransport(app=app)
                    with patch(
                        "feedback_service.storage.time.time",
                        return_value=time.time() + (2 * 86_400),
                    ):
                        async with httpx.AsyncClient(
                            transport=transport,
                            base_url="http://feedback",
                        ) as client:
                            response = await client.post(
                                "/api/revisione",
                                json=report(4),
                                headers={"Idempotency-Key": str(uuid4())},
                            )
                            missing = await client.get("/api/feedback/charts/manifest")
                    self.assertEqual(response.status_code, 201)
                    self.assertEqual(missing.status_code, 404)
                    self.assertEqual(missing.headers["cache-control"], "private, no-store")
                    self.assertEqual(FastChartGenerator.calls, 1)
                    self.assertFalse(list(publisher.snapshots_dir.iterdir()))
                    self.assertIsNone(
                        publisher.read_asset(
                            str(manifest.generation_id),
                            manifest.charts[0].category,
                            manifest.charts[0].filename,
                        )
                    )

    async def test_conflict_after_purge_still_invalidates_without_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            active_settings = settings(Path(temporary), retention_days=1)
            app = create_app(active_settings)
            store: FeedbackStore = app.state.feedback_store
            idempotency_key = str(uuid4())
            future = time.time() + (10 * 86_400)
            store.save(report(1), idempotency_key, created_at=future)
            store.save(report(2))
            store.save(report(3), created_at=future)
            publisher: ChartSnapshotPublisher = app.state.snapshot_publisher
            FastChartGenerator.calls = 0
            with patch("feedback_service.snapshots.ChartGenerator", FastChartGenerator):
                manifest = publish_store_dataset(publisher, store)
                assert manifest is not None
                async with app.router.lifespan_context(app):
                    changed = report(1)
                    changed["Domande"][0]["Domanda nº 1"]["Domanda"] = "Diversa"
                    transport = httpx.ASGITransport(app=app)
                    with patch(
                        "feedback_service.storage.time.time",
                        return_value=time.time() + (2 * 86_400),
                    ):
                        async with httpx.AsyncClient(
                            transport=transport,
                            base_url="http://feedback",
                        ) as client:
                            conflict = await client.post(
                                "/api/revisione",
                                json=changed,
                                headers={"Idempotency-Key": idempotency_key},
                            )
                            missing = await client.get("/api/feedback/charts/manifest")

                    self.assertEqual(conflict.status_code, 409)
                    self.assertEqual(missing.status_code, 404)
                    self.assertEqual(
                        missing.headers["cache-control"],
                        "private, no-store",
                    )
                    self.assertEqual(len(store.snapshot_payloads()), 2)
                    self.assertIsNone(publisher.load_current_manifest())
                    self.assertFalse(list(publisher.snapshots_dir.iterdir()))
                    self.assertEqual(FastChartGenerator.calls, 1)
                    self.assertEqual(await app.state.retention_tick(), 0)

    async def test_tick_repairs_deleted_or_corrupt_asset_with_same_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = create_app(settings(Path(temporary)))
            store: FeedbackStore = app.state.feedback_store
            for index in range(1, 4):
                store.save(report(index))
            publisher: ChartSnapshotPublisher = app.state.snapshot_publisher
            FastChartGenerator.calls = 0
            with patch("feedback_service.snapshots.ChartGenerator", FastChartGenerator):
                first = publish_store_dataset(publisher, store)
                assert first is not None
                self.assertEqual(publisher.current_snapshot_integrity(), "valid")
                async with app.router.lifespan_context(app):
                    deleted_entry = first.charts[0]
                    deleted_path = publisher.resolve_asset(
                        str(first.generation_id),
                        deleted_entry.category,
                        deleted_entry.filename,
                    )
                    assert deleted_path is not None
                    deleted_path.unlink()
                    self.assertEqual(publisher.current_snapshot_integrity(), "invalid")

                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(
                        transport=transport,
                        base_url="http://feedback",
                    ) as client:
                        broken_ready = await client.get("/ready")
                    self.assertEqual(broken_ready.status_code, 503)
                    self.assertEqual(FastChartGenerator.calls, 1)

                    await app.state.publication_tick()
                    second = publisher.load_current_manifest()
                    assert second is not None
                    self.assertNotEqual(second.generation_id, first.generation_id)
                    self.assertEqual(second.session_count, first.session_count)
                    self.assertEqual(publisher.current_snapshot_integrity(), "valid")
                    self.assertEqual(FastChartGenerator.calls, 2)
                    self.assertIsNone(
                        publisher.load_generation_manifest(str(first.generation_id))
                    )

                    corrupt_entry = second.charts[1]
                    corrupt_path = publisher.resolve_asset(
                        str(second.generation_id),
                        corrupt_entry.category,
                        corrupt_entry.filename,
                    )
                    assert corrupt_path is not None
                    corrupt_path.write_bytes(b"corrupt")
                    self.assertEqual(publisher.current_snapshot_integrity(), "invalid")
                    await app.state.publication_tick()
                    third = publisher.load_current_manifest()
                    assert third is not None
                    self.assertNotEqual(third.generation_id, second.generation_id)
                    self.assertEqual(publisher.current_snapshot_integrity(), "valid")
                    self.assertEqual(FastChartGenerator.calls, 3)

                    async with httpx.AsyncClient(
                        transport=transport,
                        base_url="http://feedback",
                    ) as client:
                        healed_ready = await client.get("/ready")
                    self.assertEqual(healed_ready.status_code, 200)

    async def test_purge_after_payload_snapshot_aborts_stale_publication(self) -> None:
        captured = threading.Event()
        release = threading.Event()

        with tempfile.TemporaryDirectory() as temporary:
            active_settings = settings(Path(temporary), retention_days=1)
            app = create_app(active_settings)
            store: FeedbackStore = app.state.feedback_store
            future = time.time() + (10 * 86_400)
            store.save(report(1))
            store.save(report(2), created_at=future)
            store.save(report(3), created_at=future)
            publisher: ChartSnapshotPublisher = app.state.snapshot_publisher
            FastChartGenerator.calls = 0

            with patch("feedback_service.snapshots.ChartGenerator", FastChartGenerator):
                first = publish_store_dataset(publisher, store)
                assert first is not None
                original_snapshot = store.snapshot_dataset

                def blocking_snapshot() -> Any:
                    dataset = original_snapshot()
                    captured.set()
                    if not release.wait(5):
                        raise TimeoutError("snapshot test non rilasciato")
                    return dataset

                async with app.router.lifespan_context(app):
                    with patch.object(
                        store,
                        "snapshot_dataset",
                        side_effect=blocking_snapshot,
                    ):
                        tick = asyncio.create_task(app.state.publication_tick())
                        try:
                            deadline = time.monotonic() + 2
                            while not captured.is_set() and time.monotonic() < deadline:
                                await asyncio.sleep(0.01)
                            self.assertTrue(captured.is_set())

                            with patch(
                                "feedback_service.storage.time.time",
                                return_value=time.time() + (2 * 86_400),
                            ):
                                self.assertEqual(await app.state.retention_tick(), 1)
                        finally:
                            release.set()

                        with self.assertRaises(SnapshotInvalidatedError):
                            await tick

                    self.assertEqual(len(store.snapshot_payloads()), 2)
                    self.assertIsNone(publisher.load_current_manifest())
                    self.assertFalse(list(publisher.snapshots_dir.iterdir()))
                    self.assertEqual(FastChartGenerator.calls, 1)

    async def test_hourly_retention_tick_is_independent_from_long_publish_interval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            active_settings = settings(Path(temporary), retention_days=1)
            app = create_app(active_settings)
            store: FeedbackStore = app.state.feedback_store
            future = time.time() + (10 * 86_400)
            store.save(report(1))
            store.save(report(2), created_at=future)
            store.save(report(3), created_at=future)
            publisher: ChartSnapshotPublisher = app.state.snapshot_publisher
            FastChartGenerator.calls = 0
            with patch("feedback_service.snapshots.ChartGenerator", FastChartGenerator):
                self.assertIsNotNone(publish_store_dataset(publisher, store))
                async with app.router.lifespan_context(app):
                    with patch(
                        "feedback_service.storage.time.time",
                        return_value=time.time() + (2 * 86_400),
                    ):
                        deleted = await app.state.retention_tick()
                    self.assertEqual(deleted, 1)
                    self.assertIsNone(publisher.load_current_manifest())
                    self.assertFalse(list(publisher.snapshots_dir.iterdir()))
                    self.assertEqual(FastChartGenerator.calls, 1)
                    self.assertFalse(app.state.publication_task.done())
                    self.assertFalse(app.state.retention_task.done())

    async def test_submission_during_render_is_deferred_to_the_next_tick(self) -> None:
        started = threading.Event()
        release = threading.Event()

        class BlockingGenerator(FastChartGenerator):
            calls = 0

            def generate_all_charts(self) -> list[ChartArtifact]:
                started.set()
                if not release.wait(5):
                    raise TimeoutError("renderer test non rilasciato")
                return super().generate_all_charts()

        with tempfile.TemporaryDirectory() as temporary:
            app = create_app(settings(Path(temporary)))
            store: FeedbackStore = app.state.feedback_store
            for index in range(1, 4):
                store.save(report(index))
            publisher: ChartSnapshotPublisher = app.state.snapshot_publisher
            with patch("feedback_service.snapshots.ChartGenerator", BlockingGenerator):
                async with app.router.lifespan_context(app):
                    tick = asyncio.create_task(app.state.publication_tick())
                    try:
                        deadline = time.monotonic() + 2
                        while not started.is_set() and time.monotonic() < deadline:
                            await asyncio.sleep(0.01)
                        self.assertTrue(started.is_set())
                        transport = httpx.ASGITransport(app=app)
                        async with httpx.AsyncClient(
                            transport=transport,
                            base_url="http://feedback",
                        ) as client:
                            received = await client.post(
                                "/api/revisione",
                                json=report(4),
                                headers={"Idempotency-Key": str(uuid4())},
                            )
                        self.assertEqual(received.status_code, 201)
                        self.assertEqual(BlockingGenerator.calls, 0)
                    finally:
                        release.set()
                    await tick
                    first = publisher.load_current_manifest()
                    assert first is not None
                    self.assertEqual(first.session_count, 3)
                    self.assertEqual(BlockingGenerator.calls, 1)
                    await app.state.publication_tick()
                    second = publisher.load_current_manifest()
                    assert second is not None
                    self.assertEqual(second.session_count, 4)
                    self.assertEqual(BlockingGenerator.calls, 2)

    async def test_quota_metrics_and_request_id_are_pii_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            active_settings = replace(
                settings(Path(temporary)),
                max_receipts=1,
                min_free_bytes=0,
            )
            app = create_app(active_settings)
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://feedback",
                ) as client:
                    accepted = await client.post(
                        "/api/revisione",
                        json=report(1),
                        headers={
                            "Idempotency-Key": str(uuid4()),
                            "X-Request-ID": "trace-123",
                        },
                    )
                    full = await client.post(
                        "/api/revisione",
                        json=report(2),
                        headers={"Idempotency-Key": str(uuid4())},
                    )
                    metrics = await client.get("/metrics")
                    openapi = (await client.get("/openapi.json")).json()

            self.assertEqual(accepted.status_code, 201)
            self.assertEqual(accepted.headers["x-request-id"], "trace-123")
            self.assertEqual(full.status_code, 507)
            self.assertEqual(metrics.status_code, 200)
            self.assertEqual(metrics.headers["cache-control"], "private, no-store")
            self.assertIn('outcome="accepted"} 1', metrics.text)
            self.assertIn('outcome="quota_exceeded"} 1', metrics.text)
            self.assertIn("testlogica_feedback_receipts 1", metrics.text)
            self.assertNotIn("università", metrics.text)
            self.assertNotIn("Domanda 1", metrics.text)
            self.assertNotIn("/metrics", openapi["paths"])

    async def test_http_events_use_the_uvicorn_logger_without_payload_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = create_app(settings(Path(temporary)))
            with self.assertLogs("uvicorn.error", level="INFO") as captured:
                async with app.router.lifespan_context(app):
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(
                        transport=transport,
                        base_url="http://feedback",
                    ) as client:
                        response = await client.get(
                            "/health",
                            headers={"X-Request-ID": "observable-request"},
                        )

            self.assertEqual(response.status_code, 200)
            events = [
                json.loads(record.getMessage())
                for record in captured.records
                if record.getMessage().startswith("{")
            ]
            self.assertEqual(len(events), 1)
            self.assertEqual(
                events[0],
                {
                    "event": "http_request",
                    "method": "GET",
                    "path": "/health",
                    "request_id": "observable-request",
                    "status": 200,
                    "duration_ms": events[0]["duration_ms"],
                },
            )
            self.assertNotIn("Initial Data", captured.output[0])


if __name__ == "__main__":
    unittest.main()
