from __future__ import annotations

from typing import Any

import pytest

from testlogica import orchestrator


def _translation_result(seed: int, **_kwargs: Any) -> dict[str, Any]:
    return {
        "type": "translation_question",
        "question_text": f"Domanda generata con seed {seed}",
        "subtype": "propositional",
    }


def _identical_translation_questions(count: int) -> list[dict[str, Any]]:
    return [
        {
            "operation": "build_translation_question",
            "payload": {"wrong_answers_count": 3},
        }
        for _ in range(count)
    ]


def test_batch_seed_assigns_a_distinct_retry_window_to_every_item(monkeypatch: Any) -> None:
    generated_seeds: list[int] = []

    def record_seed(seed: int, **kwargs: Any) -> dict[str, Any]:
        generated_seeds.append(seed)
        return _translation_result(seed, **kwargs)

    monkeypatch.setattr(orchestrator.generator, "build_translation_question", record_seed)

    result = orchestrator.multiple_questions(
        _identical_translation_questions(6),
        seed=100,
        bridge=object(),  # type: ignore[arg-type]
    )

    assert result["success_count"] == 6
    assert result["failed_count"] == 0
    assert generated_seeds == [100, 104, 108, 112, 116, 120]
    assert [item["request"]["seed"] for item in sorted(result["questions"], key=lambda item: item["index"])] == [
        100,
        104,
        108,
        112,
        116,
        120,
    ]


def test_batch_seed_is_deterministic_and_does_not_mutate_input(monkeypatch: Any) -> None:
    monkeypatch.setattr(orchestrator.generator, "build_translation_question", _translation_result)
    questions = _identical_translation_questions(6)
    original_questions = [
        {"operation": item["operation"], "payload": dict(item["payload"])}
        for item in questions
    ]

    first = orchestrator.multiple_questions(questions, seed=73, bridge=object())  # type: ignore[arg-type]
    second = orchestrator.multiple_questions(questions, seed=73, bridge=object())  # type: ignore[arg-type]

    assert first == second
    assert questions == original_questions
    assert all("seed" not in item["payload"] for item in questions)


def test_explicit_item_seed_keeps_the_existing_retry_sequence(monkeypatch: Any) -> None:
    generated_seeds: list[int] = []

    def record_seed(seed: int, **kwargs: Any) -> dict[str, Any]:
        generated_seeds.append(seed)
        return _translation_result(seed, **kwargs)

    monkeypatch.setattr(orchestrator.generator, "build_translation_question", record_seed)
    questions = [
        {"operation": "build_translation_question", "payload": {"wrong_answers_count": 3, "seed": 7}},
        {"operation": "build_translation_question", "payload": {"wrong_answers_count": 3, "seed": 7}},
    ]

    result = orchestrator.multiple_questions(questions, seed=100, bridge=object())  # type: ignore[arg-type]

    assert result["success_count"] == 2
    assert generated_seeds == [7, 7, 8]
    assert sorted(item["request"]["seed"] for item in result["questions"]) == [7, 8]


def test_direct_batch_api_enforces_the_configured_size_limit(monkeypatch: Any) -> None:
    monkeypatch.setattr(orchestrator, "MAX_BATCH_SIZE", 2)

    with pytest.raises(ValueError, match="più di 2"):
        orchestrator.multiple_questions(
            _identical_translation_questions(3),
            bridge=object(),  # type: ignore[arg-type]
        )
