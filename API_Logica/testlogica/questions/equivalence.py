from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from typing import Any, cast

from ..constants import (
    MAX_BINARY_OPERATORS,
    MAX_EQUIVALENCE_WRONG_OPTIONS,
    MAX_EXPLICIT_EQUIVALENCE_WRONG_OPTIONS,
    MAX_SPOKEN_NESTED_NEGATIONS,
)
from ..metrics import formula_atom_count, formula_binary_operator_count, formula_depth, formula_size
from ..prolog_bridge import PrologBridge, collect_variables, from_prolog, to_prolog
from ..validation import GenerationDeadlineExceeded
from ..validation import make_timeout_provider as _make_timeout_provider


def _generator_module():
    from .. import generator

    return generator


def _delegate(name: str):
    def call(*args, **kwargs):
        return getattr(_generator_module(), name)(*args, **kwargs)

    return call


_default_vars = _delegate("_default_vars")
_diversify_sample = _delegate("_diversify_sample")
_ensure_bridge = _delegate("_ensure_bridge")
_ensure_keys = _delegate("_ensure_keys")
_formula_entry = _delegate("_formula_entry")
_formula_is_spoken_friendly = _delegate("_formula_is_spoken_friendly")
_get_formulas = _delegate("_get_formulas")
_get_orchestrator_module = _delegate("_get_orchestrator_module")
_has_adjacent_duplicate_atoms = _delegate("_has_adjacent_duplicate_atoms")
_req_int_ge = _delegate("_req_int_ge")
_require_pairwise_distinct = _delegate("_require_pairwise_distinct")
_resolve_depth = _delegate("_resolve_depth")
_scramble_formula_prolog = _delegate("_scramble_formula_prolog")
_to_spoken_string = _delegate("_to_spoken_string")


def _pick_modified(
    question_prolog: str,
    variables,
    bridge: PrologBridge,
    filter_equiv_batch: Callable[[Sequence[str]], list[str]],
    target_atom_count: int | None = None,
    seed: int | None = None,
    timeout: int = 10,
    spoken_only: bool = False,
    return_transformation: bool = False,
    timeout_provider: Callable[[int], int] | None = None,
) -> tuple[str, int] | tuple[str, int, dict[str, Any]]:
    """Seleziona una formula equivalente tramite passaggi logici leggibili.

    Preferisce percorsi di almeno due passaggi; quando non sono disponibili,
    il fallback puo restituire una singola legge invece di aggiungere
    trasformazioni artificiali.
    """
    orchestrator_module = _get_orchestrator_module()
    impl = getattr(orchestrator_module, "_pick_modified", None) if orchestrator_module else None
    if callable(impl) and impl is not _pick_modified:
        return cast(
            tuple[str, int] | tuple[str, int, dict[str, Any]],
            impl(
                question_prolog=question_prolog,
                variables=variables,
                bridge=bridge,
                filter_equiv_batch=filter_equiv_batch,
                target_atom_count=target_atom_count,
                seed=seed,
                timeout=timeout,
                timeout_provider=timeout_provider,
                spoken_only=spoken_only,
                return_transformation=return_transformation,
            ),
        )
    raise RuntimeError("orchestrator required: use orchestrator._pick_modified")


