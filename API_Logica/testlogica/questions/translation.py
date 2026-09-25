"""Rule-based Italian-to-logic translation questions."""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Any

from ..constants import TRANSLATION_WRONG_OPTIONS
from ..formula_construction import build_term_construction_trace
from ..validation import ensure_keys, require_int_at_least


def _translation_option(formula: str, *, is_correct: bool) -> dict[str, Any]:
    """Create one translation option with its deterministic construction trace."""
    return {
        "formula": formula,
        "is_correct": is_correct,
        "construction": build_term_construction_trace(formula),
    }


def _pick_subtype(mode: str, quantifier_ratio: float, rng: random.Random) -> str:
    if mode == "quantifier":
        return "quantifier"
    if mode == "propositional":
        return "propositional"
    if mode == "auto":
        return "quantifier" if rng.random() < quantifier_ratio else "propositional"
    raise ValueError("mode deve essere uno tra: auto, quantifier, propositional")


def _wrong_propositional_formulas(template: str, atoms: Sequence[str], correct: str) -> list[str]:
    if template == "implication":
        left, right = atoms
        candidates = [
            f"imp({right},{left})",
            f"and({left},{right})",
            f"or({left},{right})",
            f"iff({left},{right})",
            f"imp(not({left}),{right})",
        ]
    elif template == "conjunction_chain":
        first, second, third = atoms
        candidates = [
            f"or(or({first},{second}),{third})",
            f"imp(and({first},{second}),{third})",
            f"imp({first},and({second},{third}))",
            f"and({first},or({second},{third}))",
            f"iff(and({first},{second}),{third})",
        ]
    elif template == "disjunction_chain":
        first, second, third = atoms
        candidates = [
            f"and(and({first},{second}),{third})",
            f"imp(or({first},{second}),{third})",
            f"imp({first},or({second},{third}))",
            f"or({first},and({second},{third}))",
            f"iff(or({first},{second}),{third})",
        ]
    else:
        raise RuntimeError(f"Template proposizionale non supportato: {template}")

    unique = list(dict.fromkeys(candidate for candidate in candidates if candidate != correct))
    if len(unique) < 3:
        raise RuntimeError(
            f"Impossibile generare {TRANSLATION_WRONG_OPTIONS} opzioni sbagliate distinte per il quiz proposizionale"
        )
    return unique[:3]


def _build_propositional(
    *,
    names_pool: Sequence[str],
    actions_pool: Sequence[str],
    rng: random.Random,
    template: str,
    allow_spoken_mode: bool,
) -> dict[str, Any]:
    unique_names = list(dict.fromkeys(names_pool))
    unique_actions = list(dict.fromkeys(actions_pool))
    if not unique_names:
        raise ValueError("names_pool deve contenere almeno 1 nome")
    if not unique_actions:
        raise ValueError("actions_pool deve contenere almeno 1 azione")
    if template not in {"implication", "conjunction_chain", "disjunction_chain"}:
        raise ValueError(f"template_name non valido: {template}")

    atoms = rng.sample(["P", "Q", "R"], k=2 if template == "implication" else 3)
    symbols = list(dict.fromkeys(atoms))
    description_candidates = list(
        {
            f"{name} {action}": (name, action)
            for name in unique_names
            for action in unique_actions
        }.items()
    )
    if len(description_candidates) < len(symbols):
        raise ValueError(
            "names_pool e actions_pool non producono abbastanza descrizioni atomiche distinte"
        )

    # Massimizza insieme nomi e azioni distinti. Con il prodotto cartesiano
    # dei due pool, a ogni passo esiste una coppia che introduce entrambi finche
    # ciascun pool conserva valori non usati. Questo evita che il client debba
    # ritentare una domanda soltanto perche tutte le proposizioni usano la
    # stessa azione.
    rng.shuffle(description_candidates)
    selected_descriptions: list[tuple[str, tuple[str, str]]] = []
    covered_names: set[str] = set()
    covered_actions: set[str] = set()
    remaining_descriptions = list(description_candidates)
    while len(selected_descriptions) < len(symbols):
        best_score = max(
            (
                int(name not in covered_names) + int(action not in covered_actions),
                int(action not in covered_actions),
                int(name not in covered_names),
            )
            for _text, (name, action) in remaining_descriptions
        )
        selected_index = next(
            index
            for index, (_text, (name, action)) in enumerate(remaining_descriptions)
            if (
                int(name not in covered_names) + int(action not in covered_actions),
                int(action not in covered_actions),
                int(name not in covered_names),
            )
            == best_score
        )
        selected = remaining_descriptions.pop(selected_index)
        selected_descriptions.append(selected)
        _text, (name, action) = selected
        covered_names.add(name)
        covered_actions.add(action)
    symbol_to_text = {
        symbol: description
        for symbol, (description, _pair) in zip(symbols, selected_descriptions, strict=True)
    }
    selected_names = list(dict.fromkeys(pair[0] for _description, pair in selected_descriptions))
    selected_actions = list(dict.fromkeys(pair[1] for _description, pair in selected_descriptions))

    if template == "implication":
        left, right = atoms
        sentence = f"Se {symbol_to_text[left]} allora {symbol_to_text[right]}"
        correct = f"imp({left},{right})"
    elif template == "conjunction_chain":
        first, second, third = atoms
        sentence = f"{symbol_to_text[first]} e {symbol_to_text[second]} e {symbol_to_text[third]}"
        correct = f"and(and({first},{second}),{third})"
    else:
        first, second, third = atoms
        sentence = f"{symbol_to_text[first]} o {symbol_to_text[second]} o {symbol_to_text[third]}"
        correct = f"or(or({first},{second}),{third})"

    options = [
        _translation_option(correct, is_correct=True),
        *(
            _translation_option(item, is_correct=False)
            for item in _wrong_propositional_formulas(template, atoms, correct)
        ),
    ]
    rng.shuffle(options)
    return {
        "type": "translation_question",
        "subtype": "propositional",
        "question_text": f'Tradurre la seguente frase in linguaggio logico: "{sentence}"',
        "info": [f"{symbol} = {symbol_to_text[symbol]}" for symbol in symbols],
        "options": options,
        "correct_options_count": 1,
        "wrong_options_count": TRANSLATION_WRONG_OPTIONS,
        "metadata": {
            "quantifier_used": "none",
            "names_used": selected_names,
            "actions_used": list(selected_actions),
            "template_used": template,
            "spoken_mode": allow_spoken_mode,
            "repetition_used": len(set(atoms)) < len(atoms),
            "source": "rule_generator",
        },
    }


