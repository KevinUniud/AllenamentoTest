"""Orchestrator module: thin wrappers that handle bridge/defaults/serialization
and delegate exercise construction to `generator.py`.

This file is a first-step scaffold: it centralizes JSON wrappers and bridge
resolution so we can later move orchestration logic out of `generator.py`.
"""

from __future__ import annotations

import logging
import math
import random
import time
from collections.abc import Callable, Sequence
from typing import Any, cast

from . import generator
from .ast_logic import And, Iff, Imp, Not, Or
from .config import MAX_BATCH_SIZE
from .constants import (
    DEFAULT_DISTRACTOR_MAX_STEPS,
    DISTRACTION_CANDIDATE_MULTIPLIER,
    MAX_MODIFIED_EQUIV_CHECKS,
    MIN_NON_TRIVIAL_CORRECT_STEPS,
)
from .formula_transformation import build_transformation_trace
from .prolog_bridge import PrologBridge, collect_variables, get_default_bridge
from .question_identity import question_id, question_identity_key
from .validation import GenerationDeadlineExceeded


def _ensure_bridge(bridge: PrologBridge | None = None) -> PrologBridge:
    return bridge or get_default_bridge()


# module logger; server should call `config.configure_logging()` on startup
logger = logging.getLogger(__name__)


def generate_formula_json(
    depth: int | None = None,
    variables: list[str] | None = None,
    use_all: bool = False,
    timeout: int = 10,
    seed: int | None = None,
    bridge: PrologBridge | None = None,
    allow_spoken_mode: bool = False,
) -> dict:
    """Wrapper: generate a formula and return JSON-serializable payload."""
    bridge = _ensure_bridge(bridge)
    variables_arg = variables if variables is not None else generator.DEFAULT_VARIABLES
    # Delegate to generator JSON wrapper which supports spoken rendering
    return generator.generate_formula_json(
        depth=depth,
        variables=variables_arg,
        use_all=use_all,
        timeout=timeout,
        seed=seed,
        bridge=bridge,
        allow_spoken_mode=allow_spoken_mode,
    )


def generate_formula_by_variable_count_json(
    variable_count: int,
    use_all: bool = False,
    timeout: int = 10,
    seed: int | None = None,
    bridge: PrologBridge | None = None,
    allow_spoken_mode: bool = False,
) -> dict:
    bridge = _ensure_bridge(bridge)
    return generator.generate_formula_by_variable_count_json(
        variable_count=variable_count,
        use_all=use_all,
        timeout=timeout,
        seed=seed,
        bridge=bridge,
        allow_spoken_mode=allow_spoken_mode,
    )


def build_ex_json(
    expr: Any,
    bridge: PrologBridge | None = None,
    seed: int | None = None,
    wrong_answers_count: int = 3,
    operator_cycles: int | None = None,
    wrong_from_correct: bool = False,
    timeout: int = 10,
    allow_spoken_mode: bool = False,
) -> str:
    bridge = _ensure_bridge(bridge)
    return generator._to_json_string(
        generator.build_exercise(
            expr=expr,
            bridge=bridge,
            seed=seed,
            wrong_answers_count=wrong_answers_count,
            operator_cycles=operator_cycles,
            wrong_from_correct=wrong_from_correct,
            timeout=timeout,
            allow_spoken_mode=allow_spoken_mode,
        )
    )


def build_ex_depth_json(
    depth: int | None = None,
    use_all: bool = False,
    timeout: int = 10,
    seed: int | None = None,
    wrong_answers_count: int = 3,
    operator_cycles: int | None = None,
    wrong_from_correct: bool = False,
    bridge: PrologBridge | None = None,
    allow_spoken_mode: bool = False,
) -> str:
    bridge = _ensure_bridge(bridge)
    return generator._to_json_string(
        generator.build_ex_depth(
            depth=depth,
            use_all=use_all,
            timeout=timeout,
            seed=seed,
            wrong_answers_count=wrong_answers_count,
            operator_cycles=operator_cycles,
            wrong_from_correct=wrong_from_correct,
            bridge=bridge,
            allow_spoken_mode=allow_spoken_mode,
        )
    )