def _pick_wrongs(
    question_prolog: str,
    correct_prolog: str,
    variables,
    target_atom_count: int | None,
    wrong_answers_count: int,
    operator_cycles: int | None,
    from_correct_answer: bool,
    bridge: PrologBridge,
    filter_wrong_batch: Callable[[Sequence[str]], list[str]],
    seed: int | None = None,
    timeout: int = 10,
    timeout_provider: Callable[[int], int] | None = None,
    spoken_only: bool = False,
    return_transformations: bool = False,
) -> list[str] | tuple[list[str], dict[str, dict[str, Any]]]:
    """Raccoglie distractor non equivalenti per una formula domanda."""
    orchestrator_module = _get_orchestrator_module()
    impl = getattr(orchestrator_module, "_pick_wrongs", None) if orchestrator_module else None
    if callable(impl) and impl is not _pick_wrongs:
        return cast(
            list[str] | tuple[list[str], dict[str, dict[str, Any]]],
            impl(
                question_prolog=question_prolog,
                correct_prolog=correct_prolog,
                variables=variables,
                target_atom_count=target_atom_count,
                wrong_answers_count=wrong_answers_count,
                operator_cycles=operator_cycles,
                from_correct_answer=from_correct_answer,
                bridge=bridge,
                filter_wrong_batch=filter_wrong_batch,
                seed=seed,
                timeout=timeout,
                timeout_provider=timeout_provider,
                spoken_only=spoken_only,
                return_transformations=return_transformations,
            ),
        )
    raise RuntimeError("orchestrator required: use orchestrator._pick_wrongs")


