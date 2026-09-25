from __future__ import annotations

import random
import time
from collections.abc import Callable, Sequence
from typing import Any

from ..ast_logic import And, Iff, Imp, Not, Or, Var
from ..constants import (
    MAX_LOGICAL_CONSEQUENCE_OPTIONS,
    MAX_LOGICAL_CONSEQUENCE_VARIABLES,
    MIN_LOGICAL_CONSEQUENCE_VARIABLES,
)
from ..metrics import formula_operator_count
from ..prolog_bridge import PrologBridge, collect_variables
from ..validation import GenerationDeadlineExceeded
from ..validation import make_timeout_provider as _make_timeout_provider


def _generator_module():
    from .. import generator

    return generator


def _delegate(name: str):
    def call(*args, **kwargs):
        return getattr(_generator_module(), name)(*args, **kwargs)

    return call


_as_ast = _delegate("_as_ast")
_as_prolog = _delegate("_as_prolog")
_collect_candidate_formulas = _delegate("_collect_candidate_formulas")
_commutative_signature = _delegate("_commutative_signature")
_default_vars = _delegate("_default_vars")
_ensure_bridge = _delegate("_ensure_bridge")
_ensure_keys = _delegate("_ensure_keys")
_formula_entry = _delegate("_formula_entry")
_formula_is_spoken_friendly = _delegate("_formula_is_spoken_friendly")
_has_adjacent_duplicate_atoms = _delegate("_has_adjacent_duplicate_atoms")
_req_int_ge = _delegate("_req_int_ge")
_scramble_formula_prolog = _delegate("_scramble_formula_prolog")
_select_formulas_with_repetition_policy = _delegate("_select_formulas_with_repetition_policy")
_to_spoken_string = _delegate("_to_spoken_string")
class _LogicalConsequenceConstructionError(RuntimeError):
    """Segnala che i vincoli del quiz non possono essere soddisfatti."""


def _formula_contains_not(expr: Any) -> bool:
    """Verifica se la formula contiene almeno un operatore not."""
    ast = _as_ast(expr)

    def walk(node: Any) -> bool:
        if isinstance(node, Var):
            return False
        if isinstance(node, Not):
            return True
        if isinstance(node, (And, Or, Imp, Iff)):
            return walk(node.left) or walk(node.right)
        raise TypeError(f"Tipo formula non supportato: {type(node)!r}")

    return walk(ast)


def _logical_consequence_operator_bucket(formula: str) -> int | None:
    """Restituisce il bucket operatori valido (1/2) per le opzioni di conseguenza logica."""
    ast = _as_ast(formula)
    operator_count = formula_operator_count(ast)
    if operator_count not in (1, 2):
        return None
    # Vincolo richiesto: se compare not, serve almeno un altro operatore.
    if operator_count == 1 and _formula_contains_not(ast):
        return None
    return operator_count


def _logical_consequence_special_bucket(formula: str) -> int | None:
    """Restituisce il bucket speciale per atomi o atomi negati semplici."""
    ast = _as_ast(formula)
    if isinstance(ast, Var):
        return 0
    if isinstance(ast, Not) and isinstance(ast.expr, Var):
        return 1
    return None


def _logical_consequence_variable_bucket(formula: str) -> int | None:
    """Restituisce il bucket di cardinalita delle variabili per le opzioni di conseguenza logica."""
    variable_count = len(collect_variables(_as_ast(formula)))
    if variable_count in (2, 3):
        return variable_count
    return None