def build_tvq_json(
    predicate_count: int,
    true_options_count: int,
    false_options_count: int,
    timeout: int = 10,
    seed: int | None = None,
    operator_cycles: int | None = None,
    bridge: PrologBridge | None = None,
    allow_spoken_mode: bool = False,
) -> str:
    bridge = _ensure_bridge(bridge)
    return generator._to_json_string(
        generator.build_tvq(
            predicate_count=predicate_count,
            true_options_count=true_options_count,
            false_options_count=false_options_count,
            timeout=timeout,
            seed=seed,
            operator_cycles=operator_cycles,
            bridge=bridge,
            allow_spoken_mode=allow_spoken_mode,
        )
    )


def build_logical_consequence_question_json(
    variable_count: int,
    correct_options_count: int,
    wrong_options_count: int,
    timeout: int = 10,
    seed: int | None = None,
    operator_cycles: int | None = None,
    allow_spoken_mode: bool = False,
    bridge: PrologBridge | None = None,
) -> str:
    bridge = _ensure_bridge(bridge)
    return generator._to_json_string(
        generator.build_logical_consequence_question(
            variable_count=variable_count,
            correct_options_count=correct_options_count,
            wrong_options_count=wrong_options_count,
            timeout=timeout,
            seed=seed,
            operator_cycles=operator_cycles,
            allow_spoken_mode=allow_spoken_mode,
            bridge=bridge,
        )
    )


def _transform_answer_candidates(
    *,
    formula: str,
    bridge: PrologBridge,
    rng: random.Random,
    operator_cycles: int | None,
    timeout_provider: Callable[[], int],
) -> list[str]:
    """Delegate transformation generation to Prolog via bridge with Python fallback.

    This was extracted from `generator` so orchestration of bridge calls
    remains in this module while reusing generator pure helpers.
    """
    transformed: list[str] = []

    answer_cycles_fn = getattr(bridge, "apply_answer_transform_cycles", None)
    if callable(answer_cycles_fn):
        cycles = generator._operator_cycle_count(formula, rng, operator_cycles)
        if cycles > 0:
            transformed = generator._safe_bridge_call(
                cast(Callable[..., object], answer_cycles_fn),
                formula,
                cycles=cycles,
                timeout=timeout_provider(),
            )

    if transformed:
        return list(dict.fromkeys([formula, *transformed]))

    fallback = [formula, generator._maybe_swap_and_or(formula, rng)]
    if operator_cycles == 0:
        return list(dict.fromkeys(fallback))

    apply_cycles = getattr(bridge, "apply_operator_cycles", None)
    if not callable(apply_cycles):
        return list(dict.fromkeys(fallback))

    cycle_fn = cast(Callable[..., list[str]], apply_cycles)
    candidate_cycles = generator._operator_cycle_count(formula, rng, operator_cycles)
    if candidate_cycles <= 0:
        return list(dict.fromkeys(fallback))

    enriched_candidates = generator._safe_bridge_call(
        cast(Callable[..., object], cycle_fn),
        formula,
        cycles=candidate_cycles,
        timeout=timeout_provider(),
    )

    for enriched in enriched_candidates:
        fallback.append(enriched)
        fallback.append(generator._maybe_swap_and_or(enriched, rng))
        if generator._needs_extra_transformation(enriched):
            extra_candidates = generator._safe_bridge_call(
                cast(Callable[..., object], cycle_fn),
                enriched,
                cycles=1,
                timeout=timeout_provider(),
            )
            for extra in extra_candidates:
                fallback.append(extra)
                fallback.append(generator._maybe_swap_and_or(extra, rng))

    return list(dict.fromkeys(fallback))