def _build_exercise(
    expr,
    wrong_answers_count: int = 3,
    operator_cycles: int | None = None,
    wrong_from_correct: bool = False,
    bridge: PrologBridge | None = None,
    seed: int | None = None,
    timeout: int = 10,
    allow_spoken_mode: bool = False,
    *,
    maximum_wrong_answers_count: int,
) -> dict:
    """Costruisce un esercizio con formula originale, modificata e distrazioni."""
    _req_int_ge("wrong_answers_count", wrong_answers_count, 1)
    if wrong_answers_count > maximum_wrong_answers_count:
        raise ValueError(f"wrong_answers_count non può superare {maximum_wrong_answers_count}")
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)
    _req_int_ge("timeout", int(timeout), 1)
    question_input = to_prolog(expr) if not isinstance(expr, str) else expr
    question_expr = from_prolog(question_input)
    question_prolog = to_prolog(question_expr)
    variables = sorted(collect_variables(question_expr))
    question_atom_count = formula_atom_count(question_expr)
    if question_atom_count < 2:
        raise ValueError("expr deve contenere almeno 2 atomi per generare distractor distinti")
    if formula_binary_operator_count(question_expr) > MAX_BINARY_OPERATORS:
        raise ValueError(f"expr non può contenere più di {MAX_BINARY_OPERATORS} operatori binari")
    if _has_adjacent_duplicate_atoms(question_expr):
        raise ValueError("expr non può contenere due atomi uguali come figli dello stesso operatore")
    if _generator_module()._has_excessive_negation_chain(question_expr):
        raise ValueError("expr non può contenere più di due negazioni consecutive")
    if allow_spoken_mode and not _formula_is_spoken_friendly(question_expr):
        raise ValueError("expr produce troppe negazioni annidate nella forma parlata")

    bridge = _ensure_bridge(bridge)
    rng = random.Random(seed)
    remaining_timeout = _make_timeout_provider(timeout)
    total_timeout = max(1, int(timeout))
    check_timeout = max(1, min(total_timeout, 2))
    equiv_cache: dict[str, bool] = {}
    not_equiv_cache: dict[str, bool] = {}

    def filter_equiv_batch(candidates: Sequence[str]) -> list[str]:
        unresolved = [candidate for candidate in candidates if candidate not in equiv_cache]
        if unresolved:
            try:
                equivalent = bridge.filter_equivalent(
                    question_prolog,
                    unresolved,
                    vars_list=variables,
                    timeout=remaining_timeout(check_timeout),
                )
                equivalent_set = set(equivalent)
                for candidate in unresolved:
                    equiv_cache[candidate] = candidate in equivalent_set
            except GenerationDeadlineExceeded:
                raise
            except Exception:
                for candidate in unresolved:
                    try:
                        equiv_cache[candidate] = bridge.equiv(
                            question_prolog,
                            candidate,
                            vars_list=variables,
                            timeout=remaining_timeout(check_timeout),
                        )
                    except GenerationDeadlineExceeded:
                        raise
                    except Exception:
                        equiv_cache[candidate] = False

        return [candidate for candidate in candidates if equiv_cache.get(candidate, False)]

    def filter_wrong_batch(candidates: Sequence[str]) -> list[str]:
        unresolved = [candidate for candidate in candidates if candidate not in not_equiv_cache]
        if unresolved:
            try:
                wrong = bridge.filter_non_equivalent(
                    question_prolog,
                    unresolved,
                    vars_list=variables,
                    timeout=remaining_timeout(check_timeout),
                )
                wrong_set = set(wrong)
                for candidate in unresolved:
                    not_equiv_cache[candidate] = candidate in wrong_set
            except GenerationDeadlineExceeded:
                raise
            except Exception:
                for candidate in unresolved:
                    try:
                        not_equiv_cache[candidate] = bridge.not_equiv(
                            question_prolog,
                            candidate,
                            vars_list=variables,
                            timeout=remaining_timeout(check_timeout),
                        )
                    except GenerationDeadlineExceeded:
                        raise
                    except Exception:
                        not_equiv_cache[candidate] = False

        return [candidate for candidate in candidates if not_equiv_cache.get(candidate, False)]

    modified_result = _pick_modified(
        question_prolog=question_prolog,
        variables=variables,
        bridge=bridge,
        filter_equiv_batch=filter_equiv_batch,
        target_atom_count=question_atom_count,
        seed=seed,
        timeout=remaining_timeout(total_timeout),
        timeout_provider=remaining_timeout,
        spoken_only=allow_spoken_mode,
        return_transformation=True,
    )
    modified_prolog, rewrite_steps, correct_transformation = cast(
        tuple[str, int, dict[str, Any]],
        modified_result,
    )

    if modified_prolog == question_prolog:
        raise RuntimeError("La formula modificata coincide con la formula originale")

    wrong_result = _pick_wrongs(
        question_prolog=question_prolog,
        correct_prolog=modified_prolog,
        variables=variables,
        target_atom_count=question_atom_count,
        wrong_answers_count=wrong_answers_count,
        operator_cycles=operator_cycles,
        from_correct_answer=wrong_from_correct,
        bridge=bridge,
        filter_wrong_batch=filter_wrong_batch,
        seed=seed,
        timeout=remaining_timeout(total_timeout),
        timeout_provider=remaining_timeout,
        spoken_only=allow_spoken_mode,
        return_transformations=True,
    )
    wrong_selected, wrong_transformations = cast(
        tuple[list[str], dict[str, dict[str, Any]]],
        wrong_result,
    )

    _require_pairwise_distinct(
        [question_prolog, modified_prolog, *wrong_selected],
        "build_exercise question/correct/wrongs",
    )

    # L'equivalenza conserva gli endpoint esatti del percorso: nessun ulteriore
    # scrambling deve separare la formula visualizzata dalla transformation.
    original_formula = _formula_entry(question_expr, label="formula originale")
    modified_formula = _formula_entry(
        modified_prolog,
        label="formula modificata",
        steps=rewrite_steps,
        transformation=correct_transformation,
    )
    wrong_entries = [
        _formula_entry(
            formula,
            label=f"formula distrazione n{index}",
            transformation=wrong_transformations[formula],
        )
        for index, formula in enumerate(wrong_selected, start=1)
    ]
    question_prolog_display = original_formula["formula_prolog"]
    correct_answer_display = modified_formula["formula_prolog"]
    wrong_answers_display = [entry["formula_prolog"] for entry in wrong_entries]
    options = [{**modified_formula, "is_correct": True}] + [
        {**entry, "is_correct": False} for entry in wrong_entries
    ]
    rng.shuffle(options)

    exercise: dict[str, Any] = {
        "original_formula": original_formula,
        "modified_formula": modified_formula,
        "variables": variables,
        "depth": formula_depth(question_expr),
        "size": formula_size(question_expr),
        "atom_count": question_atom_count,
        "rewrite_steps": rewrite_steps,
        "source": "prolog_builder",
        "question_prolog": question_prolog_display,
        "correct_answer_prolog": correct_answer_display,
        "wrong_answers_prolog": wrong_answers_display,
        "options": options,
        "spoken_mode": allow_spoken_mode,
    }

    for index, wrong_entry in enumerate(wrong_entries, start=1):
        exercise[f"distraction_{index}"] = wrong_entry

    _ensure_keys(exercise, ["original_formula", "modified_formula", "wrong_answers_prolog"])
    if len(exercise["wrong_answers_prolog"]) < wrong_answers_count:
        raise RuntimeError("Postcondizione fallita: distractor insufficienti")
    return exercise


