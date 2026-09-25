"""Pure payload-to-metrics adaptation of the legacy feedback processor."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from unicodedata import normalize

import numpy as np

_CATEGORY_ALIASES = {
    "equivalence": "equivalenza",
    "equivalenza": "equivalenza",
    "hypothesis": "valori di verita",
    "ipotesi": "valori di verita",
    "truth value": "valori di verita",
    "truth value question": "valori di verita",
    "valore di verita": "valori di verita",
    "valori di verita": "valori di verita",
    "consequence": "conseguenza logica",
    "logical consequence": "conseguenza logica",
    "conseguenza logica": "conseguenza logica",
    "translation": "traduzione",
    "traduzione": "traduzione",
    "negation": "negazione",
    "quantified negation": "negazione",
    "negazione": "negazione",
}

_INSTITUTION_ALIASES = {
    "corso di laurea triennale": "corso di laurea triennale",
    "corso di laurea magistrale": "corso di laurea magistrale",
    "ciclo unico": "ciclo unico",
    "laurea a ciclo unico": "ciclo unico",
    "universita": "universita",
    "liceo scientifico": "liceo scientifico",
    "altro liceo": "altro liceo",
    "istituto tecnico industriale": "istituto tecnico industriale",
    "altri istituti tecnici": "altri istituti tecnici",
    "istituto professionale": "istituto professionale",
    "altro": "altro",
}

_STUDY_AREA_ALIASES = {
    "stem": "stem",
    "non stem": "non stem",
    "non-stem": "non stem",
    "altro": "altro",
}

# I tempi restano stringhe inalterate nel payload persistito. Questo limite viene
# applicato soltanto alla vista analitica, cosi valori non finiti o palesemente
# anomali non possono rendere inutilizzabile una pubblicazione Matplotlib.
_MAX_DERIVED_TIME_SECONDS = 24 * 60 * 60


class DataProcessor:
    """Extract chart metrics from already validated in-memory reports.

    Unlike the legacy implementation this class never discovers files relative
    to the process CWD. Missing demographic values remain ``None`` for the
    corresponding session instead of inheriting the preceding user's age.
    """

    def __init__(self, reports: list[dict[str, Any]]) -> None:
        self.all_data = self._chronological(reports)
        self.metrics: dict[str, Any] | None = None

    @staticmethod
    def parse_time(value: Any) -> float:
        def bounded(seconds: float) -> float:
            if not math.isfinite(seconds) or not 0.0 <= seconds <= _MAX_DERIVED_TIME_SECONDS:
                return 0.0
            return seconds

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                return bounded(float(value))
            except OverflowError:
                return 0.0
        if not isinstance(value, str):
            return 0.0
        text = value.strip()
        if not text:
            return 0.0
        if ":" in text:
            parts = text.split(":")
            try:
                if len(parts) == 3:
                    result = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                elif len(parts) == 2:
                    result = int(parts[0]) * 60 + float(parts[1])
                else:
                    return 0.0
                return bounded(result)
            except (TypeError, ValueError, OverflowError):
                return 0.0
        try:
            return bounded(float(text.removesuffix("s").strip()))
        except ValueError:
            return 0.0

    @staticmethod
    def parse_datetime(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        text = value.strip()
        candidates = (text, text.replace("Z", "+00:00"))
        for candidate in candidates:
            try:
                parsed = datetime.fromisoformat(candidate)
                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone(UTC).replace(tzinfo=None)
                return parsed
            except (ValueError, OverflowError, OSError):
                pass
        for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%dT%H:%M:%S"):
            try:
                return datetime.strptime(text, fmt)
            except (ValueError, OverflowError, OSError):
                pass
        return None

    @classmethod
    def _chronological(cls, reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
        indexed = list(enumerate(reports))

        def key(item: tuple[int, dict[str, Any]]) -> tuple[bool, datetime, int]:
            index, report = item
            initial = report.get("Initial Data", {})
            parsed = (
                cls.parse_datetime(initial.get("Tempo inizio esercitazione"))
                if isinstance(initial, dict)
                else None
            )
            return (parsed is None, parsed or datetime.max, index)

        return [report for _, report in sorted(indexed, key=key)]

    @staticmethod
    def _age(value: Any) -> int | None:
        try:
            age = int(value)
        except (TypeError, ValueError):
            return None
        return age if 1 <= age <= 199 else None

    @staticmethod
    def _normalized_text(value: Any, *, maximum: int) -> str:
        text = " ".join(normalize("NFKC", str(value or "")).split())
        return text[:maximum].casefold()

    @classmethod
    def _taxonomy_key(cls, value: Any, *, maximum: int) -> str:
        text = cls._normalized_text(value, maximum=maximum)
        ascii_key = "".join(
            character
            for character in normalize("NFKD", text)
            if not 0x300 <= ord(character) <= 0x36F
        )
        return " ".join(ascii_key.replace("_", " ").split())

    @classmethod
    def normalize_institution(cls, value: Any) -> str:
        """Return a bounded derived institution label without changing the payload."""

        key = cls._taxonomy_key(value, maximum=200)
        if not key:
            return ""
        return _INSTITUTION_ALIASES.get(key, "altro")

    @classmethod
    def normalize_study_area(cls, value: Any) -> str:
        """Return a bounded derived study-area label without changing the payload."""

        key = cls._taxonomy_key(value, maximum=100)
        if not key:
            return ""
        return _STUDY_AREA_ALIASES.get(key, "altro")

    @classmethod
    def normalize_category(cls, value: Any) -> tuple[str, bool]:
        """Map historical/current labels into a bounded derived taxonomy."""

        text = cls._normalized_text(value, maximum=128)
        ascii_key = "".join(
            character
            for character in normalize("NFKD", text)
            if not 0x300 <= ord(character) <= 0x36F
        )
        key = ascii_key.replace("_", " ").replace("-", " ")
        key = " ".join(key.split())
        category = _CATEGORY_ALIASES.get(key)
        return (category, False) if category is not None else ("altro", True)

    def extract_metrics(self) -> dict[str, Any]:
        metrics: dict[str, Any] = {
            "total_questions": [],
            "correct_answers": [],
            "response_times": [],
            "category_accuracy": defaultdict(lambda: {"correct": 0, "total": 0}),
            "category_sessions": defaultdict(set),
            "by_session": [],
            "unknown_question_types": 0,
        }

        for session_index, entry in enumerate(self.all_data):
            initial = entry.get("Initial Data", {})
            questions = entry.get("Domande", [])
            feedback = entry.get("Feedback", {})
            if not isinstance(initial, dict):
                initial = {}
            if not isinstance(questions, list):
                questions = []
            if not isinstance(feedback, dict):
                feedback = {}

            total = int(initial.get("Totale domande", 0) or 0)
            correct = int(initial.get("Totale domande corrette", 0) or 0)
            age = self._age(initial.get("Età"))
            institution = self.normalize_institution(
                initial.get("Istituto di appartenenza", "")
            )
            study_area = self.normalize_study_area(initial.get("Indirizzo", ""))
            started_at = self.parse_datetime(initial.get("Tempo inizio esercitazione"))
            total_time = self.parse_time(initial.get("Tempo totale", ""))
            options = initial.get("Opzioni attive", {})
            if not isinstance(options, dict):
                options = {}

            feedback_values: dict[str, float] = {}
            for name, value in feedback.items():
                try:
                    feedback_values[str(name)] = float(value)
                except (TypeError, ValueError):
                    continue

            responses: list[dict[str, Any]] = []
            session: dict[str, Any] = {
                "session_id": session_index,
                "total_questions": total,
                "correct_answers": correct,
                "accuracy": (correct / total * 100) if total > 0 else 0.0,
                "age": age,
                "institution": institution,
                "study_area": study_area,
                "datetime": started_at,
                "options_state": {str(name): bool(active) for name, active in options.items()},
                "feedback": feedback_values,
                "total_time": total_time,
                "avg_time": total_time / total if total > 0 else 0.0,
                "responses": responses,
            }
            metrics["total_questions"].append(total)
            metrics["correct_answers"].append(correct)

            question_number = 1
            for question_entry in questions:
                if not isinstance(question_entry, dict):
                    continue
                for question in question_entry.values():
                    if not isinstance(question, dict):
                        continue
                    category, is_unknown = self.normalize_category(
                        question.get("Tipologia", "")
                    )
                    if is_unknown:
                        metrics["unknown_question_types"] += 1
                    elapsed = self.parse_time(question.get("Tempo impiegato per rispondere", ""))
                    is_correct = str(question.get("Risposta è corretta", "No")).strip().casefold() in {
                        "sì",
                        "si",
                        "yes",
                        "s",
                        "y",
                    }
                    response = {
                        "question_num": question_number,
                        "tipologia": category,
                        "time": elapsed,
                        "is_correct": is_correct,
                    }
                    responses.append(response)
                    metrics["response_times"].append((question_number, elapsed))
                    metrics["category_accuracy"][category]["total"] += 1
                    metrics["category_sessions"][category].add(session_index)
                    if is_correct:
                        metrics["category_accuracy"][category]["correct"] += 1
                    question_number += 1

            metrics["by_session"].append(session)

        self.metrics = metrics
        return metrics

    def _require_metrics(self) -> dict[str, Any]:
        return self.metrics if self.metrics is not None else self.extract_metrics()

    def get_category_stats(
        self,
        *,
        minimum_sessions: int = 1,
    ) -> dict[str, dict[str, float | int]]:
        metrics = self._require_metrics()
        result: dict[str, dict[str, float | int]] = {}
        for category, values in metrics["category_accuracy"].items():
            if len(metrics["category_sessions"][category]) < minimum_sessions:
                continue
            total = int(values["total"])
            correct = int(values["correct"])
            result[category] = {
                "total": total,
                "correct": correct,
                "wrong": total - correct,
                "accuracy": (correct / total * 100) if total else 0.0,
            }
        return result

    def get_demographic_segments(
        self,
        *,
        minimum_size: int = 1,
    ) -> dict[str, dict[str, list[dict[str, Any]]]]:
        metrics = self._require_metrics()
        segments: dict[str, defaultdict[str, list[dict[str, Any]]]] = {
            "by_age_range": defaultdict(list),
            "by_institution": defaultdict(list),
            "by_study_area": defaultdict(list),
        }
        for session in metrics["by_session"]:
            age = session["age"]
            if age is not None:
                segments["by_age_range"][f"{(age // 10) * 10}-{(age // 10) * 10 + 9}"].append(session)
            if session["institution"]:
                segments["by_institution"][session["institution"]].append(session)
            if session["study_area"]:
                segments["by_study_area"][session["study_area"]].append(session)
        return {
            name: {
                label: sessions
                for label, sessions in groups.items()
                if len(sessions) >= minimum_size
            }
            for name, groups in segments.items()
        }

    def get_feedback_correlation(self, *, minimum_sessions: int = 2) -> dict[str, float]:
        metrics = self._require_metrics()
        keys = sorted({key for session in metrics["by_session"] for key in session["feedback"]})
        result: dict[str, float] = {}
        for key in keys:
            pairs = [
                (session["feedback"][key], session["accuracy"])
                for session in metrics["by_session"]
                if key in session["feedback"]
            ]
            if len(pairs) < minimum_sessions:
                continue
            values = np.asarray([pair[0] for pair in pairs], dtype=float)
            accuracies = np.asarray([pair[1] for pair in pairs], dtype=float)
            if np.std(values) == 0 or np.std(accuracies) == 0:
                continue
            correlation = float(np.corrcoef(values, accuracies)[0, 1])
            if np.isfinite(correlation):
                result[key] = correlation
        return result

    def get_options_performance(self) -> dict[str, dict[str, list[float]]]:
        metrics = self._require_metrics()
        result: defaultdict[str, dict[str, list[float]]] = defaultdict(lambda: {"on": [], "off": []})
        for session in metrics["by_session"]:
            for option, active in session["options_state"].items():
                result[option]["on" if active else "off"].append(session["accuracy"])
        return dict(result)

    def get_summary_stats(self) -> dict[str, Any]:
        metrics = self._require_metrics()
        total_questions = sum(metrics["total_questions"])
        total_correct = sum(metrics["correct_answers"])
        response_times = [elapsed for _, elapsed in metrics["response_times"]]
        return {
            "total_sessions": len(self.all_data),
            "total_questions_answered": total_questions,
            "total_correct_answers": total_correct,
            "overall_accuracy": (total_correct / total_questions * 100) if total_questions else 0.0,
            "avg_response_time": float(np.mean(response_times)) if response_times else 0.0,
            "min_response_time": min(response_times, default=0.0),
            "max_response_time": max(response_times, default=0.0),
            "category_stats": self.get_category_stats(),
        }