def _fold(connective: str, terms: Sequence[str]) -> str:
    if not terms:
        raise ValueError("terms non puo essere vuoto")
    result = terms[0]
    for term in terms[1:]:
        result = f"{connective}({result},{term})"
    return result


def _predicate_symbols(count: int) -> list[str]:
    require_int_at_least("count", count, 1)
    base = [chr(code) for code in range(ord("A"), ord("Z") + 1)]
    extended = list(base)
    suffix = 1
    while len(extended) < count:
        for symbol in base:
            extended.append(f"{symbol}{suffix}")
            if len(extended) >= count:
                break
        suffix += 1
    return extended[:count]


def _build_quantifier(*, actions_pool: Sequence[str], predicate_count: int, rng: random.Random) -> dict[str, Any]:
    require_int_at_least("predicate_count", predicate_count, 1)
    unique_actions = list(dict.fromkeys(actions_pool))
    if len(unique_actions) < predicate_count:
        raise ValueError(
            "actions_pool deve contenere almeno people_count azioni distinte per il subtype quantifier"
        )

    actions = rng.sample(unique_actions, predicate_count)
    symbols = _predicate_symbols(predicate_count)
    terms = [f"{symbol}(x)" for symbol in symbols]
    conjunction = _fold("and", terms)
    disjunction = _fold("or", terms)
    rest = terms[1:]
    if rest:
        implication = f"imp({terms[0]},{_fold('and', rest)})"
        alternative = disjunction
    else:
        # Con un solo predicato ``A -> not(A)`` e ``not(A)`` sono
        # semanticamente equivalenti. Usa quindi una contraddizione come
        # terzo distractor, mantenendo quattro significati distinti.
        implication = f"and({terms[0]},not({terms[0]}))"
        alternative = f"not({terms[0]})"
    natural_text = " e ".join(f"x {action}" for action in actions)
    quantifier = rng.choice(["per_ogni", "esiste"])

    if quantifier == "per_ogni":
        question = f'Tradurre la seguente frase in linguaggio logico: "Per ogni x, {natural_text}"'
        correct = f"forall(x,{conjunction})"
        wrong = [f"exists(x,{conjunction})", f"forall(x,{alternative})", f"forall(x,{implication})"]
    else:
        question = f'Tradurre la seguente frase in linguaggio logico: "Esiste un x tale che {natural_text}"'
        correct = f"exists(x,{conjunction})"
        wrong = [f"forall(x,{conjunction})", f"exists(x,{alternative})", f"exists(x,{implication})"]

    options = [
        _translation_option(correct, is_correct=True),
        *(_translation_option(item, is_correct=False) for item in wrong),
    ]
    rng.shuffle(options)
    return {
        "type": "translation_question",
        "subtype": "quantifier",
        "question_text": question,
        "info": [f"{symbol}(x) = x {action}" for symbol, action in zip(symbols, actions, strict=False)],
        "options": options,
        "correct_options_count": 1,
        "wrong_options_count": TRANSLATION_WRONG_OPTIONS,
        "metadata": {
            "quantifier_used": quantifier,
            "names_used": [],
            "actions_used": actions,
            "predicate_symbols_used": symbols,
            "source": "rule_generator",
        },
    }


