from __future__ import annotations

import random
from collections.abc import Callable, Sequence

from ..prolog_bridge import PrologBridge
from ..validation import make_timeout_provider as _make_timeout_provider


def _generator_module():
    from .. import generator

    return generator


def _delegate(name: str):
    def call(*args, **kwargs):
        return getattr(_generator_module(), name)(*args, **kwargs)

    return call


_collect_candidate_formulas = _delegate("_collect_candidate_formulas")
_default_vars = _delegate("_default_vars")
_ensure_bridge = _delegate("_ensure_bridge")
_ensure_keys = _delegate("_ensure_keys")
_formula_entry = _delegate("_formula_entry")
_has_operator_diversity = _delegate("_has_operator_diversity")
_req_int_ge = _delegate("_req_int_ge")
_require_pairwise_distinct = _delegate("_require_pairwise_distinct")
_select_formulas_with_repetition_policy = _delegate("_select_formulas_with_repetition_policy")


def _sample_partitioned_options(
    *,
    rng: random.Random,
    left_candidates: Sequence[str],
    right_candidates: Sequence[str],
    left_count: int,
    right_count: int,
    max_attempts: int = 12,
    uniqueness_key: Callable[[str], str] | None = None,
    extra_validator: Callable[[Sequence[str], Sequence[str]], bool] | None = None,
) -> tuple[list[str], list[str]] | None:
    """Campiona due partizioni di opzioni rispettando i vincoli comuni di diversita."""
    for _ in range(max_attempts):
        try:
            trial_left = _select_formulas_with_repetition_policy(
                left_candidates,
                count=left_count,
                rng=rng,
            )
            trial_right = _select_formulas_with_repetition_policy(
                right_candidates,
                count=right_count,
                rng=rng,
            )
        except RuntimeError:
            # Non aggirare la policy di ripetizione con un campionamento
            # generico: il chiamante puo provare una diversa valutazione.
            return None
        trial_options = trial_left + trial_right

        if len(set(trial_options)) != len(trial_options):
            continue
        if uniqueness_key is not None and len({uniqueness_key(option) for option in trial_options}) != len(
            trial_options
        ):
            continue
        if not _has_operator_diversity(trial_options):
            continue
        if extra_validator is not None and not extra_validator(trial_left, trial_right):
            continue
        return trial_left, trial_right

    return None


def build_tvq(
    predicate_count: int,
    true_options_count: int,
    false_options_count: int,
    timeout: int = 10,
    seed: int | None = None,
    operator_cycles: int | None = None,
    bridge: PrologBridge | None = None,
    allow_spoken_mode: bool = False,
) -> dict:
    """Costruisce una domanda vero/falso da informazioni sui predicati."""
    _req_int_ge("predicate_count", predicate_count, 1)
    _req_int_ge("timeout", int(timeout), 1)
    if true_options_count < 1:
        raise ValueError("true_options_count deve essere >= 1")
    if false_options_count < 1:
        raise ValueError("false_options_count deve essere >= 1")
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)

    bridge = _ensure_bridge(bridge)
    rng = random.Random(seed)
    remaining_timeout = _make_timeout_provider(timeout)

    # La cardinalita richiesta rappresenta la difficolta scelta dal client e non
    # deve cambiare casualmente tra quattro e cinque predicati.
    variables = _default_vars(predicate_count)

    effective_predicate_count = len(variables)
    required_options = true_options_count + false_options_count

    valuations = bridge.assignment(variables, timeout=remaining_timeout(None))
    if not valuations:
        raise RuntimeError("Nessuna assegnazione disponibile per i predicati richiesti")
    rng.shuffle(valuations)

    target_atom_count = effective_predicate_count
    candidates = _collect_candidate_formulas(
        bridge=bridge,
        variables=variables,
        required_options=required_options,
        rng=rng,
        timeout_provider=remaining_timeout,
        operator_cycles=operator_cycles,
        target_atom_count=target_atom_count,
        require_non_empty_vars=True,
        forbid_adjacent_duplicate_atoms=True,
        spoken_only=allow_spoken_mode,
        # Un albero binario con N foglie richiede almeno N - 1 connettivi.
        # Il limite globale (2) e adatto ai quiz brevi ma renderebbe vuoto per
        # costruzione il pool delle difficolta media e alta (4/5 atomi).
        max_binary_operators=max(2, target_atom_count - 1),
    )

    if len(candidates) < required_options:
        raise RuntimeError("Non ci sono abbastanza formule candidate con il numero di atomi richiesto")

    for valuation in valuations:
        true_candidates: list[str] = []
        false_candidates: list[str] = []

        shuffled_candidates = list(candidates)
        rng.shuffle(shuffled_candidates)

        for candidate in shuffled_candidates:
            result = bridge.eval(candidate, valuation, timeout=remaining_timeout(2))
            if result:
                true_candidates.append(candidate)
            else:
                false_candidates.append(candidate)

            if len(true_candidates) >= true_options_count and len(false_candidates) >= false_options_count:
                break

        if len(true_candidates) < true_options_count or len(false_candidates) < false_options_count:
            continue

        combined_candidates = true_candidates + false_candidates
        if not _has_operator_diversity(combined_candidates):
            continue

        selected = _sample_partitioned_options(
            rng=rng,
            left_candidates=true_candidates,
            right_candidates=false_candidates,
            left_count=true_options_count,
            right_count=false_options_count,
        )

        if selected is None:
            continue

        selected_true, selected_false = selected

        _require_pairwise_distinct(selected_true + selected_false, "build_tvq options")

        true_entries = [_formula_entry(formula, rng=rng, is_true=True) for formula in selected_true]
        false_entries = [_formula_entry(formula, rng=rng, is_true=False) for formula in selected_false]
        options = true_entries + false_entries
        rng.shuffle(options)

        result = {
            "type": "truth_value_options_question",
            "predicate_count": effective_predicate_count,
            "true_options_count": true_options_count,
            "false_options_count": false_options_count,
            "variables": variables,
            "information": list(valuation),
            "options": options,
            "true_options": true_entries,
            "false_options": false_entries,
            "source": "prolog_assignment_and_eval",
            "spoken_mode": allow_spoken_mode,
        }

        _ensure_keys(result, ["information", "options", "variables"])
        return result

    raise RuntimeError("Impossibile trovare una assegnazione con abbastanza opzioni vere e false distinte")


__all__ = ["build_tvq"]