def _select_logical_consequence_options(
    *,
    rng: random.Random,
    consequence_candidates: Sequence[str],
    non_consequence_candidates: Sequence[str],
    correct_count: int,
    wrong_count: int,
) -> tuple[list[str], list[str]] | None:
    """Seleziona opzioni garantendo almeno una risposta a 2 operatori e, quando possibile, una speciale."""
    special_correct_candidates = [
        candidate
        for candidate in dict.fromkeys(consequence_candidates)
        if _logical_consequence_special_bucket(candidate) is not None
    ]
    special_wrong_candidates = [
        candidate
        for candidate in dict.fromkeys(non_consequence_candidates)
        if _logical_consequence_special_bucket(candidate) is not None
    ]
    two_correct_candidates = [
        candidate
        for candidate in dict.fromkeys(consequence_candidates)
        if _logical_consequence_operator_bucket(candidate) == 2
    ]
    two_wrong_candidates = [
        candidate
        for candidate in dict.fromkeys(non_consequence_candidates)
        if _logical_consequence_operator_bucket(candidate) == 2
    ]
    all_correct_candidates = list(dict.fromkeys(consequence_candidates))
    all_wrong_candidates = list(dict.fromkeys(non_consequence_candidates))

    special_candidates: list[tuple[str, bool]] = [(candidate, True) for candidate in special_correct_candidates]
    special_candidates.extend((candidate, False) for candidate in special_wrong_candidates)
    two_candidates: list[tuple[str, bool]] = [(candidate, True) for candidate in two_correct_candidates]
    two_candidates.extend((candidate, False) for candidate in two_wrong_candidates)

    # Prima prova combinazioni con una risposta speciale atomica/negata e una risposta a 2 operatori.
    candidate_pairs: list[tuple[tuple[str, bool] | None, tuple[str, bool]]] = []
    candidate_pairs.extend((special, two) for special in special_candidates for two in two_candidates)
    # Se non basta, prova comunque a garantire almeno una risposta a 2 operatori.
    candidate_pairs.extend((None, two) for two in two_candidates)

    for special_choice, two_choice in candidate_pairs:
        selected_correct: list[str] = []
        selected_wrong: list[str] = []
        used: set[str] = set()

        if special_choice is not None:
            special_candidate, is_special_correct = special_choice
            if is_special_correct:
                selected_correct.append(special_candidate)
            else:
                selected_wrong.append(special_candidate)
            used.add(special_candidate)

        two_candidate, is_two_correct = two_choice
        if two_candidate in used:
            continue
        if is_two_correct:
            selected_correct.append(two_candidate)
        else:
            selected_wrong.append(two_candidate)
        used.add(two_candidate)

        remaining_correct = correct_count - len(selected_correct)
        remaining_wrong = wrong_count - len(selected_wrong)
        if remaining_correct < 0 or remaining_wrong < 0:
            continue

        # Gli elementi gia scelti garantiscono il vincolo didattico (almeno
        # una formula a due operatori e, quando disponibile, una formula
        # atomica/negata). Le posizioni residue possono appartenere a
        # qualunque bucket valido: limitarle alle sole formule a un operatore
        # rendeva matematicamente impossibili i batch da otto opzioni con due
        # variabili, pur in presenza di candidati sufficienti.
        remaining_correct_pool = [candidate for candidate in all_correct_candidates if candidate not in used]
        remaining_wrong_pool = [candidate for candidate in all_wrong_candidates if candidate not in used]

        if len(remaining_correct_pool) < remaining_correct or len(remaining_wrong_pool) < remaining_wrong:
            continue

        selected_correct.extend(rng.sample(remaining_correct_pool, remaining_correct))
        selected_wrong.extend(rng.sample(remaining_wrong_pool, remaining_wrong))

        trial_options = selected_correct + selected_wrong
        if len(set(trial_options)) != len(trial_options):
            continue
        if len({_commutative_signature(option) for option in trial_options}) != len(trial_options):
            continue

        return selected_correct, selected_wrong

    return None


def _select_logical_consequence_variable_mix(
    *,
    rng: random.Random,
    consequence_candidates: Sequence[str],
    non_consequence_candidates: Sequence[str],
    correct_count: int,
    wrong_count: int,
) -> tuple[list[str], list[str]] | None:
    """Seleziona 4 opzioni bilanciando 2 formule a 2 variabili e 2 a 3 variabili."""
    if correct_count + wrong_count != 4:
        return None

    two_correct_candidates = [
        candidate
        for candidate in dict.fromkeys(consequence_candidates)
        if _logical_consequence_variable_bucket(candidate) == 2
    ]
    two_wrong_candidates = [
        candidate
        for candidate in dict.fromkeys(non_consequence_candidates)
        if _logical_consequence_variable_bucket(candidate) == 2
    ]
    three_correct_candidates = [
        candidate
        for candidate in dict.fromkeys(consequence_candidates)
        if _logical_consequence_variable_bucket(candidate) == 3
    ]
    three_wrong_candidates = [
        candidate
        for candidate in dict.fromkeys(non_consequence_candidates)
        if _logical_consequence_variable_bucket(candidate) == 3
    ]

    if len(two_correct_candidates) + len(two_wrong_candidates) < 2:
        return None
    if len(three_correct_candidates) + len(three_wrong_candidates) < 2:
        return None

    def pick_bucket(candidates: Sequence[str], count: int) -> list[str]:
        if count == 0:
            return []
        return _select_formulas_with_repetition_policy(candidates, count, rng)

    for correct_two_count in range(max(0, correct_count - 2), min(2, correct_count) + 1):
        wrong_two_count = 2 - correct_two_count
        correct_three_count = correct_count - correct_two_count
        wrong_three_count = wrong_count - wrong_two_count

        if correct_three_count < 0 or wrong_three_count < 0:
            continue
        if correct_three_count > 2 or wrong_three_count > 2:
            continue

        try:
            selected_two_correct = pick_bucket(two_correct_candidates, correct_two_count)
            selected_two_wrong = pick_bucket(two_wrong_candidates, wrong_two_count)
            selected_three_correct = pick_bucket(three_correct_candidates, correct_three_count)
            selected_three_wrong = pick_bucket(three_wrong_candidates, wrong_three_count)
        except RuntimeError:
            continue

        selected_correct = selected_two_correct + selected_three_correct
        selected_wrong = selected_two_wrong + selected_three_wrong
        trial_options = selected_correct + selected_wrong

        if len(set(trial_options)) != len(trial_options):
            continue
        if len({_commutative_signature(option) for option in trial_options}) != len(trial_options):
            continue

        return selected_correct, selected_wrong

    return None


