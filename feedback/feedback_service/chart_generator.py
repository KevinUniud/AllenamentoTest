"""Headless generation of the 22 legacy feedback charts."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import matplotlib
import numpy as np

matplotlib.use("Agg", force=True)
from matplotlib import pyplot as plt  # noqa: E402

from feedback_service.analytics import wilson_interval
from feedback_service.data_processor import DataProcessor

LOGGER = logging.getLogger(__name__)
ChartStatus = Literal["ready", "insufficient_data"]


@dataclass(frozen=True, slots=True)
class ChartSpec:
    category: str
    filename: str

    @property
    def chart_id(self) -> str:
        return f"{self.category}.{self.filename.removesuffix('.png')}"


@dataclass(frozen=True, slots=True)
class ChartArtifact:
    spec: ChartSpec
    path: Path
    status: ChartStatus


CHART_SPECS: tuple[ChartSpec, ...] = (
    ChartSpec("general", "percentuale_domande_corrette.png"),
    ChartSpec("general", "corrette_vs_errate.png"),
    ChartSpec("general", "performance_summary.png"),
    ChartSpec("timings", "tempo_medio_risposta.png"),
    ChartSpec("timings", "tempo_per_tipologia.png"),
    ChartSpec("timings", "tempo_vs_correttezza.png"),
    ChartSpec("timings", "distribuzione_tempi.png"),
    ChartSpec("timings", "boxplot_tempi_tipologia.png"),
    ChartSpec("timings", "timeline_risposte.png"),
    ChartSpec("accuracy", "accuratezza_per_tipologia.png"),
    ChartSpec("accuracy", "multipanel_tipologia.png"),
    ChartSpec("accuracy", "radar_competenze.png"),
    ChartSpec("accuracy", "difficolta_vs_risultato.png"),
    ChartSpec("demographics", "performance_per_demographic.png"),
    ChartSpec("demographics", "feedback_correlation.png"),
    ChartSpec("behavioral", "opzioni_vs_performance.png"),
    ChartSpec("behavioral", "heatmap_sessioni_tipologie.png"),
    ChartSpec("temporal", "accuracy_timeline.png"),
    ChartSpec("temporal", "velocity_timeline.png"),
    ChartSpec("advanced", "regression_tempo_accuracy.png"),
    ChartSpec("advanced", "learning_curve.png"),
    ChartSpec("advanced", "performance_projection.png"),
)


class ChartGenerator:
    """Generate every expected asset into an explicit staging directory."""

    def __init__(
        self,
        data_processor: DataProcessor,
        output_dir: Path,
        *,
        minimum_aggregate_sessions: int,
        dpi: int = 120,
    ) -> None:
        if minimum_aggregate_sessions < 2:
            raise ValueError("minimum_aggregate_sessions deve essere almeno 2")
        self.dp = data_processor
        self.metrics = (
            data_processor.metrics
            if data_processor.metrics is not None
            else data_processor.extract_metrics()
        )
        self.output_dir = output_dir.resolve()
        self.minimum_aggregate_sessions = minimum_aggregate_sessions
        self.dpi = dpi

    @staticmethod
    def _spec(category: str, filename: str) -> ChartSpec:
        return ChartSpec(category, filename)

    def _save(self, fig: Any, spec: ChartSpec, *, status: ChartStatus = "ready") -> ChartArtifact:
        directory = self.output_dir / spec.category
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = directory / spec.filename
        try:
            fig.savefig(path, dpi=self.dpi, bbox_inches="tight", metadata={"Software": "TestLogica"})
            path.chmod(0o600)
        finally:
            plt.close(fig)
        return ChartArtifact(spec=spec, path=path, status=status)

    def _placeholder(self, spec: ChartSpec, message: str = "Dati insufficienti") -> ChartArtifact:
        fig, axis = plt.subplots(figsize=(9, 5))
        axis.axis("off")
        axis.text(0.5, 0.55, message, ha="center", va="center", fontsize=18, fontweight="bold")
        axis.text(0.5, 0.42, "Il grafico si aggiornerà con nuove sessioni.", ha="center", va="center", fontsize=11)
        return self._save(fig, spec, status="insufficient_data")

    def _chronological_cohorts(self) -> list[list[dict[str, Any]]]:
        sessions = self.metrics["by_session"]
        size = self.minimum_aggregate_sessions
        return [
            sessions[index : index + size]
            for index in range(0, len(sessions) - size + 1, size)
        ]

    def _daily_aggregates(self, field: str) -> tuple[list[Any], list[float]]:
        """Return date buckets containing at least ``k`` independent reports."""
        grouped: dict[Any, list[float]] = {}
        for session in self.metrics["by_session"]:
            started_at = session["datetime"]
            if started_at is not None:
                grouped.setdefault(started_at.date(), []).append(float(session[field]))
        safe = {
            day: values
            for day, values in grouped.items()
            if len(values) >= self.minimum_aggregate_sessions
        }
        days = sorted(safe)
        return days, [float(np.mean(safe[day])) for day in days]

    def chart_percentuale_domande_corrette(self) -> ChartArtifact:
        spec = self._spec("general", "percentuale_domande_corrette.png")
        sessions = self.metrics["by_session"]
        if len(sessions) < self.minimum_aggregate_sessions:
            return self._placeholder(spec)
        total = sum(int(session["total_questions"]) for session in sessions)
        correct = sum(int(session["correct_answers"]) for session in sessions)
        if total <= 0:
            return self._placeholder(spec)
        aggregate_accuracy = correct / total * 100
        lower, upper = wilson_interval(correct, total)
        fig, axis = plt.subplots(figsize=(9, 5))
        axis.bar(
            [f"{len(sessions)} sessioni · {total} domande"],
            [aggregate_accuracy],
            yerr=[[aggregate_accuracy - lower], [upper - aggregate_accuracy]],
            capsize=8,
            color="#146c94",
        )
        axis.set(
            title="Accuratezza aggregata con intervallo di confidenza 95%",
            ylabel="Risposte corrette (%)",
            ylim=(-5, 105),
        )
        return self._save(fig, spec)

    def chart_corrette_vs_errate(self) -> ChartArtifact:
        spec = self._spec("general", "corrette_vs_errate.png")
        sessions = self.metrics["by_session"]
        if len(sessions) < self.minimum_aggregate_sessions:
            return self._placeholder(spec)
        correct = sum(session["correct_answers"] for session in sessions)
        wrong = sum(session["total_questions"] - session["correct_answers"] for session in sessions)
        fig, axis = plt.subplots(figsize=(9, 5))
        axis.bar(["Campione aggregato"], [correct], label="Corrette", color="#2e8b57")
        axis.bar(["Campione aggregato"], [wrong], bottom=[correct], label="Errate", color="#c94c4c")
        axis.set(title="Risposte aggregate corrette ed errate", ylabel="Risposte")
        axis.legend()
        return self._save(fig, spec)

    def chart_performance_summary(self) -> ChartArtifact:
        spec = self._spec("general", "performance_summary.png")
        stats = self.dp.get_summary_stats()
        fig, axes = plt.subplots(2, 2, figsize=(9, 7))
        values = (
            (stats["total_sessions"], "Sessioni"),
            (f"{stats['overall_accuracy']:.1f}%", "Accuratezza aggregata"),
            (stats["total_questions_answered"], "Domande"),
            (f"{stats['avg_response_time']:.2f}s", "Tempo medio"),
        )
        for axis, (value, label) in zip(axes.flat, values, strict=True):
            axis.axis("off")
            axis.text(0.5, 0.58, str(value), ha="center", va="center", fontsize=34, fontweight="bold")
            axis.text(0.5, 0.25, label, ha="center", va="center", fontsize=12)
        fig.suptitle("Riepilogo delle prestazioni", fontsize=16, fontweight="bold")
        status: ChartStatus = "ready" if stats["total_sessions"] else "insufficient_data"
        return self._save(fig, spec, status=status)

    def chart_tempo_medio_risposta(self) -> ChartArtifact:
        spec = self._spec("timings", "tempo_medio_risposta.png")
        grouped: dict[int, list[float]] = {}
        for number, elapsed in self.metrics["response_times"]:
            grouped.setdefault(number, []).append(elapsed)
        grouped = {
            number: values
            for number, values in grouped.items()
            if len(values) >= self.minimum_aggregate_sessions
        }
        if not grouped:
            return self._placeholder(spec)
        numbers = sorted(grouped)
        means = [float(np.mean(grouped[number])) for number in numbers]
        fig, axis = plt.subplots(figsize=(9, 5))
        axis.bar(numbers, means, color="#2e8b57")
        axis.set(title="Tempo medio di risposta per domanda", xlabel="Numero domanda", ylabel="Secondi")
        return self._save(fig, spec)

    def chart_tempo_per_tipologia(self) -> ChartArtifact:
        spec = self._spec("timings", "tempo_per_tipologia.png")
        grouped: dict[str, list[float]] = {}
        for session in self.metrics["by_session"]:
            per_session: dict[str, list[float]] = {}
            for response in session["responses"]:
                per_session.setdefault(response["tipologia"], []).append(response["time"])
            for category, values in per_session.items():
                grouped.setdefault(category, []).append(float(np.mean(values)))
        grouped = {
            category: values
            for category, values in grouped.items()
            if len(values) >= self.minimum_aggregate_sessions
        }
        if not grouped:
            return self._placeholder(spec)
        labels = sorted(grouped)
        means = [float(np.mean(grouped[label])) for label in labels]
        fig, axis = plt.subplots(figsize=(10, 5))
        axis.bar(labels, means, color="#65a9cf")
        axis.set(title="Tempo medio per tipologia", ylabel="Secondi")
        axis.tick_params(axis="x", rotation=35)
        fig.tight_layout()
        return self._save(fig, spec)

    def chart_tempo_vs_correttezza(self) -> ChartArtifact:
        spec = self._spec("timings", "tempo_vs_correttezza.png")
        grouped: dict[bool, list[float]] = {True: [], False: []}
        for session in self.metrics["by_session"]:
            for expected in (True, False):
                values = [
                    response["time"]
                    for response in session["responses"]
                    if response["is_correct"] is expected
                ]
                if values:
                    grouped[expected].append(float(np.mean(values)))
        safe_groups = {
            expected: values
            for expected, values in grouped.items()
            if len(values) >= self.minimum_aggregate_sessions
        }
        if not safe_groups:
            return self._placeholder(spec)
        fig, axis = plt.subplots(figsize=(9, 5))
        labels = ["Corrette" if expected else "Errate" for expected in safe_groups]
        means = [float(np.mean(values)) for values in safe_groups.values()]
        colors = ["#2e8b57" if expected else "#c94c4c" for expected in safe_groups]
        axis.bar(labels, means, color=colors)
        axis.set(
            title="Tempo medio aggregato per esito",
            ylabel="Secondi",
        )
        return self._save(fig, spec)

    def chart_distribuzione_tempi(self) -> ChartArtifact:
        spec = self._spec("timings", "distribuzione_tempi.png")
        values = [
            float(np.mean([session["avg_time"] for session in cohort]))
            for cohort in self._chronological_cohorts()
        ]
        if not values:
            return self._placeholder(spec)
        fig, axis = plt.subplots(figsize=(9, 5))
        bins = min(30, max(5, round(np.sqrt(len(values)))))
        axis.hist(values, bins=bins, color="#4682b4", edgecolor="black", alpha=0.75)
        axis.set(
            title="Distribuzione dei tempi medi per coorte aggregata",
            xlabel="Secondi medi",
            ylabel="Numero di coorti",
        )
        return self._save(fig, spec)

    def chart_boxplot_tempi_tipologia(self) -> ChartArtifact:
        spec = self._spec("timings", "boxplot_tempi_tipologia.png")
        grouped: dict[str, list[float]] = {}
        for cohort in self._chronological_cohorts():
            per_category: dict[str, list[float]] = {}
            for session in cohort:
                per_session: dict[str, list[float]] = {}
                for response in session["responses"]:
                    per_session.setdefault(response["tipologia"], []).append(response["time"])
                for category, values in per_session.items():
                    per_category.setdefault(category, []).append(float(np.mean(values)))
            for category, values in per_category.items():
                if len(values) >= self.minimum_aggregate_sessions:
                    grouped.setdefault(category, []).append(float(np.mean(values)))
        if not grouped:
            return self._placeholder(spec)
        labels = sorted(grouped)
        fig, axis = plt.subplots(figsize=(10, 5))
        axis.boxplot([grouped[label] for label in labels], tick_labels=labels, patch_artist=True)
        axis.set(
            title="Distribuzione aggregata dei tempi per tipologia",
            ylabel="Secondi medi per coorte",
        )
        axis.tick_params(axis="x", rotation=35)
        fig.tight_layout()
        return self._save(fig, spec)

    def chart_timeline_risposte(self) -> ChartArtifact:
        spec = self._spec("timings", "timeline_risposte.png")
        grouped: dict[int, list[float]] = {}
        for number, elapsed in self.metrics["response_times"]:
            grouped.setdefault(number, []).append(elapsed)
        grouped = {
            number: values
            for number, values in grouped.items()
            if len(values) >= self.minimum_aggregate_sessions
        }
        if not grouped:
            return self._placeholder(spec)
        numbers = sorted(grouped)
        means = [float(np.mean(grouped[number])) for number in numbers]
        fig, axis = plt.subplots(figsize=(10, 5))
        axis.plot(numbers, means, marker="o", color="#7048a8")
        axis.set(
            title="Tempo aggregato per posizione della domanda",
            xlabel="Posizione della domanda",
            ylabel="Secondi",
        )
        return self._save(fig, spec)

    def chart_accuratezza_per_tipologia(self) -> ChartArtifact:
        spec = self._spec("accuracy", "accuratezza_per_tipologia.png")
        stats = self.dp.get_category_stats(
            minimum_sessions=self.minimum_aggregate_sessions,
        )
        if not stats:
            return self._placeholder(spec)
        labels = sorted(stats)
        values = [float(stats[label]["accuracy"]) for label in labels]
        intervals = [
            wilson_interval(
                int(stats[label]["correct"]),
                int(stats[label]["total"]),
            )
            for label in labels
        ]
        errors = [
            [value - interval[0] for value, interval in zip(values, intervals, strict=True)],
            [interval[1] - value for value, interval in zip(values, intervals, strict=True)],
        ]
        fig, axis = plt.subplots(figsize=(10, 5))
        axis.bar(labels, values, yerr=errors, capsize=5, color="#db8b34")
        axis.set(
            title="Accuratezza per tipologia · intervallo di confidenza 95%",
            ylabel="Accuratezza (%)",
            ylim=(0, 105),
        )
        axis.tick_params(axis="x", rotation=35)
        fig.tight_layout()
        return self._save(fig, spec)

    def chart_multipanel_tipologia(self) -> ChartArtifact:
        spec = self._spec("accuracy", "multipanel_tipologia.png")
        stats = self.dp.get_category_stats(
            minimum_sessions=self.minimum_aggregate_sessions,
        )
        if not stats:
            return self._placeholder(spec)
        categories = sorted(stats, key=lambda name: int(stats[name]["total"]), reverse=True)[:4]
        fig, axes = plt.subplots(2, 2, figsize=(10, 8))
        for axis in axes.flat:
            axis.axis("off")
        for axis, category in zip(axes.flat, categories, strict=False):
            axis.axis("on")
            values = stats[category]
            axis.bar(["Corrette", "Errate"], [values["correct"], values["wrong"]], color=["#2e8b57", "#c94c4c"])
            axis.set_title(f"{category.capitalize()} · {values['accuracy']:.1f}%")
        fig.suptitle("Principali tipologie", fontweight="bold")
        fig.tight_layout()
        return self._save(fig, spec)

    def chart_radar_competenze(self) -> ChartArtifact:
        spec = self._spec("accuracy", "radar_competenze.png")
        stats = self.dp.get_category_stats(
            minimum_sessions=self.minimum_aggregate_sessions,
        )
        if not stats:
            return self._placeholder(spec)
        labels = sorted(stats)
        values = [float(stats[label]["accuracy"]) for label in labels]
        angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
        closed_angles = angles + angles[:1]
        closed_values = values + values[:1]
        fig, axis = plt.subplots(figsize=(8, 8), subplot_kw={"projection": "polar"})
        axis.plot(closed_angles, closed_values, marker="o", color="#146c94")
        axis.fill(closed_angles, closed_values, alpha=0.2, color="#146c94")
        axis.set_xticks(angles, [label.capitalize() for label in labels])
        axis.set_ylim(0, 100)
        axis.set_title("Radar delle competenze", pad=20, fontweight="bold")
        return self._save(fig, spec)

    def chart_difficolta_vs_risultato(self) -> ChartArtifact:
        spec = self._spec("accuracy", "difficolta_vs_risultato.png")
        grouped: dict[float, list[float]] = {}
        for session in self.metrics["by_session"]:
            if "Difficoltà test" in session["feedback"]:
                difficulty = session["feedback"]["Difficoltà test"]
                grouped.setdefault(difficulty, []).append(session["accuracy"])
        grouped = {
            difficulty: values
            for difficulty, values in grouped.items()
            if len(values) >= self.minimum_aggregate_sessions
        }
        if not grouped:
            return self._placeholder(spec)
        difficulty = sorted(grouped)
        accuracy = [float(np.mean(grouped[value])) for value in difficulty]
        fig, axis = plt.subplots(figsize=(9, 5))
        axis.bar([str(value) for value in difficulty], accuracy, color="#db8b34")
        axis.set(
            title="Risultato aggregato per difficoltà percepita",
            xlabel="Difficoltà (1–5)",
            ylabel="Accuratezza (%)",
            xlim=(0, 6),
            ylim=(-5, 105),
        )
        return self._save(fig, spec)

    def chart_performance_per_demographic(self) -> ChartArtifact:
        spec = self._spec("demographics", "performance_per_demographic.png")
        segments = self.dp.get_demographic_segments(
            minimum_size=self.minimum_aggregate_sessions,
        )
        if not any(segments.values()):
            return self._placeholder(spec)
        fig, axes = plt.subplots(1, 3, figsize=(15, 5))
        definitions = (
            ("by_age_range", "Fascia d'età"),
            ("by_institution", "Istituto"),
            ("by_study_area", "Indirizzo"),
        )
        any_group = False
        for axis, (key, title) in zip(axes, definitions, strict=True):
            groups = segments[key]
            if not groups:
                axis.axis("off")
                continue
            any_group = True
            labels = sorted(groups)
            values = [float(np.mean([session["accuracy"] for session in groups[label]])) for label in labels]
            axis.barh(labels, values, color="#65a9cf")
            axis.set(title=title, xlabel="Accuratezza (%)", xlim=(0, 105))
        fig.suptitle("Prestazioni per segmento demografico", fontweight="bold")
        fig.tight_layout()
        return self._save(fig, spec, status="ready" if any_group else "insufficient_data")

    def chart_feedback_correlation(self) -> ChartArtifact:
        spec = self._spec("demographics", "feedback_correlation.png")
        if len(self.metrics["by_session"]) < self.minimum_aggregate_sessions:
            return self._placeholder(spec)
        correlations = self.dp.get_feedback_correlation(
            minimum_sessions=self.minimum_aggregate_sessions,
        )
        if not correlations:
            return self._placeholder(spec)
        labels = sorted(correlations)
        values = [correlations[label] for label in labels]
        colors = ["#2e8b57" if value >= 0 else "#c94c4c" for value in values]
        fig, axis = plt.subplots(figsize=(10, 5))
        axis.barh(labels, values, color=colors)
        axis.axvline(0, color="black", linewidth=0.8)
        axis.set(title="Correlazione tra feedback e accuratezza", xlabel="Correlazione", xlim=(-1, 1))
        fig.tight_layout()
        return self._save(fig, spec)

    def chart_opzioni_vs_performance(self) -> ChartArtifact:
        spec = self._spec("behavioral", "opzioni_vs_performance.png")
        performance = self.dp.get_options_performance()
        if not performance:
            return self._placeholder(spec)
        labels: list[str] = []
        values: list[float] = []
        colors: list[str] = []
        for option in sorted(performance):
            for state, state_label, color in (
                ("on", "attiva", "#2e8b57"),
                ("off", "disattiva", "#c94c4c"),
            ):
                cohort = performance[option][state]
                if len(cohort) >= self.minimum_aggregate_sessions:
                    labels.append(f"{option} · {state_label}")
                    values.append(float(np.mean(cohort)))
                    colors.append(color)
        if not labels:
            return self._placeholder(spec)
        fig, axis = plt.subplots(figsize=(11, 5))
        axis.bar(labels, values, color=colors)
        axis.set(
            title="Prestazioni aggregate per configurazione",
            ylabel="Accuratezza (%)",
            ylim=(0, 105),
        )
        axis.tick_params(axis="x", rotation=35)
        fig.tight_layout()
        return self._save(fig, spec)

    def chart_heatmap_sessioni_tipologie(self) -> ChartArtifact:
        spec = self._spec("behavioral", "heatmap_sessioni_tipologie.png")
        safe_stats = self.dp.get_category_stats(
            minimum_sessions=self.minimum_aggregate_sessions,
        )
        categories = sorted(safe_stats)
        sessions = self.metrics["by_session"]
        if not categories or not sessions:
            return self._placeholder(spec)
        matrix = np.asarray(
            [[float(safe_stats[category]["accuracy"]) for category in categories]],
            dtype=float,
        )
        fig, axis = plt.subplots(figsize=(11, 6))
        image = axis.imshow(matrix, cmap="RdYlGn", vmin=0, vmax=100, aspect="auto")
        axis.set(
            title="Accuratezza aggregata per tipologia",
            xticks=range(len(categories)),
            xticklabels=categories,
            yticks=[0],
            yticklabels=["Campione aggregato"],
        )
        axis.tick_params(axis="x", rotation=35)
        fig.colorbar(image, ax=axis, label="Accuratezza (%)")
        fig.tight_layout()
        return self._save(fig, spec)

    def chart_accuracy_timeline(self) -> ChartArtifact:
        spec = self._spec("temporal", "accuracy_timeline.png")
        days, accuracies = self._daily_aggregates("accuracy")
        if not days:
            return self._placeholder(spec)
        fig, axis = plt.subplots(figsize=(10, 5))
        if len(days) == 1:
            axis.bar(days, accuracies, width=0.6, color="#146c94")
        else:
            axis.plot(days, accuracies, marker="o", color="#146c94")
        axis.set(
            title="Andamento globale dell'accuratezza per giorno",
            ylabel="Accuratezza media (%)",
            ylim=(0, 105),
        )
        fig.autofmt_xdate()
        return self._save(fig, spec)

    def chart_velocity_timeline(self) -> ChartArtifact:
        spec = self._spec("temporal", "velocity_timeline.png")
        days, average_times = self._daily_aggregates("avg_time")
        if not days:
            return self._placeholder(spec)
        fig, axis = plt.subplots(figsize=(10, 5))
        if len(days) == 1:
            axis.bar(days, average_times, width=0.6, color="#7048a8")
        else:
            axis.plot(days, average_times, marker="s", color="#7048a8")
        axis.set(
            title="Andamento globale del tempo medio per giorno",
            ylabel="Secondi medi per domanda",
        )
        fig.autofmt_xdate()
        return self._save(fig, spec)

    def chart_regression_tempo_accuracy(self) -> ChartArtifact:
        spec = self._spec("advanced", "regression_tempo_accuracy.png")
        cohorts = self._chronological_cohorts()
        if len(cohorts) < 2:
            return self._placeholder(spec)
        times = np.asarray(
            [np.mean([session["avg_time"] for session in cohort]) for cohort in cohorts],
            dtype=float,
        )
        accuracies = np.asarray(
            [np.mean([session["accuracy"] for session in cohort]) for cohort in cohorts],
            dtype=float,
        )
        fig, axis = plt.subplots(figsize=(9, 5))
        axis.scatter(times, accuracies, s=80, alpha=0.7, label="Coorti aggregate")
        status: ChartStatus = "ready"
        if len(np.unique(times)) >= 2:
            polynomial = np.poly1d(np.polyfit(times, accuracies, 1))
            trend = np.linspace(float(min(times)), float(max(times)), 100)
            axis.plot(trend, polynomial(trend), "--", color="#a32626")
        else:
            status = "insufficient_data"
        axis.set(
            title="Relazione aggregata tra tempo e accuratezza",
            xlabel="Secondi medi per domanda (coorte)",
            ylabel="Accuratezza media (%)",
            ylim=(-5, 105),
        )
        axis.legend()
        return self._save(fig, spec, status=status)

    def chart_learning_curve(self) -> ChartArtifact:
        spec = self._spec("advanced", "learning_curve.png")
        cohorts = self._chronological_cohorts()
        if len(cohorts) < 2:
            return self._placeholder(spec)
        accuracies = [
            float(np.mean([session["accuracy"] for session in cohort]))
            for cohort in cohorts
        ]
        cohort_numbers = np.arange(1, len(accuracies) + 1)
        fig, axis = plt.subplots(figsize=(10, 5))
        axis.plot(cohort_numbers, accuracies, marker="o", color="#2e8b57")
        if len(accuracies) >= 3:
            window = min(3, len(accuracies))
            rolling = np.convolve(accuracies, np.ones(window) / window, mode="valid")
            axis.plot(
                np.arange(window, len(accuracies) + 1),
                rolling,
                "--",
                color="#a32626",
                label="Media mobile aggregata",
            )
            axis.legend()
        axis.set(
            title="Andamento globale delle prestazioni",
            xlabel="Coorte temporale aggregata",
            ylabel="Accuratezza media (%)",
            ylim=(-5, 105),
        )
        return self._save(fig, spec)

    def chart_performance_projection(self) -> ChartArtifact:
        spec = self._spec("advanced", "performance_projection.png")
        cohorts = self._chronological_cohorts()
        if len(cohorts) < 2:
            return self._placeholder(spec)
        accuracies = np.asarray(
            [np.mean([session["accuracy"] for session in cohort]) for cohort in cohorts],
            dtype=float,
        )
        cohort_numbers = np.arange(1, len(accuracies) + 1)
        degree = 2 if len(accuracies) >= 3 else 1
        model = np.poly1d(np.polyfit(cohort_numbers, accuracies, degree))
        future = np.arange(1, len(accuracies) + 6)
        predicted = np.clip(model(future), 0, 100)
        fig, axis = plt.subplots(figsize=(10, 5))
        axis.plot(cohort_numbers, accuracies, "o-", label="Coorti aggregate osservate")
        axis.plot(
            future[len(accuracies) :],
            predicted[len(accuracies) :],
            "s--",
            color="#a32626",
            label="Tendenza aggregata",
        )
        axis.set(
            title="Tendenza aggregata delle prestazioni globali",
            xlabel="Coorte temporale aggregata",
            ylabel="Accuratezza media (%)",
            ylim=(-5, 105),
        )
        axis.legend()
        return self._save(fig, spec)

    def generate_all_charts(self) -> list[ChartArtifact]:
        methods: dict[str, Callable[[], ChartArtifact]] = {
            "general.percentuale_domande_corrette": self.chart_percentuale_domande_corrette,
            "general.corrette_vs_errate": self.chart_corrette_vs_errate,
            "general.performance_summary": self.chart_performance_summary,
            "timings.tempo_medio_risposta": self.chart_tempo_medio_risposta,
            "timings.tempo_per_tipologia": self.chart_tempo_per_tipologia,
            "timings.tempo_vs_correttezza": self.chart_tempo_vs_correttezza,
            "timings.distribuzione_tempi": self.chart_distribuzione_tempi,
            "timings.boxplot_tempi_tipologia": self.chart_boxplot_tempi_tipologia,
            "timings.timeline_risposte": self.chart_timeline_risposte,
            "accuracy.accuratezza_per_tipologia": self.chart_accuratezza_per_tipologia,
            "accuracy.multipanel_tipologia": self.chart_multipanel_tipologia,
            "accuracy.radar_competenze": self.chart_radar_competenze,
            "accuracy.difficolta_vs_risultato": self.chart_difficolta_vs_risultato,
            "demographics.performance_per_demographic": self.chart_performance_per_demographic,
            "demographics.feedback_correlation": self.chart_feedback_correlation,
            "behavioral.opzioni_vs_performance": self.chart_opzioni_vs_performance,
            "behavioral.heatmap_sessioni_tipologie": self.chart_heatmap_sessioni_tipologie,
            "temporal.accuracy_timeline": self.chart_accuracy_timeline,
            "temporal.velocity_timeline": self.chart_velocity_timeline,
            "advanced.regression_tempo_accuracy": self.chart_regression_tempo_accuracy,
            "advanced.learning_curve": self.chart_learning_curve,
            "advanced.performance_projection": self.chart_performance_projection,
        }
        if len(self.metrics["by_session"]) < self.minimum_aggregate_sessions:
            return [self._placeholder(spec) for spec in CHART_SPECS]
        generated: list[ChartArtifact] = []
        for spec in CHART_SPECS:
            try:
                generated.append(methods[spec.chart_id]())
            except Exception:
                LOGGER.exception("Generazione grafico fallita (%s)", spec.chart_id)
                generated.append(self._placeholder(spec, "Grafico temporaneamente non disponibile"))
        return generated