def _collect_candidate_formulas(
    *,
    bridge: PrologBridge,
    variables: Sequence[str],
    required_options: int,
    rng: random.Random,
    timeout_provider: Callable[[int | None], int],
    operator_cycles: int | None,
    target_atom_count: int | None = None,
    excluded_formulas: Sequence[str] | None = None,
    dedupe_by_commutative_signature: bool = False,
    require_non_empty_vars: bool = False,
    forbid_adjacent_duplicate_atoms: bool = False,
    spoken_only: bool = False,
    max_binary_operators: int = generator.MAX_BINARY_OPERATORS,
) -> list[str]:
    """Collect candidate formulas using bridge calls and generator helpers."""
    candidates: list[str] = []
    seen_candidates: set[str] = set(excluded_formulas or ())
    seen_signatures: set[str] = set()
    if dedupe_by_commutative_signature:
        seen_signatures = {generator._commutative_signature(formula) for formula in seen_candidates}

    allowed_variables = set(variables)

    def register_candidate(formula: str) -> None:
        if not formula or formula in seen_candidates:
            return
        used_variables = collect_variables(generator._as_ast(formula))
        if require_non_empty_vars and not used_variables:
            return
        if not used_variables.issubset(allowed_variables):
            return
        if target_atom_count is not None and not generator._has_atom_count(formula, target_atom_count):
            return
        if generator._has_excessive_negation_chain(formula):
            return
        if forbid_adjacent_duplicate_atoms and generator._has_adjacent_duplicate_atoms(formula):
            return
        if not generator._has_valid_binary_operator_count(generator._as_ast(formula), max_binary_operators):
            return
        if spoken_only and not generator._formula_is_spoken_friendly(formula):
            return

        if dedupe_by_commutative_signature:
            signature = generator._commutative_signature(formula)
            if signature in seen_signatures:
                return
            seen_signatures.add(signature)

        seen_candidates.add(formula)
        candidates.append(formula)

    def register_with_operator_cycles(formula: str) -> None:
        transformed = _transform_answer_candidates(
            formula=formula,
            bridge=bridge,
            rng=rng,
            operator_cycles=operator_cycles,
            timeout_provider=lambda: timeout_provider(2),
        )
        for candidate in transformed:
            register_candidate(candidate)

    for variable in variables:
        register_candidate(variable)
        register_with_operator_cycles(f"not({variable})")

    search_depth = max(2, generator._depth_from_var_count(len(variables)) + 2)
    target_candidate_count = max(required_options * DISTRACTION_CANDIDATE_MULTIPLIER, 12)

    for depth in range(1, search_depth + 1):
        fetched = generator._get_formulas(
            bridge=bridge,
            depth=depth,
            variables=variables,
            use_all=False,
            timeout=timeout_provider(3),
            rng=rng,
            max_binary_operators=max_binary_operators,
            spoken_negation_limit=(
                generator.MAX_SPOKEN_NESTED_NEGATIONS if spoken_only else None
            ),
        )
        for formula in fetched:
            register_candidate(formula)
        if len(candidates) >= target_candidate_count:
            break

    return candidates


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
    """Trova un equivalente privilegiando percorsi naturali di almeno due leggi.

    Se il motore non ne offre uno, una sola riscrittura nominata e leggibile e
    preferibile a passaggi ridondanti introdotti soltanto per raggiungere una
    cardinalita minima.
    """
    rng = random.Random(seed)
    local_deadline = time.monotonic() + max(1, int(timeout))
    rewrite_call_limit = max(1, min(int(timeout), 3))

    def current_timeout() -> int:
        remaining = local_deadline - time.monotonic()
        if remaining <= 0:
            raise GenerationDeadlineExceeded("Tempo esaurito durante la ricerca della formula equivalente")
        allowed = min(rewrite_call_limit, max(1, math.ceil(remaining)))
        if timeout_provider is not None:
            allowed = min(allowed, timeout_provider(allowed))
        return max(1, allowed)

    def candidate_is_eligible(candidate: str, *, require_effective: bool = True) -> bool:
        if not candidate or candidate == question_prolog:
            return False
        if spoken_only and not generator._formula_is_spoken_friendly(candidate):
            return False
        try:
            return (
                not generator._has_adjacent_duplicate_atoms(candidate)
                and not generator._has_excessive_negation_chain(candidate)
                and generator._uses_vars(candidate, variables)
                and generator._has_valid_binary_operator_count(generator._as_ast(candidate))
                and generator._has_atom_count(candidate, target_atom_count)
                and (
                    not require_effective
                    or generator._is_effective_transformation(question_prolog, candidate)
                )
            )
        except (TypeError, ValueError):
            return False

    def finalize_candidate(
        candidate: str,
        path: Sequence[str],
        *,
        minimum_steps: int = MIN_NON_TRIVIAL_CORRECT_STEPS,
        require_effective: bool = True,
    ) -> tuple[str, dict[str, Any]] | None:
        current_timeout()
        selected = candidate
        selected_path = list(path)
        if any(generator._has_excessive_negation_chain(item) for item in selected_path):
            return None
        if spoken_only and any(
            not generator._formula_is_spoken_friendly(item) for item in selected_path
        ):
            return None

        if generator._has_adjacent_duplicate_atoms(selected):
            return None
        if require_effective and not generator._is_effective_transformation(question_prolog, selected):
            return None
        try:
            transformation = build_transformation_trace(
                question_prolog,
                selected_path,
                strategy="equivalence_rewrite",
                preserves_meaning=True,
            )
        except ValueError:
            # Il controllo semantico garantisce l'equivalenza, ma il percorso
            # pedagogico viene esposto solo quando ogni arco corrisponde a una
            # legge logica identificabile e istanziabile.
            return None
        if len(transformation["steps"]) < minimum_steps:
            return None
        current_timeout()
        return selected, transformation

    def select_with_min_non_trivial(
        candidates: Sequence[tuple[str, Sequence[str]]],
        *,
        minimum_steps: int = MIN_NON_TRIVIAL_CORRECT_STEPS,
        require_effective: bool = True,
    ) -> tuple[str, dict[str, Any]] | None:
        shuffled = list(candidates)
        rng.shuffle(shuffled)
        for candidate, path in shuffled:
            selected = finalize_candidate(
                candidate,
                path,
                minimum_steps=minimum_steps,
                require_effective=require_effective,
            )
            if selected is not None:
                return selected
        return None

    rewrite_paths: list[list[str]] = []
    try:
        rewrite_paths_fn = getattr(bridge, "rewrite_paths", None)
        if callable(rewrite_paths_fn):
            raw_paths = rewrite_paths_fn(question_prolog, timeout=current_timeout())
            if isinstance(raw_paths, list):
                rewrite_paths = [list(path) for path in raw_paths if isinstance(path, list)]
        else:
            legacy_path = bridge.rewrite_path(question_prolog, timeout=current_timeout())
            if isinstance(legacy_path, list):
                rewrite_paths = [list(legacy_path)]
        current_timeout()
    except GenerationDeadlineExceeded:
        raise
    except Exception:
        rewrite_paths = []

    seen_multi: set[str] = set()
    seen_single: set[str] = set()
    multi_step_candidates: list[tuple[str, Sequence[str]]] = []
    single_step_candidates: list[tuple[str, Sequence[str]]] = []
    for raw_path in rewrite_paths:
        path = list(raw_path)
        if not path or path[0] != question_prolog:
            path.insert(0, question_prolog)
        for index, candidate in enumerate(path[1:], start=1):
            target = multi_step_candidates if index >= MIN_NON_TRIVIAL_CORRECT_STEPS else single_step_candidates
            seen = seen_multi if index >= MIN_NON_TRIVIAL_CORRECT_STEPS else seen_single
            if candidate in seen or not candidate_is_eligible(candidate, require_effective=False):
                continue
            if any(generator._has_excessive_negation_chain(item) for item in path[: index + 1]):
                continue
            if spoken_only and any(
                not generator._formula_is_spoken_friendly(item) for item in path[: index + 1]
            ):
                continue
            seen.add(candidate)
            target.append((candidate, path[: index + 1]))

    def equivalent_records(
        records: Sequence[tuple[str, Sequence[str]]],
    ) -> list[tuple[str, Sequence[str]]]:
        limited = list(records[:MAX_MODIFIED_EQUIV_CHECKS])
        if not limited:
            return []
        try:
            equivalent_set = set(filter_equiv_batch([candidate for candidate, _path in limited]))
            current_timeout()
            return [(candidate, path) for candidate, path in limited if candidate in equivalent_set]
        except GenerationDeadlineExceeded:
            raise
        except Exception:
            return []

    # I percorsi Prolog di almeno due leggi sono il caso normale e vengono
    # valutati prima dei loro prefissi di un solo passo.
    equivalent_path_candidates = equivalent_records(multi_step_candidates)
    if equivalent_path_candidates:
        selected = select_with_min_non_trivial(equivalent_path_candidates)
        if selected is not None:
            formula, transformation = selected
            rewrite_steps = len(transformation["steps"])
            if return_transformation:
                return formula, rewrite_steps, transformation
            return formula, rewrite_steps

    # Una legge singola ma sostanziale e comunque un risultato primario
    # valido. La sola commutativita viene accettata per ultima (per esempio
    # iff(p,q)), evitando di fabbricare passaggi ridondanti.
    equivalent_single_candidates = equivalent_records(single_step_candidates)
    if equivalent_single_candidates:
        selected = select_with_min_non_trivial(
            equivalent_single_candidates,
            minimum_steps=1,
        )
        if selected is None:
            selected = select_with_min_non_trivial(
                equivalent_single_candidates,
                minimum_steps=1,
                require_effective=False,
            )
        if selected is not None:
            formula, transformation = selected
            rewrite_steps = len(transformation["steps"])
            if return_transformation:
                return formula, rewrite_steps, transformation
            return formula, rewrite_steps

    # Compatibilita di emergenza per bridge precedenti o parzialmente guasti.
    # Con il bridge corrente questo ramo deve restare a zero nei test di carico.
    fallback_raw = generator._safe_bridge_call(
        bridge.rewrite_formula,
        question_prolog,
        timeout=current_timeout(),
    )
    current_timeout()
    fallback_candidates = [
        candidate
        for candidate in fallback_raw
        if candidate not in seen_multi
        and candidate not in seen_single
        and candidate_is_eligible(candidate, require_effective=False)
    ][:MAX_MODIFIED_EQUIV_CHECKS]

    equivalent_fallbacks: list[str] = []
    if fallback_candidates:
        try:
            equivalent_set = set(filter_equiv_batch(fallback_candidates))
            current_timeout()
            equivalent_fallbacks = [candidate for candidate in fallback_candidates if candidate in equivalent_set]
        except GenerationDeadlineExceeded:
            raise
        except Exception:
            equivalent_fallbacks = []

    if equivalent_fallbacks:
        logger.warning("rewrite_paths non ha prodotto un percorso utilizzabile; uso rewrite_formula")
        fallback_records = [(candidate, [question_prolog, candidate]) for candidate in equivalent_fallbacks]
        selected = select_with_min_non_trivial(fallback_records, minimum_steps=1)
        if selected is None:
            selected = select_with_min_non_trivial(
                fallback_records,
                minimum_steps=1,
                require_effective=False,
            )
        if selected is not None:
            formula, transformation = selected
            rewrite_steps = len(transformation["steps"])
            if return_transformation:
                return formula, rewrite_steps, transformation
            return formula, rewrite_steps

    # Se il motore non offre un percorso di almeno due leggi, e preferibile
    # esporre una sola trasformazione reale e leggibile invece di raggiungere
    # artificialmente il minimo applicando due volte la doppia negazione.
    # La riscrittura puo avvenire anche dentro una negazione gia esistente.
    def path_respects_negation_limit(path: Sequence[Any]) -> bool:
        return all(
            not generator._has_excessive_negation_chain(item)
            and (not spoken_only or generator._formula_is_spoken_friendly(item))
            for item in path
        )

    def elementary_rewrite_path(node: Any) -> list[Any] | None:
        if isinstance(node, And):
            rewritten_left = elementary_rewrite_path(node.left)
            if rewritten_left is not None:
                and_left_path: list[Any] = [
                    node,
                    *(And(item, node.right) for item in rewritten_left[1:]),
                ]
                if path_respects_negation_limit(and_left_path):
                    return and_left_path

            rewritten_right = elementary_rewrite_path(node.right)
            if rewritten_right is not None:
                and_right_path: list[Any] = [
                    node,
                    *(And(node.left, item) for item in rewritten_right[1:]),
                ]
                if path_respects_negation_limit(and_right_path):
                    return and_right_path

            commuted_and = And(node.right, node.left)
            de_morgan_and = Not(Or(Not(node.right), Not(node.left)))
            top_level_path = [node, commuted_and, de_morgan_and]
            if path_respects_negation_limit(top_level_path):
                return top_level_path
            return [node, commuted_and]
        if isinstance(node, Or):
            rewritten_left = elementary_rewrite_path(node.left)
            if rewritten_left is not None:
                or_left_path: list[Any] = [
                    node,
                    *(Or(item, node.right) for item in rewritten_left[1:]),
                ]
                if path_respects_negation_limit(or_left_path):
                    return or_left_path

            rewritten_right = elementary_rewrite_path(node.right)
            if rewritten_right is not None:
                or_right_path: list[Any] = [
                    node,
                    *(Or(node.left, item) for item in rewritten_right[1:]),
                ]
                if path_respects_negation_limit(or_right_path):
                    return or_right_path

            commuted_or = Or(node.right, node.left)
            de_morgan_or = Not(And(Not(node.right), Not(node.left)))
            top_level_path = [node, commuted_or, de_morgan_or]
            if path_respects_negation_limit(top_level_path):
                return top_level_path
            return [node, commuted_or]
        if isinstance(node, Iff):
            return [node, Iff(node.right, node.left)]
        if isinstance(node, Imp):
            if isinstance(node.left, Not) and isinstance(node.left.expr, Not):
                simplified = Imp(node.left.expr.expr, node.right)
                eliminated = Or(Not(node.left.expr.expr), node.right)
                return [node, simplified, eliminated]
            return [node, Or(Not(node.left), node.right)]
        if isinstance(node, Not):
            if isinstance(node.expr, Not):
                return [node, node.expr.expr]
            if isinstance(node.expr, And):
                return [node, Or(Not(node.expr.left), Not(node.expr.right))]
            if isinstance(node.expr, Or):
                return [node, And(Not(node.expr.left), Not(node.expr.right))]
            rewritten_operand_path = elementary_rewrite_path(node.expr)
            if rewritten_operand_path is not None:
                return [node, *(Not(item) for item in rewritten_operand_path[1:])]
        return None

    fallback_ast_path = elementary_rewrite_path(generator._as_ast(question_prolog))
    fallback_path = (
        [generator._as_prolog(item) for item in fallback_ast_path]
        if fallback_ast_path is not None
        else []
    )
    fallback_formula = fallback_path[-1] if fallback_path else ""
    if (
        fallback_formula
        and all(not generator._has_excessive_negation_chain(item) for item in fallback_path)
        and (
            not spoken_only
            or all(generator._formula_is_spoken_friendly(item) for item in fallback_path)
        )
        and candidate_is_eligible(fallback_formula, require_effective=False)
    ):
        try:
            fallback_transformation: dict[str, Any] | None = build_transformation_trace(
                question_prolog,
                fallback_path,
                strategy="equivalence_rewrite",
                preserves_meaning=True,
            )
        except ValueError:
            fallback_transformation = None
        if fallback_transformation is not None:
            logger.warning("motore di riscrittura non disponibile; uso il percorso equivalente Python")
            rewrite_steps = len(fallback_transformation["steps"])
            if return_transformation:
                return fallback_formula, rewrite_steps, fallback_transformation
            return fallback_formula, rewrite_steps

    raise RuntimeError("Nessuna formula modificata equivalente trovata")


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
    rng = random.Random(seed)
    collected: list[str] = []
    transformations: dict[str, dict[str, Any]] = {}
    seen = {question_prolog, correct_prolog}
    source_formula = correct_prolog if from_correct_answer else question_prolog
    distract_timeout = max(1, min(timeout, 3))
    candidate_limit = max(wrong_answers_count * DISTRACTION_CANDIDATE_MULTIPLIER, 4)

    def current_timeout() -> int:
        if timeout_provider is None:
            return distract_timeout
        return max(1, min(distract_timeout, timeout_provider(distract_timeout)))

    def candidate_is_eligible(candidate: str) -> bool:
        if not candidate or candidate in seen:
            return False
        if spoken_only and not generator._formula_is_spoken_friendly(candidate):
            return False
        try:
            return (
                not generator._has_adjacent_duplicate_atoms(candidate)
                and not generator._has_excessive_negation_chain(candidate)
                and generator._uses_vars(candidate, variables)
                and generator._has_valid_binary_operator_count(generator._as_ast(candidate))
                and generator._has_atom_count(candidate, target_atom_count)
            )
        except (TypeError, ValueError):
            return False

    def add_records(records: Sequence[tuple[str, Sequence[str]]]) -> bool:
        eligible = [
            (candidate, path)
            for candidate, path in records
            if candidate_is_eligible(candidate)
            and all(not generator._has_excessive_negation_chain(item) for item in path)
            and (
                not spoken_only
                or all(generator._formula_is_spoken_friendly(item) for item in path)
            )
        ]
        if not eligible:
            return False
        rng.shuffle(eligible)
        wrong_set = set(filter_wrong_batch([candidate for candidate, _path in eligible]))
        for candidate, path in eligible:
            seen.add(candidate)
            if candidate not in wrong_set:
                continue
            transformation = build_transformation_trace(
                source_formula,
                path,
                strategy="distractor_mutation",
                preserves_meaning=False,
            )
            collected.append(candidate)
            transformations[candidate] = transformation
            if len(collected) >= wrong_answers_count:
                return True
        return False

    def direct_records(candidates: Sequence[str]) -> list[tuple[str, Sequence[str]]]:
        return [(candidate, [source_formula, candidate]) for candidate in dict.fromkeys(candidates or [])]

    def expanded_records(candidates: Sequence[str]) -> list[tuple[str, Sequence[str]]]:
        records: list[tuple[str, Sequence[str]]] = []
        for candidate in dict.fromkeys(candidates or []):
            if not candidate:
                continue
            expanded = _transform_answer_candidates(
                formula=candidate,
                bridge=bridge,
                rng=rng,
                operator_cycles=operator_cycles,
                timeout_provider=current_timeout,
            )
            for result in expanded:
                path = [source_formula, candidate] if result == candidate else [source_formula, candidate, result]
                records.append((result, path))
        return records

    def finish():
        rng.shuffle(collected)
        selected = collected[:wrong_answers_count]
        if return_transformations:
            return selected, {candidate: transformations[candidate] for candidate in selected}
        return selected

    one_step_sources: list[Callable[[], list[str]]] = []

    some_one_step = getattr(bridge, "some_step_neq", None)
    if callable(some_one_step):
        one_step_sources.append(
            lambda: generator._safe_bridge_call(
                cast(Callable[..., object], some_one_step),
                source_formula,
                limit=candidate_limit,
                timeout=current_timeout(),
            )
        )
    else:
        one_step_sources.append(
            lambda: generator._safe_bridge_call(
                bridge.all_step_neq,
                source_formula,
                timeout=current_timeout(),
            )
        )

    one_step_sources.append(
        lambda: generator._safe_bridge_call(
            bridge.one_step_neq,
            source_formula,
            timeout=current_timeout(),
        )
    )

    one_step_candidates: list[str] = []
    for source in one_step_sources:
        candidates = source()
        one_step_candidates.extend(candidates)
        if add_records(direct_records(candidates)):
            return finish()

    deterministic_sources: list[Callable[[], list[str]]] = []
    if one_step_candidates:
        deterministic_sources.append(lambda: one_step_candidates)

    some_multi_step = getattr(bridge, "some_neq", None)
    if callable(some_multi_step):
        deterministic_sources.append(
            lambda: generator._safe_bridge_call(
                cast(Callable[..., object], some_multi_step),
                source_formula,
                max_steps=DEFAULT_DISTRACTOR_MAX_STEPS,
                limit=candidate_limit,
                timeout=current_timeout(),
            )
        )

    deterministic_sources.append(
        lambda: generator._safe_bridge_call(
            bridge.non_equivalent_distraction,
            source_formula,
            max_steps=DEFAULT_DISTRACTOR_MAX_STEPS,
            timeout=current_timeout(),
        )
    )

    for source in deterministic_sources:
        if add_records(expanded_records(source())):
            return finish()

    if len(collected) >= wrong_answers_count:
        return finish()

    raise RuntimeError(
        f"Non ci sono abbastanza distractor errati: richiesti {wrong_answers_count}, trovati {len(collected)}"
    )