def build_exercise(
    expr,
    wrong_answers_count: int = 3,
    operator_cycles: int | None = None,
    wrong_from_correct: bool = False,
    bridge: PrologBridge | None = None,
    seed: int | None = None,
    timeout: int = 10,
    allow_spoken_mode: bool = False,
) -> dict:
    """Costruisce un esercizio da una formula esplicita entro il profilo affidabile."""
    return _build_exercise(
        expr=expr,
        wrong_answers_count=wrong_answers_count,
        operator_cycles=operator_cycles,
        wrong_from_correct=wrong_from_correct,
        bridge=bridge,
        seed=seed,
        timeout=timeout,
        allow_spoken_mode=allow_spoken_mode,
        maximum_wrong_answers_count=MAX_EXPLICIT_EQUIVALENCE_WRONG_OPTIONS,
    )


def build_ex_depth(
    depth: int | None = None,
    use_all: bool = False,
    timeout: int = 10,
    seed: int | None = None,
    wrong_answers_count: int = 3,
    operator_cycles: int | None = None,
    wrong_from_correct: bool = False,
    bridge: PrologBridge | None = None,
    allow_spoken_mode: bool = False,
) -> dict:
    """Costruisce un esercizio con 3 atomi e 2 operatori binari, lasciando liberi i not."""
    _req_int_ge("wrong_answers_count", wrong_answers_count, 1)
    if wrong_answers_count > MAX_EQUIVALENCE_WRONG_OPTIONS:
        raise ValueError(f"wrong_answers_count non può superare {MAX_EQUIVALENCE_WRONG_OPTIONS}")
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)
    _req_int_ge("timeout", int(timeout), 1)
    if depth is not None:
        _req_int_ge("depth", depth, 2)
    bridge = _ensure_bridge(bridge)
    rng = random.Random(seed)
    remaining_timeout = _make_timeout_provider(timeout)

    variables = _default_vars(3)

    depth, variables = _resolve_depth(depth, variables)
    formulas = _get_formulas(
        bridge=bridge,
        depth=depth,
        variables=variables,
        use_all=use_all,
        timeout=remaining_timeout(None),
        rng=rng,
        spoken_negation_limit=MAX_SPOKEN_NESTED_NEGATIONS if allow_spoken_mode else None,
    )

    if not formulas:
        raise RuntimeError("Nessuna formula generata che usi tutte le variabili richieste")

    candidates = list(dict.fromkeys(formulas))
    candidates = _diversify_sample(candidates, len(candidates), rng)
    initial_attempts = min(len(candidates), max(8, wrong_answers_count * 4))
    attempt_order = candidates[:initial_attempts] + candidates[initial_attempts:]

    last_error: Exception | None = None
    for formula in attempt_order:
        try:
            return _build_exercise(
                expr=formula,
                bridge=bridge,
                seed=seed,
                wrong_answers_count=wrong_answers_count,
                operator_cycles=operator_cycles,
                wrong_from_correct=wrong_from_correct,
                timeout=remaining_timeout(None),
                allow_spoken_mode=allow_spoken_mode,
                maximum_wrong_answers_count=MAX_EQUIVALENCE_WRONG_OPTIONS,
            )
        except GenerationDeadlineExceeded:
            raise
        except (RuntimeError, ValueError) as exc:
            last_error = exc
            continue

    raise RuntimeError(
        "Impossibile costruire un esercizio completo con la profondita richiesta "
        f"dopo aver provato {len(attempt_order)} candidati"
    ) from last_error


__all__ = ["build_ex_depth", "build_exercise"]