def _build_one_operator_candidates(variables: Sequence[str]) -> list[str]:
    """Genera formule candidate a 1 operatore a partire da coppie di variabili."""
    candidates: list[str] = []
    for left in variables:
        for right in variables:
            if left == right:
                continue
            candidates.append(f"and({left},{right})")
            candidates.append(f"or({left},{right})")
            candidates.append(f"imp({left},{right})")
            candidates.append(f"iff({left},{right})")
    return list(dict.fromkeys(candidates))


def _build_two_operator_candidates(variables: Sequence[str]) -> list[str]:
    """Genera formule candidate con esattamente due operatori."""
    candidates: list[str] = []
    for left in variables:
        candidates.append(f"not(not({left}))")
        # Una tautologia e una contraddizione per variabile garantiscono che
        # entrambi i gruppi semantici restino popolati anche negli split da
        # otto opzioni, senza ricorrere a una nuova formula-domanda.
        candidates.append(f"or({left},not({left}))")
        candidates.append(f"and({left},not({left}))")
        for middle in variables:
            for right in variables:
                if left in (middle, right) or middle == right:
                    continue
                candidates.extend(
                    [
                        f"and({left},or({middle},{right}))",
                        f"or({left},and({middle},{right}))",
                        f"imp({left},and({middle},{right}))",
                        f"iff({left},or({middle},{right}))",
                    ]
                )
    return list(dict.fromkeys(candidates))


def _build_special_logical_consequence_candidates(variables: Sequence[str]) -> list[str]:
    """Genera candidati speciali atomici o negati a partire dalle variabili disponibili."""
    candidates: list[str] = []
    for variable in variables:
        candidates.append(variable)
        candidates.append(f"not({variable})")
    return list(dict.fromkeys(candidates))


def _build_consequence_ready_question_formula(
    variables: Sequence[str],
    rng: random.Random,
) -> str:
    """Costruisce una congiunzione di letterali con un unico modello.

    La polarita e sempre mista: il pool breve contiene quindi, per
    costruzione, formule vere e false nel modello della domanda. Ordine,
    polarita e forma dell'albero dipendono dal seed e mantengono la varieta
    delle domande senza affidarsi a tentativi successivi.
    """
    if len(variables) < 2:
        raise ValueError("Servono almeno due variabili per la conseguenza logica")

    negated = [False, True]
    negated.extend(bool(rng.getrandbits(1)) for _ in variables[2:])
    rng.shuffle(negated)

    nodes: list[Any] = [
        Not(Var(variable)) if is_negated else Var(variable)
        for variable, is_negated in zip(variables, negated, strict=True)
    ]
    rng.shuffle(nodes)

    while len(nodes) > 1:
        left = nodes.pop(rng.randrange(len(nodes)))
        right = nodes.pop(rng.randrange(len(nodes)))
        if rng.random() < 0.5:
            left, right = right, left
        combined = And(left, right)
        nodes.insert(rng.randrange(len(nodes) + 1), combined)

    return _as_prolog(nodes[0])


