from __future__ import annotations

import random
from typing import Any

import pytest

from testlogica.questions import logical_consequence


class _ControlledBridge:
    def __init__(self, *, failures: int = 0, invalid_result: bool = False) -> None:
        self.failures = failures
        self.invalid_result = invalid_result
        self.calls = 0

    def implies_formula(
        self,
        _question: str,
        candidate: str,
        *,
        vars_list: list[str],
        timeout: int,
    ) -> bool | None:
        del vars_list, timeout
        self.calls += 1
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("errore bridge iniettato")
        if self.invalid_result:
            return None
        return candidate in {"p", "q"}


def _install_controlled_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> list[int]:
    generation_calls: list[int] = []

    def generate_formula(_variables: list[str], _rng: random.Random) -> str:
        generation_calls.append(1)
        return "and(p,q)"

    def select_options(
        *,
        consequence_candidates: list[str],
        non_consequence_candidates: list[str],
        **_kwargs: Any,
    ) -> tuple[list[str], list[str]]:
        assert "p" in consequence_candidates
        assert "not(p)" in non_consequence_candidates
        return ["p"], ["not(p)"]

    monkeypatch.setattr(logical_consequence, "_build_consequence_ready_question_formula", generate_formula)
    monkeypatch.setattr(
        logical_consequence,
        "_collect_candidate_formulas",
        lambda **_kwargs: ["p", "q", "not(p)", "not(q)"],
    )
    monkeypatch.setattr(logical_consequence, "_build_one_operator_candidates", lambda _variables: [])
    monkeypatch.setattr(logical_consequence, "_build_two_operator_candidates", lambda _variables: [])
    monkeypatch.setattr(logical_consequence, "_build_special_logical_consequence_candidates", lambda _variables: [])
    monkeypatch.setattr(logical_consequence, "_select_logical_consequence_options", select_options)
    return generation_calls


def _build(bridge: _ControlledBridge) -> dict[str, Any]:
    return logical_consequence.build_logical_consequence_question(
        variable_count=2,
        correct_options_count=1,
        wrong_options_count=1,
        timeout=3,
        seed=17,
        bridge=bridge,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("variable_count", "correct_count", "wrong_count", "message"),
    [
        (1, 1, 3, "variable_count"),
        (6, 1, 3, "variable_count"),
        (4, 1, 9, "non può superare 8"),
    ],
)
def test_unsupported_capacity_is_rejected_before_bridge_use(
    variable_count: int,
    correct_count: int,
    wrong_count: int,
    message: str,
) -> None:
    bridge = _ControlledBridge()

    with pytest.raises(ValueError, match=message):
        logical_consequence.build_logical_consequence_question(
            variable_count=variable_count,
            correct_options_count=correct_count,
            wrong_options_count=wrong_count,
            timeout=3,
            seed=17,
            bridge=bridge,  # type: ignore[arg-type]
        )

    assert bridge.calls == 0


def test_implies_error_is_propagated_without_retry_or_false_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_calls = _install_controlled_generation(monkeypatch)
    bridge = _ControlledBridge(failures=1)

    with pytest.raises(RuntimeError, match="errore bridge iniettato"):
        _build(bridge)

    assert len(generation_calls) == 1
    assert bridge.calls == 1


def test_construction_error_is_not_hidden_by_formula_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_calls = _install_controlled_generation(monkeypatch)
    monkeypatch.setattr(logical_consequence, "_collect_candidate_formulas", lambda **_kwargs: [])
    bridge = _ControlledBridge()

    with pytest.raises(RuntimeError, match="Non ci sono abbastanza formule"):
        _build(bridge)

    assert len(generation_calls) == 1
    assert bridge.calls == 0


def test_invalid_implies_result_is_not_coerced_to_false(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_controlled_generation(monkeypatch)

    with pytest.raises(RuntimeError, match="Risposta non valida"):
        _build(_ControlledBridge(invalid_result=True))


def test_implies_result_arriving_after_global_deadline_is_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_controlled_generation(monkeypatch)
    now = [0.0]
    monkeypatch.setattr(logical_consequence.time, "monotonic", lambda: now[0])

    class _LateBridge(_ControlledBridge):
        def implies_formula(
            self,
            question: str,
            candidate: str,
            *,
            vars_list: list[str],
            timeout: int,
        ) -> bool:
            del question, candidate, vars_list, timeout
            self.calls += 1
            now[0] = 4.0
            return False

    bridge = _LateBridge()
    with pytest.raises(RuntimeError, match="Tempo esaurito"):
        _build(bridge)

    assert bridge.calls == 1


def test_selector_can_fill_eight_options_with_two_variables() -> None:
    selected = logical_consequence._select_logical_consequence_options(
        rng=random.Random(7),
        consequence_candidates=["p"],
        non_consequence_candidates=[
            "not(not(q))",
            "and(p,q)",
            "or(p,q)",
            "imp(p,q)",
            "imp(q,p)",
            "iff(p,q)",
            "not(p)",
        ],
        correct_count=1,
        wrong_count=7,
    )

    assert selected is not None
    selected_correct, selected_wrong = selected
    assert selected_correct == ["p"]
    assert len(selected_wrong) == 7
    assert "not(not(q))" in selected_wrong
    assert "not(p)" in selected_wrong