def multiple_questions(
    questions: Sequence[dict[str, Any]],
    seed: int | None = None,
    bridge: PrologBridge | None = None,
) -> dict[str, Any]:
    """Batch orchestration for multiple question generation.

    This delegates to functions in `generator` and handles retries, deduplication
    and envelope formatting. Kept here so `generator` only contains exercise
    building logic.
    """
    if not questions:
        raise ValueError("questions non può essere vuoto")
    if len(questions) > MAX_BATCH_SIZE:
        raise ValueError(f"questions non può contenere più di {MAX_BATCH_SIZE} elementi")

    bridge = _ensure_bridge(bridge)
    rng = random.Random(seed)
    logger.info("multiple_questions start: count=%d seed=%s", len(questions), seed)

    operation_aliases = {
        "build_exercise_from_depth": "build_ex_depth",
        "build_truth_value_options_question": "build_tvq",
    }

    supported_operations = {
        "build_exercise",
        "build_ex_depth",
        "build_tvq",
        "build_logical_consequence_question",
        "build_translation_question",
    }
    max_attempts = 4
    used_question_keys: set[str] = set()

    envelopes: list[dict[str, Any]] = []
    for index, item in enumerate(questions):
        envelope: dict[str, Any] = {"index": index}
        attempts = 0
        try:
            if not isinstance(item, dict):
                raise ValueError("Ogni elemento di questions deve essere un oggetto")

            operation = item.get("operation")
            if not isinstance(operation, str) or not operation:
                raise ValueError("Ogni elemento di questions deve contenere una stringa operation")

            normalized_operation = operation_aliases.get(operation, operation)
            if normalized_operation not in supported_operations:
                raise ValueError(
                    f"Operazione non supportata in multiple_questions: {operation}. "
                    f"Operazioni supportate: {sorted(supported_operations | set(operation_aliases))}"
                )

            payload = item.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("Ogni elemento di questions deve contenere un payload oggetto")

            normalized_payload = dict(payload)
            normalized_payload.pop("bridge", None)
            seed_injected_from_batch = seed is not None and "seed" not in normalized_payload
            if seed_injected_from_batch:
                normalized_payload["seed"] = seed

            last_error: Exception | None = None
            used_payload: dict[str, Any] = dict(normalized_payload)
            result: Any = None
            question_key: str | None = None

            for attempt in range(1, max_attempts + 1):
                attempts = attempt
                attempt_payload = dict(normalized_payload)
                if isinstance(attempt_payload.get("seed"), int):
                    seed_offset = attempt - 1
                    if seed_injected_from_batch:
                        seed_offset += index * max_attempts
                    attempt_payload["seed"] = int(attempt_payload["seed"]) + seed_offset
                else:
                    attempt_payload["seed"] = rng.randint(0, 2**31 - 1)
                    attempt_payload["seed"] += index * max_attempts + (attempt - 1)

                try:
                    if normalized_operation == "build_exercise":
                        result = generator.build_exercise(bridge=bridge, **attempt_payload)
                    elif normalized_operation == "build_ex_depth":
                        result = generator.build_ex_depth(bridge=bridge, **attempt_payload)
                    elif normalized_operation == "build_tvq":
                        result = generator.build_tvq(bridge=bridge, **attempt_payload)
                    elif normalized_operation == "build_logical_consequence_question":
                        result = generator.build_logical_consequence_question(bridge=bridge, **attempt_payload)
                    else:
                        result = generator.build_translation_question(**attempt_payload)

                    question_key = question_identity_key(normalized_operation, result)
                    if question_key in used_question_keys:
                        last_error = RuntimeError("Domanda duplicata nel batch")
                        continue

                    used_payload = attempt_payload
                    used_question_keys.add(question_key)
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    logger.exception("attempt %d failed for operation %s: %s", attempt, normalized_operation, exc)
                    continue

            if last_error is not None:
                raise last_error

            if isinstance(result, dict):
                result = {**result, "question_id": question_id(normalized_operation, result)}

            envelope.update(
                {
                    "operation": normalized_operation,
                    "request": used_payload,
                    "status": "ok",
                    "attempts": attempts,
                    "result": result,
                }
            )
        except Exception as exc:
            logger.warning(
                "question generation failed: operation=%s index=%d error=%s",
                item.get("operation") if isinstance(item, dict) else None,
                index,
                exc,
            )
            envelope.update(
                {
                    "operation": item.get("operation") if isinstance(item, dict) else None,
                    "request": item.get("payload") if isinstance(item, dict) else None,
                    "status": "failed",
                    "attempts": attempts if attempts > 0 else 1,
                    "error": str(exc),
                    "result": None,
                }
            )

        envelopes.append(envelope)

    rng.shuffle(envelopes)
    success_count = sum(1 for envelope in envelopes if envelope.get("status") == "ok")
    failed_count = len(envelopes) - success_count
    batch = {
        "type": "multiple_questions",
        "seed": seed,
        "count": len(envelopes),
        "success_count": success_count,
        "failed_count": failed_count,
        "questions": envelopes,
    }
    # Ensure generator-level invariant checking is used
    generator._ensure_keys(batch, ["type", "count", "success_count", "failed_count", "questions"])
    # Register orchestrator implementations so generator can call them internally
    generator._transform_answer_candidates = _transform_answer_candidates
    generator._collect_candidate_formulas = _collect_candidate_formulas
    generator._pick_modified = _pick_modified
    generator._pick_wrongs = _pick_wrongs
    return batch


# Install the orchestrator helpers on import so the public generator entry points
# can work without requiring an extra bootstrap call.
generator._transform_answer_candidates = _transform_answer_candidates
generator._collect_candidate_formulas = _collect_candidate_formulas
generator._pick_modified = _pick_modified
generator._pick_wrongs = _pick_wrongs