def _build_logical_consequence_question_once(
    variable_count: int,
    correct_options_count: int,
    wrong_options_count: int,
    *,
    seed: int,
    operator_cycles: int | None,
    allow_spoken_mode: bool,
    bridge: PrologBridge,
    remaining_timeout: Callable[[int | None], int],
    deadline: float,
) -> dict:
    """Esegue un singolo tentativo conservando tutti i vincoli didattici."""
    rng = random.Random(seed)
    required_options = correct_options_count + wrong_options_count
    variables = _default_vars(variable_count)
    question_prolog = _build_consequence_ready_question_formula(variables, rng)
    question_formula_entry = _formula_entry(question_prolog, rng=rng, label="formula domanda")
    question_prolog_display = question_formula_entry["formula_prolog"]

    if time.monotonic() >= deadline:
        raise GenerationDeadlineExceeded("Tempo esaurito durante la generazione della conseguenza logica")

    candidates = _collect_candidate_formulas(
        bridge=bridge,
        variables=variables,
        required_options=required_options,
        rng=rng,
        timeout_provider=remaining_timeout,
        operator_cycles=operator_cycles,
        excluded_formulas=[question_prolog],
        dedupe_by_commutative_signature=True,
        forbid_adjacent_duplicate_atoms=True,
        spoken_only=allow_spoken_mode,
    )

    if len(candidates) < required_options:
        raise _LogicalConsequenceConstructionError(
            "Non ci sono abbastanza formule candidate per il quiz di conseguenza logica"
        )

    candidate_signatures = {_commutative_signature(candidate) for candidate in candidates}
    for synthetic in _build_one_operator_candidates(variables):
        if _has_adjacent_duplicate_atoms(synthetic):
            continue
        signature = _commutative_signature(synthetic)
        if signature in candidate_signatures:
            continue
        if signature == _commutative_signature(question_prolog):
            continue
        candidates.append(synthetic)
        candidate_signatures.add(signature)

    for synthetic in _build_special_logical_consequence_candidates(variables):
        signature = _commutative_signature(synthetic)
        if signature in candidate_signatures:
            continue
        if signature == _commutative_signature(question_prolog):
            continue
        candidates.append(synthetic)
        candidate_signatures.add(signature)

    for synthetic in _build_two_operator_candidates(variables):
        if _has_adjacent_duplicate_atoms(synthetic):
            continue
        signature = _commutative_signature(synthetic)
        if signature in candidate_signatures:
            continue
        if signature == _commutative_signature(question_prolog):
            continue
        candidates.append(synthetic)
        candidate_signatures.add(signature)

    candidates = [
        candidate
        for candidate in candidates
        if (
            _logical_consequence_operator_bucket(candidate) is not None
            or _logical_consequence_special_bucket(candidate) is not None
        )
        and (not allow_spoken_mode or _formula_is_spoken_friendly(candidate))
    ]

    if len(candidates) < required_options:
        raise _LogicalConsequenceConstructionError(
            "Non ci sono abbastanza formule candidate con 1 o 2 operatori per il quiz di conseguenza logica"
        )

    implication_cache: dict[str, bool] = {}

    def is_logical_consequence(candidate: str) -> bool:
        if candidate in implication_cache:
            return implication_cache[candidate]
        try:
            result = bridge.implies_formula(
                question_prolog,
                candidate,
                vars_list=variables,
                timeout=remaining_timeout(2),
            )
        except GenerationDeadlineExceeded:
            raise
        except Exception:
            # Un errore del bridge non dimostra che la formula non sia una
            # conseguenza: propagarlo evita sia un'etichetta falsa sia un
            # tentativo nascosto con dati diversi.
            raise
        if time.monotonic() >= deadline:
            raise GenerationDeadlineExceeded(
                "Tempo esaurito durante la verifica delle conseguenze logiche"
            )
        if not isinstance(result, bool):
            raise _LogicalConsequenceConstructionError(
                "Risposta non valida dal bridge durante la verifica delle conseguenze logiche"
            )
        implication_cache[candidate] = result
        return result

    consequence_candidates: list[str] = []
    non_consequence_candidates: list[str] = []

    shuffled_candidates = list(candidates)
    rng.shuffle(shuffled_candidates)
    for candidate in shuffled_candidates:
        if time.monotonic() >= deadline:
            raise GenerationDeadlineExceeded(
                "Tempo esaurito durante la verifica delle conseguenze logiche"
            )
        if is_logical_consequence(candidate):
            consequence_candidates.append(candidate)
        else:
            non_consequence_candidates.append(candidate)

    if len(consequence_candidates) < correct_options_count or len(non_consequence_candidates) < wrong_options_count:
        raise _LogicalConsequenceConstructionError(
            "Impossibile trovare abbastanza opzioni per il quiz di conseguenza logica"
        )

    if variable_count >= 4 and required_options == 4:
        selected = _select_logical_consequence_variable_mix(
            rng=rng,
            consequence_candidates=consequence_candidates,
            non_consequence_candidates=non_consequence_candidates,
            correct_count=correct_options_count,
            wrong_count=wrong_options_count,
        )
        if selected is None:
            raise _LogicalConsequenceConstructionError(
                "Impossibile trovare abbastanza opzioni con 2 formule a 2 variabili e 2 formule a 3 variabili"
            )
    else:
        selected = _select_logical_consequence_options(
            rng=rng,
            consequence_candidates=consequence_candidates,
            non_consequence_candidates=non_consequence_candidates,
            correct_count=correct_options_count,
            wrong_count=wrong_options_count,
        )

    if selected is None:
        raise _LogicalConsequenceConstructionError(
            "Impossibile rispettare i vincoli di conseguenza logica e garantire una risposta atomica o negata"
        )

    selected_correct, selected_wrong = selected

    if len({_commutative_signature(option) for option in selected_correct + selected_wrong}) != len(
        selected_correct + selected_wrong
    ):
        raise RuntimeError("Postcondizione fallita: formule non distinte nel quiz di conseguenza logica")

    options = [_formula_entry(formula, rng=rng, is_consequence=True) for formula in selected_correct] + [
        _formula_entry(formula, rng=rng, is_consequence=False) for formula in selected_wrong
    ]
    rng.shuffle(options)

    result = {
        "type": "logical_consequence_question",
        "variable_count": variable_count,
        "correct_options_count": correct_options_count,
        "wrong_options_count": wrong_options_count,
        "variables": variables,
        "question_prolog": question_prolog_display,
        "question_formula": question_formula_entry,
        "options": options,
        "spoken_mode": allow_spoken_mode,
        "source": "prolog_implies_formula",
    }

    _ensure_keys(
        result,
        ["question_prolog", "options", "variables"],
    )
    return result