def build_translation_question(
    *,
    mode: str,
    quantifier_ratio: float,
    wrong_options_count: int = 3,
    names_pool: Sequence[str],
    people_count: int | None = None,
    actions_pool: Sequence[str],
    allow_spoken_mode: bool,
    seed: int | None = None,
    timeout: int = 10,
) -> dict[str, Any]:
    require_int_at_least("timeout", int(timeout), 1)
    if wrong_options_count != TRANSLATION_WRONG_OPTIONS:
        raise ValueError(f"wrong_options_count deve essere {TRANSLATION_WRONG_OPTIONS}")
    if not 0 <= quantifier_ratio <= 1:
        raise ValueError("quantifier_ratio deve essere compreso tra 0 e 1")
    if not names_pool or not actions_pool:
        raise ValueError("names_pool e actions_pool non possono essere vuoti")
    if people_count is not None:
        require_int_at_least("people_count", int(people_count), 1)

    effective_quantifier_count = people_count or 2
    quantifier_is_possible = mode == "quantifier" or (mode == "auto" and quantifier_ratio > 0)
    propositional_is_possible = mode == "propositional" or (mode == "auto" and quantifier_ratio < 1)
    unique_names = list(dict.fromkeys(names_pool))
    unique_actions = list(dict.fromkeys(actions_pool))
    if quantifier_is_possible and len(unique_actions) < effective_quantifier_count:
        raise ValueError(
            "actions_pool deve contenere almeno "
            f"{effective_quantifier_count} azioni distinte quando il subtype quantifier è possibile"
        )
    if (
        propositional_is_possible
        and people_count is not None
        and len(unique_names) < people_count
    ):
        raise ValueError(
            "names_pool deve contenere almeno people_count nomi distinti "
            "quando il subtype propositional è possibile"
        )
    effective_propositional_names = people_count or len(unique_names)
    if (
        propositional_is_possible
        and effective_propositional_names * len(unique_actions) < 2
    ):
        raise ValueError(
            "names_pool e actions_pool devono produrre almeno 2 descrizioni atomiche distinte "
            "quando il subtype propositional è possibile"
        )

    rng = random.Random(seed)
    subtype = _pick_subtype(mode, quantifier_ratio, rng)
    if subtype == "quantifier":
        result = _build_quantifier(actions_pool=actions_pool, predicate_count=people_count or 2, rng=rng)
    else:
        names = unique_names
        if people_count is not None and people_count > len(names):
            raise ValueError("people_count non puo superare il numero di nomi distinti in names_pool")
        selected_names = names if people_count is None else rng.sample(names, people_count)
        description_capacity = len(
            {
                f"{name} {action}"
                for name in selected_names
                for action in unique_actions
            }
        )
        if allow_spoken_mode:
            template = (
                rng.choice(["conjunction_chain", "disjunction_chain"])
                if description_capacity >= 3
                else "implication"
            )
        elif people_count is not None and people_count >= 3 and description_capacity >= 3:
            template = rng.choice(["conjunction_chain", "disjunction_chain"])
        else:
            available_templates = ["implication"]
            if description_capacity >= 3:
                available_templates.extend(["conjunction_chain", "disjunction_chain"])
            template = rng.choice(available_templates)
        result = _build_propositional(
            names_pool=selected_names,
            actions_pool=actions_pool,
            rng=rng,
            template=template,
            allow_spoken_mode=allow_spoken_mode,
        )

    result["spoken_mode"] = allow_spoken_mode
    options = result["options"]
    if len(options) != TRANSLATION_WRONG_OPTIONS + 1 or sum(
        1 for option in options if option["is_correct"]
    ) != 1:
        raise RuntimeError("Postcondizione fallita per le opzioni della domanda")
    if len({option["formula"] for option in options}) != len(options):
        raise RuntimeError("Postcondizione fallita: le opzioni devono essere tutte distinte")
    if subtype == "propositional" and any(
        "x" in option["formula"] or "forall(" in option["formula"] or "exists(" in option["formula"]
        for option in options
    ):
        raise RuntimeError("Postcondizione fallita: formula proposizionale non valida")

    result["metadata"]["seed"] = seed
    result["metadata"]["people_count"] = people_count
    result["metadata"]["actual_people_count"] = len(
        result["metadata"].get("names_used") or result["metadata"].get("predicate_symbols_used") or []
    )
    ensure_keys(result, ["type", "subtype", "question_text", "info", "options", "metadata"])
    return result
