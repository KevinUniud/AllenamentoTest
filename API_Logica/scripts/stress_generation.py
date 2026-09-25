#!/usr/bin/env python3
"""Stress test deterministico dei cinque tipi di esercizio usati dalla Webpage.

Per impostazione predefinita genera 100 esercizi per tipologia, controlla il
contratto delle opzioni, verifica semanticamente l'unica risposta corretta e
richiede almeno il 95% di fingerprint distinti. Verifica inoltre che i rami di
emergenza e il fallback della pipeline parlata non vengano usati. Il bridge
SWI-Prolog rimane persistente per l'intera esecuzione.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import random
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from testlogica import (  # noqa: E402
    And,
    Iff,
    Imp,
    Not,
    Or,
    Var,
    generator,
)
from testlogica.metrics import formula_atom_count, formula_operator_count  # noqa: E402
from testlogica.prolog.codec import collect_variables, from_prolog  # noqa: E402
from testlogica.prolog_bridge import PrologBridge  # noqa: E402

DEFAULT_COUNT = 100
DEFAULT_MINIMUM_UNIQUE_RATIO = 0.95
DEFAULT_SEED = 20260906
GENERATION_TIMEOUT_SECONDS = 10
MAX_FAILURE_SAMPLES = 10
MAX_DUPLICATE_SAMPLES = 10

NOMI = [
    "Luca",
    "Matteo",
    "Alessandro",
    "Marco",
    "Davide",
    "Giulia",
    "Sofia",
    "Martina",
    "Chiara",
    "Elisa",
]
AZIONI = [
    "nuota",
    "corre",
    "salta",
    "guarda",
    "parla",
    "apre la porta",
    "chiude la porta",
    "ascolta",
]

TYPE_SEED_OFFSETS = {
    "equivalence": 0,
    "truth-value": 100_000,
    "logical-consequence": 200_000,
    "translation": 300_000,
    "quantifier-negation": 400_000,
}


class ValidationError(RuntimeError):
    """Segnala un payload generato ma non utilizzabile dalla Webpage."""


class FallbackAuditBridge(PrologBridge):
    """Conta i rami di emergenza senza aggiungere campi ai payload pubblici."""

    def __init__(self) -> None:
        super().__init__(persistent=True)
        self.fallback_counts: Counter[str] = Counter()

    def rewrite_formula(self, expr: Any, timeout: int = 10) -> list[str]:
        self.fallback_counts["equivalence_rewrite_formula"] += 1
        return super().rewrite_formula(expr, timeout=timeout)

    def record_python_answer_fallback(self) -> None:
        self.fallback_counts["python_answer_transform"] += 1


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("deve essere un intero maggiore o uguale a 1")
    return parsed


def _ratio(value: str) -> float:
    parsed = float(value)
    if not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError("deve essere compreso tra 0 e 1")
    return parsed


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} non e un oggetto")
    return value


def _require_string(value: Any, label: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), f"{label} non e una stringa non vuota")
    return value.strip()


def _require_list(value: Any, label: str) -> list[Any]:
    _require(isinstance(value, list), f"{label} non e una lista")
    return value


def _require_bool(value: Any, label: str) -> bool:
    _require(isinstance(value, bool), f"{label} non e booleano")
    return value


def _require_string_list(value: Any, label: str) -> list[str]:
    raw_values = _require_list(value, label)
    return [_require_string(item, f"{label}[{index}]") for index, item in enumerate(raw_values)]


def _formula_from_option(option: Mapping[str, Any], label: str) -> str:
    formula = option.get("formula_prolog", option.get("formula"))
    return _require_string(formula, f"{label}.formula")


def _validated_options(
    result: Mapping[str, Any],
    *,
    expected_count: int,
    correct_field: str,
) -> tuple[list[Mapping[str, Any]], list[str], list[bool]]:
    raw_options = _require_list(result.get("options"), "options")
    _require(len(raw_options) == expected_count, f"options deve contenere {expected_count} elementi")

    options: list[Mapping[str, Any]] = []
    formulas: list[str] = []
    correct_flags: list[bool] = []
    for index, raw_option in enumerate(raw_options):
        option = _require_mapping(raw_option, f"options[{index}]")
        flag = _require_bool(option.get(correct_field), f"options[{index}].{correct_field}")
        options.append(option)
        formulas.append(_formula_from_option(option, f"options[{index}]"))
        correct_flags.append(flag)

    normalized_formulas = ["".join(formula.split()) for formula in formulas]
    _require(len(set(normalized_formulas)) == expected_count, "le formule delle opzioni non sono distinte")
    _require(sum(correct_flags) == 1, "la domanda non contiene esattamente una risposta corretta")
    return options, formulas, correct_flags


def _evaluate_formula(node: Any, valuation: Mapping[str, bool]) -> bool:
    if isinstance(node, Var):
        try:
            return valuation[node.name]
        except KeyError as exc:
            raise ValidationError(f"valutazione mancante per la variabile {node.name!r}") from exc
    if isinstance(node, Not):
        return not _evaluate_formula(node.expr, valuation)
    if isinstance(node, And):
        return _evaluate_formula(node.left, valuation) and _evaluate_formula(node.right, valuation)
    if isinstance(node, Or):
        return _evaluate_formula(node.left, valuation) or _evaluate_formula(node.right, valuation)
    if isinstance(node, Imp):
        return not _evaluate_formula(node.left, valuation) or _evaluate_formula(node.right, valuation)
    if isinstance(node, Iff):
        return _evaluate_formula(node.left, valuation) == _evaluate_formula(node.right, valuation)
    raise ValidationError(f"nodo formula non supportato: {type(node).__name__}")


def _parse_formula(formula: str, label: str) -> Any:
    try:
        return from_prolog(formula)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} non e una formula proposizionale valida: {exc}") from exc


def _validate_negation_chain(formula: str, label: str) -> None:
    _require(
        not generator._has_excessive_negation_chain(formula),
        f"{label} supera il limite di {generator.MAX_CONSECUTIVE_NEGATIONS} negazioni consecutive",
    )


def _validate_trace_negation_chains(owner: Mapping[str, Any], label: str) -> None:
    raw_trace = owner.get("transformation")
    if raw_trace is None:
        return
    trace = _require_mapping(raw_trace, f"{label}.transformation")
    for field in ("source_formula_prolog", "final_formula_prolog"):
        formula = _require_string(trace.get(field), f"{label}.transformation.{field}")
        _validate_negation_chain(formula, f"{label}.transformation.{field}")
    steps = _require_list(trace.get("steps"), f"{label}.transformation.steps")
    for index, raw_step in enumerate(steps):
        step = _require_mapping(raw_step, f"{label}.transformation.steps[{index}]")
        for field in (
            "before_prolog",
            "after_prolog",
            "before_subformula_prolog",
            "after_subformula_prolog",
        ):
            formula = _require_string(
                step.get(field),
                f"{label}.transformation.steps[{index}].{field}",
            )
            _validate_negation_chain(
                formula,
                f"{label}.transformation.steps[{index}].{field}",
            )


def _valuations(variables: Sequence[str]):
    for values in itertools.product((False, True), repeat=len(variables)):
        yield dict(zip(variables, values, strict=True))


def _truth_vector(node: Any, variables: Sequence[str]) -> str:
    return "".join("1" if _evaluate_formula(node, valuation) else "0" for valuation in _valuations(variables))


def _contains_negation(node: Any) -> bool:
    if isinstance(node, Var):
        return False
    if isinstance(node, Not):
        return True
    if isinstance(node, (And, Or, Imp, Iff)):
        return _contains_negation(node.left) or _contains_negation(node.right)
    raise ValidationError(f"nodo formula non supportato: {type(node).__name__}")


def _formula_semantics(formula: str, variables: Sequence[str]) -> dict[str, Any]:
    node = _parse_formula(formula, "formula")
    formula_variables = set(collect_variables(node))
    universe = set(variables)
    _require(formula_variables <= universe, "la formula usa variabili fuori dall'universo dichiarato")
    return {
        "variables": list(variables),
        "truth_vector": _truth_vector(node, variables),
    }


def _semantic_relations(
    question: str,
    options: Sequence[str],
    variables: Sequence[str],
) -> tuple[list[bool], list[bool]]:
    question_node = _parse_formula(question, "question_prolog")
    option_nodes = [_parse_formula(formula, "opzione") for formula in options]
    equivalences = [True] * len(option_nodes)
    consequences = [True] * len(option_nodes)

    for valuation in _valuations(variables):
        question_value = _evaluate_formula(question_node, valuation)
        for index, option_node in enumerate(option_nodes):
            option_value = _evaluate_formula(option_node, valuation)
            equivalences[index] = equivalences[index] and option_value == question_value
            consequences[index] = consequences[index] and (not question_value or option_value)
    return equivalences, consequences


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_options(
    formulas: Sequence[str],
    correct_flags: Sequence[bool],
    variables: Sequence[str],
) -> list[dict[str, Any]]:
    options = [
        {
            "semantics": _formula_semantics(formula, variables),
            "correct": correct,
        }
        for formula, correct in zip(formulas, correct_flags, strict=True)
    ]
    return sorted(options, key=_canonical_json)


def _validate_declared_variables(result: Mapping[str, Any], expected: Sequence[str]) -> list[str]:
    variables = _require_string_list(result.get("variables"), "variables")
    _require(variables == list(expected), f"variables deve essere {list(expected)!r}, ricevuto {variables!r}")
    return variables


def _validate_equivalence(raw_result: Any) -> tuple[str, str]:
    result = _require_mapping(raw_result, "equivalence")
    options, formulas, correct_flags = _validated_options(
        result,
        expected_count=4,
        correct_field="is_correct",
    )
    variables = _validate_declared_variables(result, ["p", "q", "r"])
    question = _require_string(result.get("question_prolog"), "question_prolog")
    question_node = _parse_formula(question, "question_prolog")
    _validate_negation_chain(question, "question_prolog")
    for index, (option, formula) in enumerate(zip(options, formulas, strict=True)):
        _validate_negation_chain(formula, f"options[{index}].formula")
        _validate_trace_negation_chains(option, f"options[{index}]")

    _require(formula_atom_count(question_node) == 3, "la formula domanda di equivalenza non contiene 3 atomi")
    equivalences, _ = _semantic_relations(question, formulas, variables)
    _require(sum(equivalences) == 1, "le opzioni non hanno esattamente una formula equivalente")
    _require(equivalences == correct_flags, "i flag is_correct non corrispondono all'equivalenza logica")

    modified = _require_mapping(result.get("modified_formula"), "modified_formula")
    modified_formula = _formula_from_option(modified, "modified_formula")
    _validate_negation_chain(modified_formula, "modified_formula.formula")
    _validate_trace_negation_chains(modified, "modified_formula")
    flagged_formula = formulas[correct_flags.index(True)]
    _require(modified_formula == flagged_formula, "modified_formula non coincide con l'opzione corretta")

    semantic_payload = {
        "kind": "equivalence",
        "question": _formula_semantics(question, variables),
        "options": _canonical_options(formulas, correct_flags, variables),
    }
    return _fingerprint(semantic_payload), "default"


def _parse_information(information: Any, variables: Sequence[str]) -> dict[str, bool]:
    _require(isinstance(information, list), "information non e una lista")
    parsed: dict[str, bool] = {}
    for index, entry in enumerate(information):
        text = _require_string(entry, f"information[{index}]")
        name, separator, raw_value = text.rpartition("-")
        _require(separator == "-" and raw_value in {"true", "false"}, f"information[{index}] non e valida")
        _require(name in variables, f"information[{index}] usa una variabile inattesa")
        _require(name not in parsed, f"information contiene due volte {name!r}")
        parsed[name] = raw_value == "true"
    _require(set(parsed) == set(variables), "information non assegna tutte e sole le variabili")
    return parsed


def _validate_truth_value(raw_result: Any) -> tuple[str, str]:
    result = _require_mapping(raw_result, "truth-value")
    _require(result.get("type") == "truth_value_options_question", "type truth-value non valido")
    _require(result.get("predicate_count") == 4, "predicate_count truth-value non vale 4")
    _require(result.get("true_options_count") == 1, "true_options_count non vale 1")
    _require(result.get("false_options_count") == 3, "false_options_count non vale 3")
    _, formulas, correct_flags = _validated_options(result, expected_count=4, correct_field="is_true")
    variables = _validate_declared_variables(result, ["p", "q", "r", "s"])
    valuation = _parse_information(result.get("information"), variables)

    evaluated: list[bool] = []
    for formula in formulas:
        node = _parse_formula(formula, "opzione truth-value")
        _require(set(collect_variables(node)) == set(variables), "un'opzione non usa tutte le variabili richieste")
        _require(formula_atom_count(node) == 4, "un'opzione truth-value non contiene esattamente 4 atomi")
        evaluated.append(_evaluate_formula(node, valuation))
    _require(evaluated == correct_flags, "i flag is_true non corrispondono alla valutazione dichiarata")

    semantic_payload = {
        "kind": "truth-value",
        "valuation": dict(sorted(valuation.items())),
        "options": _canonical_options(formulas, correct_flags, variables),
    }
    return _fingerprint(semantic_payload), "default"


def _validate_logical_consequence(raw_result: Any) -> tuple[str, str]:
    result = _require_mapping(raw_result, "logical-consequence")
    _require(result.get("type") == "logical_consequence_question", "type logical-consequence non valido")
    _require(result.get("variable_count") == 4, "variable_count logical-consequence non vale 4")
    _require(result.get("correct_options_count") == 1, "correct_options_count non vale 1")
    _require(result.get("wrong_options_count") == 3, "wrong_options_count non vale 3")
    _, formulas, correct_flags = _validated_options(result, expected_count=4, correct_field="is_consequence")
    variables = _validate_declared_variables(result, ["p", "q", "r", "s"])
    question = _require_string(result.get("question_prolog"), "question_prolog")
    question_node = _parse_formula(question, "question_prolog")
    _require(set(collect_variables(question_node)) == set(variables), "la domanda non usa tutte le variabili")

    option_nodes = [_parse_formula(formula, f"options[{index}]") for index, formula in enumerate(formulas)]
    variable_counts = sorted(len(set(collect_variables(node))) for node in option_nodes)
    _require(
        variable_counts == [2, 2, 3, 3],
        "le opzioni non contengono 2 formule a 2 variabili e 2 formule a 3 variabili",
    )
    for index, node in enumerate(option_nodes):
        operator_count = formula_operator_count(node)
        _require(
            operator_count in {1, 2},
            f"options[{index}] non contiene esattamente 1 o 2 operatori",
        )
        _require(
            operator_count != 1 or not _contains_negation(node),
            f"options[{index}] usa la negazione come unico operatore",
        )

    _, consequences = _semantic_relations(question, formulas, variables)
    _require(sum(consequences) == 1, "le opzioni non hanno esattamente una conseguenza logica")
    _require(consequences == correct_flags, "i flag is_consequence non corrispondono alla semantica")

    semantic_payload = {
        "kind": "logical-consequence",
        "question": _formula_semantics(question, variables),
        "options": _canonical_options(formulas, correct_flags, variables),
    }
    return _fingerprint(semantic_payload), "default"


def _fold_terms(connective: str, terms: Sequence[str]) -> str:
    _require(bool(terms), "impossibile comporre una lista vuota di termini")
    result = terms[0]
    for term in terms[1:]:
        result = f"{connective}({result},{term})"
    return result


def _expected_translation_formula(result: Mapping[str, Any]) -> tuple[str, str]:
    subtype = _require_string(result.get("subtype"), "subtype")
    metadata = _require_mapping(result.get("metadata"), "metadata")
    _require(metadata.get("people_count") == 3, "metadata.people_count non vale 3")

    if subtype == "propositional":
        template = _require_string(metadata.get("template_used"), "metadata.template_used")
        information = _require_list(result.get("info"), "info")
        _require(len(information) == 3, "info proposizionale non ha 3 voci")
        symbols = []
        for index, entry in enumerate(information):
            text = _require_string(entry, f"info[{index}]")
            symbol, separator, _ = text.partition(" = ")
            _require(separator == " = " and bool(symbol), f"info[{index}] non e valida")
            symbols.append(symbol)
        if template == "implication":
            _require(len(symbols) == 2, "il template implication deve usare 2 simboli")
            return f"imp({symbols[0]},{symbols[1]})", subtype
        _require(len(symbols) == 3, f"il template {template} deve usare 3 simboli")
        if template == "conjunction_chain":
            return f"and(and({symbols[0]},{symbols[1]}),{symbols[2]})", subtype
        if template == "disjunction_chain":
            return f"or(or({symbols[0]},{symbols[1]}),{symbols[2]})", subtype
        raise ValidationError(f"template proposizionale inatteso: {template!r}")

    if subtype == "quantifier":
        quantifier = metadata.get("quantifier_used")
        _require(quantifier in {"per_ogni", "esiste"}, "metadata.quantifier_used non valido")
        symbols = _require_string_list(metadata.get("predicate_symbols_used"), "metadata.predicate_symbols_used")
        _require(len(symbols) == 3, "servono 3 simboli predicativi")
        terms = [f"{symbol}(x)" for symbol in symbols]
        prefix = "forall" if quantifier == "per_ogni" else "exists"
        return f"{prefix}(x,{_fold_terms('and', terms)})", subtype

    raise ValidationError(f"subtype traduzione inatteso: {subtype!r}")


def _validate_translation(raw_result: Any) -> tuple[str, str]:
    result = _require_mapping(raw_result, "translation")
    _require(result.get("type") == "translation_question", "type translation non valido")
    _require(result.get("correct_options_count") == 1, "correct_options_count non vale 1")
    _require(result.get("wrong_options_count") == 3, "wrong_options_count non vale 3")
    _, formulas, correct_flags = _validated_options(result, expected_count=4, correct_field="is_correct")
    question = _require_string(result.get("question_text"), "question_text")
    expected_formula, subtype = _expected_translation_formula(result)
    _require(formulas[correct_flags.index(True)] == expected_formula, "l'opzione corretta non traduce il template")
    _require(formulas.count(expected_formula) == 1, "la traduzione corretta non compare esattamente una volta")

    information = _require_list(result.get("info"), "info")
    descriptions = []
    for index, entry in enumerate(information):
        text = _require_string(entry, f"info[{index}]")
        _symbol, separator, description = text.partition(" = ")
        _require(separator == " = " and bool(description), f"info[{index}] non e valida")
        descriptions.append(" ".join(description.split()))
    _require(
        len(descriptions) == len(set(descriptions)),
        "simboli distinti descrivono la stessa proposizione naturale",
    )
    semantic_payload = {
        "kind": "translation",
        "subtype": subtype,
        "question": " ".join(question.split()),
        "information": sorted(" ".join(str(entry).split()) for entry in information),
        "options": sorted(
            (
                {"formula": "".join(formula.split()), "correct": correct}
                for formula, correct in zip(formulas, correct_flags, strict=True)
            ),
            key=_canonical_json,
        ),
    }
    return _fingerprint(semantic_payload), subtype


def _format_logical(
    node: Any,
    parent_precedence: int = -1,
    parent_name: str = "",
    bound_variable: str | None = None,
) -> str:
    if isinstance(node, Var):
        if bound_variable is not None:
            predicate = node.name[:1].upper() + node.name[1:]
            return f"{predicate}({bound_variable})"
        return node.name
    if isinstance(node, Not):
        inner = _format_logical(node.expr, 4, "not", bound_variable)
        text = f"¬{inner}"
        return f"({text})" if parent_precedence > 4 else text

    binary_types = {
        And: ("and", "∧", 3),
        Or: ("or", "∨", 2),
        Imp: ("imp", "→", 1),
        Iff: ("iff", "↔", 0),
    }
    if isinstance(node, (And, Or, Imp, Iff)):
        name, symbol, precedence = binary_types[type(node)]
        left_node = node.left
        right_node = node.right
        left = _format_logical(left_node, precedence, name, bound_variable)
        right = _format_logical(
            right_node,
            precedence + (1 if name == "imp" else 0),
            name,
            bound_variable,
        )
        if name in {"and", "or"}:
            for side_name, child in (("left", left_node), ("right", right_node)):
                mixed = (isinstance(child, And) and name == "or") or (isinstance(child, Or) and name == "and")
                if mixed:
                    if side_name == "left" and not (left.startswith("(") and left.endswith(")")):
                        left = f"({left})"
                    if side_name == "right" and not (right.startswith("(") and right.endswith(")")):
                        right = f"({right})"
        text = f"{left} {symbol} {right}"
        nested_iff = name == "iff" and parent_name == "iff"
        return f"({text})" if parent_precedence > precedence or nested_iff else text
    raise ValidationError(f"nodo formula non renderizzabile: {type(node).__name__}")


def _format_bound_prolog(node: Any, bound_variable: str) -> str:
    if isinstance(node, Var):
        predicate = node.name[:1].upper() + node.name[1:]
        return f"{predicate}({bound_variable})"
    if isinstance(node, Not):
        return f"not({_format_bound_prolog(node.expr, bound_variable)})"
    operators = {And: "and", Or: "or", Imp: "imp", Iff: "iff"}
    if isinstance(node, (And, Or, Imp, Iff)):
        operator = operators[type(node)]
        left = _format_bound_prolog(node.left, bound_variable)
        right = _format_bound_prolog(node.right, bound_variable)
        return f"{operator}({left},{right})"
    raise ValidationError(f"nodo formula non trasformabile in predicato: {type(node).__name__}")


def _build_quantifier_negation(base_formula: str, seed: int) -> dict[str, Any]:
    base_node = _parse_formula(base_formula, "formula base quantificatori")
    bound_variable = "x"
    logical_formula = _format_logical(base_node, bound_variable=bound_variable)
    predicate_formula_source = _format_bound_prolog(base_node, bound_variable)
    wrapped_formula = f"({logical_formula})"
    rng = random.Random(seed)
    quantifier = rng.choice(["∀", "∃"])
    is_universal = quantifier == "∀"
    original = f"{quantifier}x {wrapped_formula}"
    correct = f"{'∃' if is_universal else '∀'}x ¬{wrapped_formula}"
    wrongs = (
        [f"∀x ¬{wrapped_formula}", f"∃x {wrapped_formula}"]
        if is_universal
        else [f"∃x ¬{wrapped_formula}", f"∀x {wrapped_formula}"]
    )
    options = [{"text": formula, "correct": formula == correct} for formula in [correct, *wrongs]]
    rng.shuffle(options)
    return {
        "kind": "quantifier-negation",
        "question": f"Qual'è la negazione di \"{original}\"?",
        "base_formula_prolog": base_formula,
        "predicate_formula_prolog": predicate_formula_source,
        "quantifier": quantifier,
        "options": options,
    }


def _validate_quantifier_negation(raw_result: Any) -> tuple[str, str]:
    result = _require_mapping(raw_result, "quantifier-negation")
    _require(result.get("kind") == "quantifier-negation", "kind quantifier-negation non valido")
    base_formula = _require_string(result.get("base_formula_prolog"), "base_formula_prolog")
    base_node = _parse_formula(base_formula, "base_formula_prolog")
    variables = ["p", "q", "r", "s"]
    _require(set(collect_variables(base_node)) == set(variables), "la formula base non usa tutte le 4 variabili")

    quantifier = result.get("quantifier")
    _require(quantifier in {"∀", "∃"}, "quantifier non valido")
    raw_options = _require_list(result.get("options"), "options")
    _require(len(raw_options) == 3, "servono esattamente 3 opzioni")
    options = [_require_mapping(option, f"options[{index}]") for index, option in enumerate(raw_options)]
    texts = [_require_string(option.get("text"), f"options[{index}].text") for index, option in enumerate(options)]
    flags = [_require_bool(option.get("correct"), f"options[{index}].correct") for index, option in enumerate(options)]
    _require(sum(flags) == 1, "non c'e esattamente un'opzione corretta")
    _require(len(set(texts)) == 3, "le opzioni quantificate non sono distinte")

    bound_variable = "x"
    predicate_formula_source = _format_bound_prolog(base_node, bound_variable)
    _require(
        result.get("predicate_formula_prolog") == predicate_formula_source,
        "la formula sorgente non lega gli atomi alla variabile x",
    )
    wrapped_formula = f"({_format_logical(base_node, bound_variable=bound_variable)})"
    expected_correct = f"{'∃' if quantifier == '∀' else '∀'}x ¬{wrapped_formula}"
    expected_wrongs = (
        {f"∀x ¬{wrapped_formula}", f"∃x {wrapped_formula}"}
        if quantifier == "∀"
        else {f"∃x ¬{wrapped_formula}", f"∀x {wrapped_formula}"}
    )
    flagged_text = texts[flags.index(True)]
    _require(flagged_text == expected_correct, "la negazione quantificata corretta non applica la dualita")
    actual_wrongs = {text for text, flag in zip(texts, flags, strict=True) if not flag}
    _require(actual_wrongs == expected_wrongs, "distrattori non Web")

    matrix_semantics = _formula_semantics(base_formula, variables)
    negated_matrix_semantics = {
        "variables": matrix_semantics["variables"],
        "truth_vector": "".join("0" if value == "1" else "1" for value in matrix_semantics["truth_vector"]),
    }
    dual_quantifier = "exists" if quantifier == "∀" else "forall"
    source_quantifier = "forall" if quantifier == "∀" else "exists"
    semantic_payload = {
        "kind": "quantifier-negation",
        "question": {
            "quantifier": source_quantifier,
            "matrix": matrix_semantics,
        },
        "options": sorted(
            [
                {
                    "quantifier": dual_quantifier,
                    "matrix": negated_matrix_semantics,
                    "correct": True,
                },
                {
                    "quantifier": source_quantifier,
                    "matrix": negated_matrix_semantics,
                    "correct": False,
                },
                {
                    "quantifier": dual_quantifier,
                    "matrix": matrix_semantics,
                    "correct": False,
                },
            ],
            key=_canonical_json,
        ),
    }
    return _fingerprint(semantic_payload), str(quantifier)


def _generate_equivalence(bridge: PrologBridge, seed: int) -> dict[str, Any]:
    return generator.build_ex_depth(
        use_all=False,
        timeout=GENERATION_TIMEOUT_SECONDS,
        seed=seed,
        wrong_answers_count=3,
        bridge=bridge,
        allow_spoken_mode=False,
    )


def _generate_truth_value(bridge: PrologBridge, seed: int) -> dict[str, Any]:
    return generator.build_tvq(
        predicate_count=4,
        true_options_count=1,
        false_options_count=3,
        timeout=GENERATION_TIMEOUT_SECONDS,
        seed=seed,
        bridge=bridge,
        allow_spoken_mode=False,
    )


def _generate_logical_consequence(bridge: PrologBridge, seed: int) -> dict[str, Any]:
    return generator.build_logical_consequence_question(
        variable_count=4,
        correct_options_count=1,
        wrong_options_count=3,
        timeout=GENERATION_TIMEOUT_SECONDS,
        seed=seed,
        bridge=bridge,
        allow_spoken_mode=False,
    )


def _generate_translation(_bridge: PrologBridge, seed: int) -> dict[str, Any]:
    return generator.build_translation_question(
        mode="auto",
        quantifier_ratio=0.5,
        wrong_options_count=3,
        names_pool=NOMI,
        people_count=3,
        actions_pool=AZIONI,
        allow_spoken_mode=False,
        seed=seed,
        timeout=GENERATION_TIMEOUT_SECONDS,
    )


def _generate_quantifier_negation(bridge: PrologBridge, seed: int) -> dict[str, Any]:
    base_formula = generator.generate_formula_by_variable_count(
        variable_count=4,
        use_all=False,
        timeout=GENERATION_TIMEOUT_SECONDS,
        seed=seed,
        bridge=bridge,
        allow_spoken_mode=False,
    )
    return _build_quantifier_negation(base_formula, seed)


Generator = Callable[[PrologBridge, int], dict[str, Any]]
Validator = Callable[[Any], tuple[str, str]]

TYPE_CASES: list[tuple[str, Generator, Validator]] = [
    ("equivalence", _generate_equivalence, _validate_equivalence),
    ("truth-value", _generate_truth_value, _validate_truth_value),
    ("logical-consequence", _generate_logical_consequence, _validate_logical_consequence),
    ("translation", _generate_translation, _validate_translation),
    ("quantifier-negation", _generate_quantifier_negation, _validate_quantifier_negation),
]


def _failure_sample(index: int, seed: int, exc: Exception) -> dict[str, Any]:
    return {
        "index": index + 1,
        "seed": seed,
        "error_type": type(exc).__name__,
        "message": str(exc),
    }


def _run_case(
    *,
    name: str,
    generate: Generator,
    validate: Validator,
    bridge: FallbackAuditBridge,
    count: int,
    minimum_unique_ratio: float,
    base_seed: int,
) -> dict[str, Any]:
    started = time.monotonic()
    fallback_counts_before = Counter(bridge.fallback_counts)
    generation_succeeded = 0
    validation_succeeded = 0
    generation_failures: list[dict[str, Any]] = []
    validation_failures: list[dict[str, Any]] = []
    fingerprints: dict[str, list[int]] = defaultdict(list)
    variant_counts: Counter[str] = Counter()
    seed_offset = TYPE_SEED_OFFSETS[name]

    for index in range(count):
        seed = base_seed + seed_offset + index
        try:
            result = generate(bridge, seed)
            generation_succeeded += 1
        except Exception as exc:
            if len(generation_failures) < MAX_FAILURE_SAMPLES:
                generation_failures.append(_failure_sample(index, seed, exc))
            continue

        try:
            fingerprint, variant = validate(result)
            validation_succeeded += 1
            fingerprints[fingerprint].append(index + 1)
            variant_counts[variant] += 1
        except Exception as exc:
            if len(validation_failures) < MAX_FAILURE_SAMPLES:
                validation_failures.append(_failure_sample(index, seed, exc))

    unique_count = len(fingerprints)
    unique_ratio = unique_count / count
    duplicate_samples = [
        {
            "fingerprint": fingerprint,
            "occurrences": len(indices),
            "exercise_indices": indices[:10],
        }
        for fingerprint, indices in fingerprints.items()
        if len(indices) > 1
    ][:MAX_DUPLICATE_SAMPLES]
    fallback_counts = bridge.fallback_counts - fallback_counts_before
    fallback_total = sum(fallback_counts.values())
    passed = validation_succeeded == count and unique_ratio >= minimum_unique_ratio and fallback_total == 0
    return {
        "requested": count,
        "generated": generation_succeeded,
        "validated": validation_succeeded,
        "generation_failures": count - generation_succeeded,
        "validation_failures": generation_succeeded - validation_succeeded,
        "failure_samples": {
            "generation": generation_failures,
            "validation": validation_failures,
        },
        "unique_fingerprints": unique_count,
        "unique_ratio": round(unique_ratio, 6),
        "minimum_unique_ratio": minimum_unique_ratio,
        "duplicate_samples": duplicate_samples,
        "variants": dict(sorted(variant_counts.items())),
        "fallbacks": dict(sorted(fallback_counts.items())),
        "fallback_total": fallback_total,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "passed": passed,
    }


def _audit_spoken_pipeline(
    *,
    bridge: FallbackAuditBridge,
    count: int,
    base_seed: int,
) -> dict[str, Any]:
    """Verifica che la normalizzazione parlata non usi il flag di fallback."""
    started = time.monotonic()
    failures: list[dict[str, Any]] = []
    generated = 0
    fallback_count = 0

    for variable_count in (3, 4, 5):
        for index in range(count):
            seed = base_seed + 500_000 + variable_count * 10_000 + index
            try:
                result = generator.generate_formula_by_variable_count_json(
                    variable_count=variable_count,
                    use_all=False,
                    timeout=GENERATION_TIMEOUT_SECONDS,
                    seed=seed,
                    bridge=bridge,
                    allow_spoken_mode=True,
                )
                generated += 1
                formula = _require_string(result.get("formula_prolog"), "formula_prolog")
                if not generator._formula_is_spoken_friendly(
                    formula,
                    max_nested_negations=0,
                ):
                    if len(failures) < MAX_FAILURE_SAMPLES:
                        failures.append(
                            {
                                "variable_count": variable_count,
                                "seed": seed,
                                "message": "formula_prolog contiene negazioni nella base parlata",
                                "formula": formula,
                            }
                        )
                if result.get("spoken_fallback_used") is not False:
                    fallback_count += 1
                    if len(failures) < MAX_FAILURE_SAMPLES:
                        failures.append(
                            {
                                "variable_count": variable_count,
                                "seed": seed,
                                "message": "spoken_fallback_used non vale false",
                            }
                        )
            except Exception as exc:
                if len(failures) < MAX_FAILURE_SAMPLES:
                    failures.append(
                        {
                            "variable_count": variable_count,
                            "seed": seed,
                            "error_type": type(exc).__name__,
                            "message": str(exc),
                        }
                    )

    requested = count * 3
    return {
        "requested": requested,
        "generated": generated,
        "fallback_total": fallback_count,
        "failure_samples": failures,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "passed": generated == requested and fallback_count == 0 and not failures,
    }


def _print_readable(report: Mapping[str, Any]) -> None:
    print("\nRisultati stress test generazione")
    print("=" * 34)
    type_reports = _require_mapping(report.get("types"), "types")
    for name, raw_result in type_reports.items():
        result = _require_mapping(raw_result, name)
        status = "PASS" if result.get("passed") else "FAIL"
        print(
            f"[{status}] {name}: "
            f"generati {result['generated']}/{result['requested']}, "
            f"validi {result['validated']}/{result['requested']}, "
            f"unici {result['unique_fingerprints']}/{result['requested']} "
            f"({float(result['unique_ratio']):.1%}), "
            f"tempo {result['elapsed_seconds']}s"
        )
        print(f"       fallback: {result.get('fallback_total', 0)}")
        variants = result.get("variants")
        if isinstance(variants, Mapping) and variants:
            formatted = ", ".join(f"{key}={value}" for key, value in variants.items())
            print(f"       varianti: {formatted}")
        failures = _require_mapping(result.get("failure_samples"), "failure_samples")
        for category in ("generation", "validation"):
            samples = failures.get(category)
            if isinstance(samples, list):
                for sample in samples[:3]:
                    if isinstance(sample, Mapping):
                        print(
                            f"       {category} #{sample.get('index')} seed={sample.get('seed')}: "
                            f"{sample.get('error_type')}: {sample.get('message')}"
                        )
    raw_spoken = report.get("spoken_pipeline")
    if isinstance(raw_spoken, Mapping):
        spoken_status = "PASS" if raw_spoken.get("passed") else "FAIL"
        print(
            f"[{spoken_status}] spoken-pipeline: "
            f"generati {raw_spoken.get('generated')}/{raw_spoken.get('requested')}, "
            f"fallback {raw_spoken.get('fallback_total')}, "
            f"tempo {raw_spoken.get('elapsed_seconds')}s"
        )
    print(f"\nEsito complessivo: {'PASS' if report.get('passed') else 'FAIL'}")
    print(f"Tempo totale: {report.get('elapsed_seconds')}s")


def _print_report(report: Mapping[str, Any]) -> None:
    _print_readable(report)
    print("\nReport JSON")
    print("=" * 11)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--count",
        type=_positive_integer,
        default=DEFAULT_COUNT,
        help=f"esercizi da generare per ogni tipologia (default: {DEFAULT_COUNT})",
    )
    parser.add_argument(
        "--minimum-unique-ratio",
        type=_ratio,
        default=DEFAULT_MINIMUM_UNIQUE_RATIO,
        help=f"quota minima di fingerprint unici, tra 0 e 1 (default: {DEFAULT_MINIMUM_UNIQUE_RATIO})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"seed base deterministico (default: {DEFAULT_SEED})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _argument_parser().parse_args(argv)
    started = time.monotonic()
    bridge = FallbackAuditBridge()
    type_reports: dict[str, Any] = {}
    spoken_report: dict[str, Any] | None = None
    original_python_answer_fallback = generator._maybe_swap_and_or

    def audited_python_answer_fallback(
        formula: str,
        rng: random.Random,
        swap_probability: float = 0.5,
    ) -> str:
        bridge.record_python_answer_fallback()
        return original_python_answer_fallback(formula, rng, swap_probability)

    generator._maybe_swap_and_or = audited_python_answer_fallback

    try:
        bridge.ensure_available()
        for name, generate, validate in TYPE_CASES:
            print(f"Esecuzione {name}: {args.count} esercizi...", file=sys.stderr, flush=True)
            type_reports[name] = _run_case(
                name=name,
                generate=generate,
                validate=validate,
                bridge=bridge,
                count=args.count,
                minimum_unique_ratio=args.minimum_unique_ratio,
                base_seed=args.seed,
            )
        print(f"Esecuzione spoken-pipeline: {args.count * 3} formule...", file=sys.stderr, flush=True)
        spoken_report = _audit_spoken_pipeline(
            bridge=bridge,
            count=args.count,
            base_seed=args.seed,
        )
    except KeyboardInterrupt:
        print("Stress test interrotto.", file=sys.stderr)
        return 130
    except Exception as exc:
        report = {
            "configuration": {
                "count_per_type": args.count,
                "minimum_unique_ratio": args.minimum_unique_ratio,
                "seed": args.seed,
            },
            "types": type_reports,
            "spoken_pipeline": spoken_report,
            "startup_error": {
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "passed": False,
        }
        _print_report(report)
        return 1
    finally:
        generator._maybe_swap_and_or = original_python_answer_fallback
        bridge.close()

    passed = (
        len(type_reports) == len(TYPE_CASES)
        and all(result["passed"] for result in type_reports.values())
        and spoken_report is not None
        and spoken_report["passed"]
    )
    report = {
        "configuration": {
            "count_per_type": args.count,
            "minimum_unique_ratio": args.minimum_unique_ratio,
            "seed": args.seed,
            "persistent_prolog_bridge": True,
            "parameters": {
                "equivalence": {"use_all": False, "wrong_answers_count": 3},
                "truth-value": {"predicate_count": 4, "true_options_count": 1, "false_options_count": 3},
                "logical-consequence": {
                    "variable_count": 4,
                    "correct_options_count": 1,
                    "wrong_options_count": 3,
                },
                "translation": {"mode": "auto", "quantifier_ratio": 0.5, "people_count": 3},
                "quantifier-negation": {"variable_count": 4, "option_count": 3},
            },
        },
        "types": type_reports,
        "spoken_pipeline": spoken_report,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "passed": passed,
    }
    _print_report(report)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