def build_logical_consequence_question(
    variable_count: int,
    correct_options_count: int,
    wrong_options_count: int,
    timeout: int = 10,
    seed: int | None = None,
    operator_cycles: int | None = None,
    allow_spoken_mode: bool = False,
    bridge: PrologBridge | None = None,
) -> dict:
    """Costruisce un quiz di conseguenza logica con opzioni corrette/errate.

    Semantica usata: `Q |= R` se ogni valutazione che rende vera la formula domanda `Q`
    rende vera anche l'opzione `R`. La formula-domanda viene costruita in una famiglia
    che garantisce a priori candidati veri e falsi, senza retry o fallback.
    """
    _req_int_ge("variable_count", variable_count, 1)
    _req_int_ge("timeout", int(timeout), 1)
    if not MIN_LOGICAL_CONSEQUENCE_VARIABLES <= variable_count <= MAX_LOGICAL_CONSEQUENCE_VARIABLES:
        raise ValueError(
            "variable_count deve essere compreso tra "
            f"{MIN_LOGICAL_CONSEQUENCE_VARIABLES} e {MAX_LOGICAL_CONSEQUENCE_VARIABLES}"
        )
    if correct_options_count < 1:
        raise ValueError("correct_options_count deve essere >= 1")
    if wrong_options_count < 1:
        raise ValueError("wrong_options_count deve essere >= 1")
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)

    required_options = correct_options_count + wrong_options_count
    if required_options % 2 != 0:
        raise ValueError("Il totale delle opzioni deve essere pari")
    if required_options > MAX_LOGICAL_CONSEQUENCE_OPTIONS:
        raise ValueError(f"Il totale delle opzioni non può superare {MAX_LOGICAL_CONSEQUENCE_OPTIONS}")

    resolved_bridge = _ensure_bridge(bridge)
    deadline = time.monotonic() + max(1, int(timeout))
    remaining_timeout = _make_timeout_provider(timeout)
    seed_value = seed if seed is not None else random.SystemRandom().getrandbits(128)
    return _build_logical_consequence_question_once(
        variable_count=variable_count,
        correct_options_count=correct_options_count,
        wrong_options_count=wrong_options_count,
        seed=seed_value,
        operator_cycles=operator_cycles,
        allow_spoken_mode=allow_spoken_mode,
        bridge=resolved_bridge,
        remaining_timeout=remaining_timeout,
        deadline=deadline,
    )


__all__ = ["build_logical_consequence_question"]
