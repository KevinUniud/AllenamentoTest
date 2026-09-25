from __future__ import annotations

import math
import random
import time

# Serializzazione output e utilita numeriche/temporali per campionamento.
from collections import Counter
from collections.abc import Callable, Sequence

# Tipi usati nelle firme pubbliche e nei callback interni.
from typing import Any, cast

# Nodi AST logici per trasformazioni e riscritture locali.
from .ast_logic import And, Iff, Imp, Not, Or, Var

# Import shared constants
from .constants import (
    DEFAULT_FORMULA_SAMPLE_LIMIT,
    DEFAULT_VARIABLES,
    FORMULA_FETCH_CACHE_MAX,
    FORMULA_HEADS,
    FORMULA_REPETITION_PROBABILITY,
    MAX_AUTOMATIC_TRANSFORM_CYCLES,
    MAX_BINARY_OPERATORS,
    MAX_CONSECUTIVE_NEGATIONS,
    MAX_FORMULA_ATOM_REPETITIONS,
    MAX_GENERATOR_VARIABLES,
    MAX_SAFE_USE_ALL_SPACE,
    MAX_SPOKEN_NESTED_NEGATIONS,
    MIN_FORMULA_ATOM_REPETITION_DISTANCE,
)
from .formula_construction import build_construction_trace
from .metrics import (
    formula_atom_count,
    formula_binary_operator_count,
    formula_depth,
    formula_size,
)

# Bridge Prolog e utility di conversione usate dal generatore.
from .prolog_bridge import PrologBridge, collect_variables, from_prolog, get_default_bridge, to_prolog
from .questions.equivalence import _pick_modified as _pick_modified
from .questions.equivalence import _pick_wrongs as _pick_wrongs
from .questions.equivalence import build_ex_depth as build_ex_depth
from .questions.equivalence import build_exercise as build_exercise
from .questions.logical_consequence import (
    build_logical_consequence_question as build_logical_consequence_question,
)
from .questions.translation import build_translation_question as build_translation_question
from .questions.truth_value import build_tvq as build_tvq
from .validation import (
    GenerationDeadlineExceeded,
)
from .validation import (
    default_vars as _default_vars,
)
from .validation import (
    depth_from_var_count as _depth_from_var_count,
)
from .validation import (
    ensure_keys as _ensure_keys,
)
from .validation import (
    require_int_at_least as _req_int_ge,
)
from .validation import (
    resolve_depth as _resolve_depth,
)
from .validation import (
    to_json_string as _to_json_string,
)

# Cache leggera in-process per evitare round-trip Prolog ripetuti
# su stesse tuple (depth, vars, mode) durante piu generazioni consecutive.
_FORMULA_FETCH_CACHE: dict[tuple[str, int, tuple[str, ...], bool, int], tuple[str, ...]] = {}

_MIN_CACHEABLE_FORMULA_POOL = DEFAULT_FORMULA_SAMPLE_LIMIT


def _uses_vars(formula: Any, variables: Sequence[str]) -> bool:
    """Controlla se la formula candidata usa esattamente le variabili richieste."""
    expr = _as_ast(formula)
    return sorted(collect_variables(expr)) == sorted(variables)


def _rename_vars(formula: Any, mapping: dict[str, str]) -> str:
    """Applica una mappa di rinomina variabili e restituisce testo Prolog."""
    expr = _as_ast(formula)

    def renamed(node):
        if isinstance(node, Var):
            return Var(mapping.get(node.name, node.name))
        if isinstance(node, Not):
            return Not(renamed(node.expr))
        if isinstance(node, And):
            return And(renamed(node.left), renamed(node.right))
        if isinstance(node, Or):
            return Or(renamed(node.left), renamed(node.right))
        if isinstance(node, Imp):
            return Imp(renamed(node.left), renamed(node.right))
        if isinstance(node, Iff):
            return Iff(renamed(node.left), renamed(node.right))
        return node

    return to_prolog(renamed(expr))


def _permute_vars(
    formulas: Sequence[str],
    variables: Sequence[str],
    rng: random.Random,
) -> list[str]:
    """Permuta casualmente i nomi variabile per ridurre bias di denominazione."""
    if len(variables) <= 1:
        return list(formulas)

    source = list(variables)
    renamed: list[str] = []
    for formula in formulas:
        target = list(variables)
        rng.shuffle(target)

        # Evita la mappatura identita per ridurre bias sistematici nei nomi
        # variabile e usa una permutazione indipendente per ogni candidata.
        if target == source:
            target = target[1:] + target[:1]

        mapping = dict(zip(source, target, strict=False))
        renamed.append(_rename_vars(formula, mapping))
    return list(dict.fromkeys(renamed))


def _flatten_associative(node, op_cls):
    """Appiattisce operatori associativi annidati (and/or) in una lista di termini."""
    if isinstance(node, op_cls):
        return _flatten_associative(node.left, op_cls) + _flatten_associative(node.right, op_cls)
    return [node]


def _build_balanced(terms: list[Any], op_cls, rng: random.Random):
    """Ricostruisce un albero binario bilanciato da una lista di termini."""
    if len(terms) == 1:
        return terms[0]

    split = rng.randint(1, len(terms) - 1)
    left = _build_balanced(terms[:split], op_cls, rng)
    right = _build_balanced(terms[split:], op_cls, rng)
    return op_cls(left, right)


def _scatter_vars(formulas: Sequence[str], rng: random.Random) -> list[str]:
    """Mescola blocchi associativi per diversificare le strutture delle formule."""

    def transform(node):
        if isinstance(node, Var):
            return node
        if isinstance(node, Not):
            return Not(transform(node.expr))
        if isinstance(node, Imp):
            return Imp(transform(node.left), transform(node.right))
        if isinstance(node, Iff):
            left = transform(node.left)
            right = transform(node.right)
            if rng.random() < 0.5:
                left, right = right, left
            return Iff(left, right)
        if isinstance(node, (And, Or)):
            op_cls = type(node)
            terms = [transform(term) for term in _flatten_associative(node, op_cls)]
            rng.shuffle(terms)
            return _build_balanced(terms, op_cls, rng)
        return node

    scattered: list[str] = []
    for formula in formulas:
        ast = _as_ast(formula)
        scattered.append(to_prolog(transform(ast)))
    return list(dict.fromkeys(scattered))


def _formula_head(formula: Any) -> str:
    """Estrae l operatore principale di una formula."""
    prolog_formula = _as_prolog(formula).strip()
    if "(" not in prolog_formula:
        return "var"
    return prolog_formula.split("(", 1)[0]


def _formula_truth_signature(formula: Any, variables: Sequence[str]) -> int:
    """Codifica la tavola di verita in un intero, senza interrogare Prolog."""
    expr = _as_ast(formula)
    row_count = 1 << len(variables)
    universe = (1 << row_count) - 1
    variable_masks: dict[str, int] = {}

    for variable_index, variable in enumerate(variables):
        value_bit = 1 << (len(variables) - variable_index - 1)
        variable_masks[variable] = sum(
            1 << row_index for row_index in range(row_count) if row_index & value_bit
        )

    def evaluate(node: Any) -> int:
        if isinstance(node, Var):
            return variable_masks[node.name]
        if isinstance(node, Not):
            return universe ^ evaluate(node.expr)
        if isinstance(node, And):
            return evaluate(node.left) & evaluate(node.right)
        if isinstance(node, Or):
            return evaluate(node.left) | evaluate(node.right)
        if isinstance(node, Imp):
            return (universe ^ evaluate(node.left)) | evaluate(node.right)
        if isinstance(node, Iff):
            return universe ^ (evaluate(node.left) ^ evaluate(node.right))
        raise TypeError(f"Nodo formula non supportato: {type(node).__name__}")

    return evaluate(expr)


def _semantic_formula_order(formulas: Sequence[str], variables: Sequence[str]) -> list[str]:
    """Ordina un rappresentante per classe semantica alternando gli operatori.

    L'ordine e intenzionalmente deterministico: seed consecutivi possono cosi
    attraversare classi di verita diverse senza il tasso di collisioni tipico
    di estrazioni casuali indipendenti.
    """
    if len(variables) > 8:
        return list(dict.fromkeys(formulas))

    seen_signatures: set[int] = set()
    buckets: dict[str, list[str]] = {}
    for formula in formulas:
        signature = _formula_truth_signature(formula, variables)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        buckets.setdefault(_formula_head(formula), []).append(formula)

    preferred_heads = [head for head in FORMULA_HEADS if head in buckets]
    preferred_heads.extend(sorted(set(buckets) - set(preferred_heads)))
    ordered: list[str] = []
    while True:
        progressed = False
        for head in preferred_heads:
            if not buckets[head]:
                continue
            ordered.append(buckets[head].pop(0))
            progressed = True
        if not progressed:
            return ordered


def _formula_is_spoken_friendly(
    expr: Any,
    max_nested_negations: int = MAX_SPOKEN_NESTED_NEGATIONS,
) -> bool:
    """Verifica se la formula può essere resa in forma parlata.

    Accetta le varianti con `not`, `and`, `or`, `imp`, `iff`, ma limita le
    negazioni annidate lungo ogni ramo: il renderer parlato non deve ripetere
    consecutivamente la locuzione associata alla negazione.
    """
    ast = _as_ast(expr)
    if _has_excessive_negation_chain(ast) or _has_excessive_spoken_negation_nesting(
        ast,
        max_nested=max_nested_negations,
    ):
        return False

    def walk(node: Any) -> bool:
        if isinstance(node, Var):
            return True
        if isinstance(node, Not):
            return walk(node.expr)
        if isinstance(node, (And, Or, Imp, Iff)):
            return walk(node.left) and walk(node.right)
        return False

    return walk(ast)


def _has_excessive_spoken_negation_nesting(
    expr: Any,
    max_nested: int = MAX_SPOKEN_NESTED_NEGATIONS,
) -> bool:
    """Rileva troppe negazioni lungo uno stesso ramo della formula parlata.

    Il renderer testuale legge per prima la foglia sinistra e omette le
    parentesi. Di conseguenza ``not(not(or(not(p),q)))`` viene pronunciata
    iniziando con tre occorrenze consecutive di "non e vero che", anche se
    nell'AST nessuna catena di nodi ``Not`` supera lunghezza due. Contare le
    negazioni annidate lungo ogni cammino radice-foglia copre anche il
    riordinamento successivo dei figli commutativi usato nella presentazione.
    """
    if max_nested < 0:
        raise ValueError("max_nested deve essere >= 0")

    ast = _as_ast(expr)

    def walk(node: Any, nested: int = 0) -> bool:
        if isinstance(node, Var):
            return nested > max_nested
        if isinstance(node, Not):
            return walk(node.expr, nested + 1)
        if isinstance(node, (And, Or, Imp, Iff)):
            return walk(node.left, nested) or walk(node.right, nested)
        raise TypeError(f"Tipo formula non supportato: {type(node)!r}")

    return walk(ast)


def _has_excessive_negation_chain(
    expr: Any,
    max_consecutive: int = MAX_CONSECUTIVE_NEGATIONS,
) -> bool:
    """Rileva catene di ``not`` troppo lunghe per una formula didattica.

    La doppia negazione resta disponibile come legge logica esplicita, mentre
    tre o piu negazioni adiacenti rendono inutilmente difficile sia la lettura
    simbolica sia quella in linguaggio naturale.
    """
    if max_consecutive < 0:
        raise ValueError("max_consecutive deve essere >= 0")

    ast = _as_ast(expr)

    def walk(node: Any, consecutive: int = 0) -> bool:
        if isinstance(node, Var):
            return False
        if isinstance(node, Not):
            consecutive += 1
            return consecutive > max_consecutive or walk(node.expr, consecutive)
        if isinstance(node, (And, Or, Imp, Iff)):
            return walk(node.left) or walk(node.right)
        raise TypeError(f"Tipo formula non supportato: {type(node)!r}")

    return walk(ast)


def _has_operator_diversity(formulas: Sequence[str], minimum_distinct_heads: int = 2) -> bool:
    """Verifica che l insieme di formule includa abbastanza operatori principali distinti."""
    if minimum_distinct_heads <= 1:
        return True
    heads = {_formula_head(formula) for formula in formulas}
    return len(heads) >= minimum_distinct_heads


def _pick_by_head(
    formulas: Sequence[str],
    rng: random.Random,
    *,
    prefer_or: bool = False,
) -> str:
    """Seleziona una formula con strategia casuale bilanciata per operatore."""
    buckets: dict[str, list[str]] = {}
    for formula in formulas:
        buckets.setdefault(_formula_head(formula), []).append(formula)

    available_heads = [head for head, items in buckets.items() if items]
    if not available_heads:
        raise RuntimeError("Nessuna formula disponibile")

    # Piccolo boost opzionale per OR su formule grandi, dove si percepisce
    # piu facilmente uno sbilanciamento verso AND.
    weighted_heads: list[str] = []
    for head in available_heads:
        weight = 2 if (prefer_or and head == "or") else 1
        weighted_heads.extend([head] * weight)

    selected_head = rng.choice(weighted_heads)
    return rng.choice(buckets[selected_head])


def _pick_formula_with_repetition_policy(
    formulas: Sequence[str],
    rng: random.Random,
    *,
    variables: Sequence[str],
    prefer_or: bool = False,
    repetition_probability: float = FORMULA_REPETITION_PROBABILITY,
    max_repetitions: int = MAX_FORMULA_ATOM_REPETITIONS,
) -> str:
    """Seleziona una formula applicando la policy di ripetizione su singolo trial."""
    selected = _select_formulas_with_repetition_policy(
        formulas,
        count=1,
        rng=rng,
        variables=variables,
        prefer_or=prefer_or,
        repetition_probability=repetition_probability,
        max_repetitions=max_repetitions,
    )
    return selected[0]


def _select_formulas_with_repetition_policy(
    formulas: Sequence[str],
    count: int,
    rng: random.Random,
    *,
    variables: Sequence[str] | None = None,
    prefer_or: bool = False,
    repetition_probability: float = FORMULA_REPETITION_PROBABILITY,
    max_repetitions: int = MAX_FORMULA_ATOM_REPETITIONS,
) -> list[str]:
    """Seleziona N formule con trial indipendenti sulla presenza di ripetizioni."""
    _req_int_ge("count", count, 1)

    filtered_formulas = [
        formula for formula in dict.fromkeys(formulas) if _formula_atom_repetition_count(formula) <= max_repetitions
    ]
    if variables is not None:
        matching_variables = [formula for formula in filtered_formulas if _uses_vars(formula, variables)]
        if matching_variables:
            filtered_formulas = matching_variables

    if len(filtered_formulas) < count:
        raise RuntimeError(
            f"Nessuna formula valida disponibile: richieste {count}, disponibili {len(filtered_formulas)}"
        )

    repeated_formulas = [formula for formula in filtered_formulas if _formula_has_non_banal_repetitions(formula)]
    unique_formulas = [formula for formula in filtered_formulas if _formula_atom_repetition_count(formula) == 0]

    selected: list[str] = []
    used: set[str] = set()

    def choose_from(pool: Sequence[str]) -> str | None:
        available = [item for item in pool if item not in used]
        if not available:
            return None
        return _pick_by_head(available, rng, prefer_or=prefer_or)

    for _ in range(count):
        wants_repetitions = rng.random() < repetition_probability
        primary_pool = repeated_formulas if wants_repetitions else unique_formulas
        secondary_pool = unique_formulas if wants_repetitions else repeated_formulas

        chosen = choose_from(primary_pool)
        if chosen is None:
            chosen = choose_from(secondary_pool)

        if chosen is None and wants_repetitions and variables is not None:
            base_formula = choose_from(unique_formulas)
            if base_formula is not None:
                repeated_formula = _introduce_atom_repetitions(
                    base_formula,
                    rng,
                    variables=variables,
                    max_repetitions=max_repetitions,
                )
                if repeated_formula is not None and repeated_formula not in used:
                    chosen = repeated_formula

        # Se nessuno dei due rami e disponibile, usa l'intero pool valido.
        if chosen is None:
            chosen = choose_from(filtered_formulas)

        if chosen is None:
            break

        used.add(chosen)
        selected.append(chosen)

    if len(selected) < count:
        raise RuntimeError(f"Nessuna formula valida disponibile: richieste {count}, selezionate {len(selected)}")

    return selected


def _diversify_sample(formulas: Sequence[str], limit: int, rng: random.Random) -> list[str]:
    """Costruisce un campione diversificato bilanciato tra operatori principali."""
    unique_formulas = list(dict.fromkeys(formulas))
    buckets: dict[str, list[str]] = {}

    for formula in unique_formulas:
        head = _formula_head(formula)
        buckets.setdefault(head, []).append(formula)

    heads = list(buckets.keys())
    rng.shuffle(heads)

    for head in heads:
        rng.shuffle(buckets[head])

    balanced: list[str] = []
    while len(balanced) < limit:
        progressed = False
        for head in heads:
            if not buckets[head]:
                continue
            balanced.append(buckets[head].pop())
            progressed = True
            if len(balanced) >= limit:
                break
        if not progressed:
            break

    return balanced


def _get_formulas(
    *,
    bridge: PrologBridge,
    depth: int,
    variables: Sequence[str],
    use_all: bool,
    timeout: int,
    rng: random.Random,
    max_binary_operators: int = MAX_BINARY_OPERATORS,
    semantic_slot: int | None = None,
    spoken_negation_limit: int | None = None,
) -> list[str]:
    """Recupera formule candidate per profondita/variabili con fallback progressivi."""
    # Per collegare N variabili distinte servono almeno N - 1 nodi binari.
    # Evita round-trip Prolog costosi quando i filtri renderebbero comunque
    # vuoto l'intero risultato (caso frequente nei distractor brevi).
    if len(set(variables)) > max_binary_operators + 1:
        return []

    cache_key: tuple[str, int, tuple[str, ...], bool, int] | None = None
    filtered_formulas: list[str] | None = None
    if isinstance(bridge, PrologBridge):
        cache_key = (bridge.__class__.__name__, depth, tuple(variables), use_all, max_binary_operators)
        cached = _FORMULA_FETCH_CACHE.get(cache_key)
        if cached is not None:
            filtered_formulas = list(cached)

    if filtered_formulas is None:
        started = time.monotonic()
        deadline = started + float(timeout)
        fetch_errors: list[Exception] = []

        def ensure_within_deadline() -> None:
            if time.monotonic() >= deadline:
                raise GenerationDeadlineExceeded("Tempo complessivo di generazione formule esaurito")

        def safe_fetch(callable_fn, *args, requested_timeout: int, **kwargs):
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                raise GenerationDeadlineExceeded("Tempo complessivo di generazione formule esaurito")
            effective_timeout = max(1, min(requested_timeout, math.ceil(remaining_seconds)))
            try:
                result = callable_fn(*args, timeout=effective_timeout, **kwargs)
            except GenerationDeadlineExceeded:
                raise
            except Exception as exc:
                fetch_errors.append(exc)
                if time.monotonic() >= deadline:
                    raise GenerationDeadlineExceeded(
                        "Tempo complessivo di generazione formule esaurito"
                    ) from exc
                return []
            ensure_within_deadline()
            return result

        formulas: list[str]
        if use_all:
            estimated_space = _formula_space_upper_bound(depth, len(variables))
            if estimated_space > MAX_SAFE_USE_ALL_SPACE:
                raise ValueError(
                    "use_all richiederebbe di materializzare uno spazio combinatorio "
                    f"superiore a {MAX_SAFE_USE_ALL_SPACE} formule; usare use_all=false"
                )
            if hasattr(bridge, "all_depth_allvars"):
                formulas = safe_fetch(
                    bridge.all_depth_allvars,
                    depth,
                    list(variables),
                    requested_timeout=timeout,
                )
            else:
                formulas = safe_fetch(
                    bridge.all_depth,
                    depth,
                    list(variables),
                    requested_timeout=timeout,
                )
        else:
            formulas = []
            tight_timeout = timeout <= 1
            per_head_limit = (
                DEFAULT_FORMULA_SAMPLE_LIMIT
                if tight_timeout
                else max(32, DEFAULT_FORMULA_SAMPLE_LIMIT * 4)
            )
            per_head_timeout = 1
            generic_fetch_timeout = max(1, min(timeout, 2))
            max_vars_below_root = 0 if depth <= 0 else 2 ** (depth - 1)
            heads = [
                head
                for head in FORMULA_HEADS
                if head != "not" or len(variables) <= max_vars_below_root
            ]
            target_pool_size = (
                DEFAULT_FORMULA_SAMPLE_LIMIT * min(len(heads), 4)
                if tight_timeout
                else max(DEFAULT_FORMULA_SAMPLE_LIMIT * 4, len(heads) * per_head_limit)
            )
            head_sampling_deadline = min(deadline, started + min(float(timeout), 3.0))

            # Il recupero deve restare indipendente dal seed. Altrimenti il
            # primo accesso consuma RNG che il successivo accesso in cache non
            # consuma e lo stesso seed produce due risultati diversi.
            if hasattr(bridge, "some_depth_head"):
                for head in heads:
                    if time.monotonic() >= head_sampling_deadline or len(formulas) >= target_pool_size:
                        break
                    formulas.extend(
                        safe_fetch(
                            bridge.some_depth_head,
                            depth,
                            list(variables),
                            head=head,
                            limit=per_head_limit,
                            requested_timeout=per_head_timeout,
                        )
                    )

            # Integra con formule bilanciate, mantenendo anche qui un ordine
            # stabile e lo stesso deadline globale.
            if depth >= 2 and hasattr(bridge, "some_depth_hbal"):
                for head in ("or", "and", "iff"):
                    if time.monotonic() >= head_sampling_deadline or len(formulas) >= target_pool_size:
                        break
                    formulas.extend(
                        safe_fetch(
                            bridge.some_depth_hbal,
                            depth,
                            list(variables),
                            head=head,
                            limit=per_head_limit,
                            requested_timeout=per_head_timeout,
                        )
                    )

            # Riempi la capacita residua solo se il budget globale non e
            # scaduto; ogni chiamata riceve il tempo effettivamente restante.
            remaining = max(0, target_pool_size - len(formulas))
            if remaining > 0 and time.monotonic() < deadline:
                if hasattr(bridge, "some_depth_allvars"):
                    formulas.extend(
                        safe_fetch(
                            bridge.some_depth_allvars,
                            depth,
                            list(variables),
                            limit=remaining,
                            requested_timeout=generic_fetch_timeout,
                        )
                    )
                elif hasattr(bridge, "some_depth"):
                    formulas.extend(
                        safe_fetch(
                            bridge.some_depth,
                            depth,
                            list(variables),
                            limit=remaining,
                            requested_timeout=generic_fetch_timeout,
                        )
                    )
                else:
                    formulas.extend(
                        safe_fetch(
                            bridge.formula_of_depth,
                            depth,
                            list(variables),
                            requested_timeout=generic_fetch_timeout,
                        )
                    )

        if not formulas and fetch_errors:
            # Un errore del motore (incluso un timeout locale) non equivale
            # a uno spazio di formule matematicamente vuoto.
            raise fetch_errors[-1]

        filtered_formulas = list(
            dict.fromkeys(
                formula
                for formula in formulas
                if _uses_vars(formula, variables)
                and not _has_excessive_negation_chain(formula)
                and _has_valid_binary_operator_count(_as_ast(formula), max_binary_operators)
            )
        )
        ensure_within_deadline()

        # Non conservare pool vuoti, insufficienti o enumerazioni
        # potenzialmente molto grandi. Il pool puo comunque essere riusato se
        # altri fallback hanno raccolto un insieme ampio nonostante il guasto
        # di una singola query per-head.
        cached_head_count = len({_formula_head(formula) for formula in filtered_formulas})
        cache_is_complete = (
            not use_all
            and timeout > 1
            and len(filtered_formulas) >= _MIN_CACHEABLE_FORMULA_POOL
            and not fetch_errors
            and cached_head_count >= min(3, len(heads))
        )
        if cache_key is not None and cache_is_complete:
            if len(_FORMULA_FETCH_CACHE) >= FORMULA_FETCH_CACHE_MAX:
                _FORMULA_FETCH_CACHE.pop(next(iter(_FORMULA_FETCH_CACHE)))
            _FORMULA_FETCH_CACHE[cache_key] = tuple(filtered_formulas)

    # Applica la policy anche ai pool gia presenti in memoria: durante un
    # reload applicativo una cache costruita da una versione precedente non
    # deve poter reintrodurre catene di negazioni ormai non ammesse.
    filtered_formulas = [
        formula
        for formula in filtered_formulas
        if not _has_excessive_negation_chain(formula)
        and (
            spoken_negation_limit is None
            or _formula_is_spoken_friendly(
                formula,
                max_nested_negations=spoken_negation_limit,
            )
        )
    ]

    if semantic_slot is not None:
        semantic_formulas = _semantic_formula_order(filtered_formulas, variables)
        if semantic_formulas:
            return [semantic_formulas[semantic_slot % len(semantic_formulas)]]

    # L'ordine di enumerazione Prolog e deterministico e puo introdurre bias
    # sui nomi (es. 'a' ricorre spesso sotto lo stesso operatore). Permuta
    # casualmente le etichette variabile prima della selezione finale.
    if isinstance(bridge, PrologBridge):
        filtered_formulas = _permute_vars(filtered_formulas, variables, rng)
        filtered_formulas = _scatter_vars(filtered_formulas, rng)

    if use_all:
        return filtered_formulas

    return _diversify_sample(filtered_formulas, DEFAULT_FORMULA_SAMPLE_LIMIT, rng)


def _formula_space_upper_bound(depth: int, variable_count: int) -> int:
    """Stima prudente dello spazio enumerato da ``all_depth``.

    Il conteggio sovrastima intenzionalmente operatori commutativi e formule
    duplicate. I valori vengono saturati appena oltre il limite di sicurezza,
    evitando a sua volta interi enormi per profondita elevate.
    """
    current = max(1, variable_count)
    cumulative = current
    saturation = MAX_SAFE_USE_ALL_SPACE + 1

    for _ in range(depth):
        previous_cumulative = cumulative - current
        binary_pairs = cumulative * cumulative - previous_cumulative * previous_cumulative
        current = min(saturation, current + 4 * binary_pairs)
        cumulative = min(saturation, cumulative + current)
        if current >= saturation:
            return saturation

    return current


def _has_valid_binary_operator_count(expr, max_operators: int = MAX_BINARY_OPERATORS) -> bool:
    """Verifica che la formula non abbia più del numero massimo di operatori binari."""
    return formula_binary_operator_count(expr) <= max_operators


def _formula_atom_repetition_count(expr) -> int:
    """Conta quante occorrenze ripetute di atomi sono presenti nella formula."""
    atom_counts: Counter[str] = Counter()

    def walk(node) -> None:
        if isinstance(node, Var):
            atom_counts[node.name] += 1
            return
        if isinstance(node, Not):
            walk(node.expr)
            return
        if isinstance(node, (And, Or, Imp, Iff)):
            walk(node.left)
            walk(node.right)
            return
        raise TypeError(f"Tipo formula non supportato: {type(node)!r}")

    walk(_as_ast(expr))
    return sum(count - 1 for count in atom_counts.values() if count > 1)


def _leaf_path_distance(left_path: tuple[str, ...], right_path: tuple[str, ...]) -> int:
    """Calcola la distanza strutturale tra due foglie dell'albero AST."""
    shared_prefix = 0
    for left_step, right_step in zip(left_path, right_path, strict=False):
        if left_step != right_step:
            break
        shared_prefix += 1
    return len(left_path) + len(right_path) - (2 * shared_prefix)


def _formula_has_non_banal_repetitions(
    expr,
    min_distance: int = MIN_FORMULA_ATOM_REPETITION_DISTANCE,
) -> bool:
    """Verifica che eventuali ripetizioni abbiano un distacco minimo nell'albero."""
    leaf_paths = _collect_variable_leaf_paths(expr)
    by_atom: dict[str, list[tuple[str, ...]]] = {}
    for path, atom_name in leaf_paths:
        by_atom.setdefault(atom_name, []).append(path)

    has_repetition = False
    for paths in by_atom.values():
        if len(paths) < 2:
            continue
        has_repetition = True
        for index, left_path in enumerate(paths):
            for right_path in paths[index + 1 :]:
                if _leaf_path_distance(left_path, right_path) < min_distance:
                    return False

    return has_repetition


def _collect_variable_leaf_paths(expr) -> list[tuple[tuple[str, ...], str]]:
    """Raccoglie i percorsi delle foglie variabile in una formula AST."""
    ast = _as_ast(expr)
    leaf_paths: list[tuple[tuple[str, ...], str]] = []

    def walk(node, path: tuple[str, ...]) -> None:
        if isinstance(node, Var):
            leaf_paths.append((path, node.name))
            return
        if isinstance(node, Not):
            walk(node.expr, (*path, "expr"))
            return
        if isinstance(node, (And, Or, Imp, Iff)):
            walk(node.left, (*path, "left"))
            walk(node.right, (*path, "right"))
            return
        raise TypeError(f"Tipo formula non supportato: {type(node)!r}")

    walk(ast, ())
    return leaf_paths


def _rewrite_variable_leaves(expr, replacements: dict[tuple[str, ...], str]):
    """Sostituisce foglie variabile selezionate mantenendo invariata la struttura."""
    ast = _as_ast(expr)

    def walk(node, path: tuple[str, ...]):
        if isinstance(node, Var):
            target_name = replacements.get(path)
            return Var(target_name) if target_name is not None else node
        if isinstance(node, Not):
            return Not(walk(node.expr, (*path, "expr")))
        if isinstance(node, And):
            return And(walk(node.left, (*path, "left")), walk(node.right, (*path, "right")))
        if isinstance(node, Or):
            return Or(walk(node.left, (*path, "left")), walk(node.right, (*path, "right")))
        if isinstance(node, Imp):
            return Imp(walk(node.left, (*path, "left")), walk(node.right, (*path, "right")))
        if isinstance(node, Iff):
            return Iff(walk(node.left, (*path, "left")), walk(node.right, (*path, "right")))
        raise TypeError(f"Tipo formula non supportato: {type(node)!r}")

    return walk(ast, ())


def _introduce_atom_repetitions(
    formula: Any,
    rng: random.Random,
    variables: Sequence[str] | None = None,
    max_repetitions: int = MAX_FORMULA_ATOM_REPETITIONS,
):
    """Prova a introdurre ripetizioni controllate di atomi in una formula."""
    ast = _as_ast(formula)
    current_repetitions = _formula_atom_repetition_count(ast)
    if current_repetitions > max_repetitions:
        return None
    if current_repetitions > 0:
        return to_prolog(ast) if _formula_has_non_banal_repetitions(ast) else None

    leaf_paths = _collect_variable_leaf_paths(ast)
    if len(leaf_paths) < 2:
        return None

    unique_atom_names = list(dict.fromkeys(atom_name for _, atom_name in leaf_paths))
    if len(unique_atom_names) < 2:
        return None

    atom_counts = Counter(atom_name for _, atom_name in leaf_paths)
    rng.shuffle(unique_atom_names)
    budget = max_repetitions - current_repetitions

    for target_name in unique_atom_names:
        # Sostituiamo solo foglie di atomi che rimangono comunque presenti,
        # cosi non perdiamo variabili richieste.
        available_paths = [
            path for path, atom_name in leaf_paths if atom_name != target_name and atom_counts[atom_name] > 1
        ]
        if not available_paths:
            continue

        rng.shuffle(available_paths)
        selected_paths = available_paths[:budget]
        if not selected_paths:
            continue

        transformed = _rewrite_variable_leaves(
            ast,
            {path: target_name for path in selected_paths},
        )
        transformed_prolog = to_prolog(transformed)
        if variables is not None and not _uses_vars(transformed_prolog, variables):
            continue
        if _formula_atom_repetition_count(transformed) <= max_repetitions and _formula_has_non_banal_repetitions(
            transformed
        ):
            return transformed_prolog

    return None


def formula_metadata(expr) -> dict:
    """Costruisce i metadati (variabili/profondita/dimensione/prolog) di una formula."""
    data = {
        "variables": sorted(collect_variables(expr)),
        "depth": formula_depth(expr),
        "size": formula_size(expr),
        "formula_prolog": to_prolog(expr),
    }
    _ensure_keys(data, ["variables", "depth", "size", "formula_prolog"])
    return data


def formula_payload(expr, **extra) -> dict:
    """Costruisce un payload serializzabile minimale per una formula."""
    payload = {
        "formula_prolog": to_prolog(expr),
    }
    payload.update(extra)
    _ensure_keys(payload, ["formula_prolog"])
    return payload


def _ensure_bridge(bridge: PrologBridge | None = None) -> PrologBridge:
    """Restituisce il bridge fornito o crea pigramente quello di default."""
    return bridge or get_default_bridge()


def _safe_bridge_call(fn: Callable[..., object], *args, **kwargs) -> list[str]:
    """Esegue una chiamata bridge restituendo sempre una lista o fallback vuoto."""
    try:
        result = fn(*args, **kwargs)
    except Exception:
        return []
    return result if isinstance(result, list) else []


def _operator_cycle_count(formula: Any, rng: random.Random, max_cycles: int | None = None) -> int:
    """Sceglie un numero di cicli compreso tra meta e massimo delle trasformazioni disponibili."""
    atom_count = formula_atom_count(_as_ast(formula))
    if atom_count <= 0:
        return 0

    automatic_max = min(MAX_AUTOMATIC_TRANSFORM_CYCLES, max(1, atom_count * 2))
    upper_bound = automatic_max if max_cycles is None else min(automatic_max, max_cycles)
    upper_bound = max(1, upper_bound)
    lower_bound = max(1, math.ceil(upper_bound / 2))
    return rng.randint(lower_bound, upper_bound)


def _as_prolog(expr: Any) -> str:
    """Converte l input formula nel formato stringa Prolog."""
    return expr if isinstance(expr, str) else to_prolog(expr)


def _as_ast(expr: Any):
    """Converte l input formula in AST quando necessario."""
    return from_prolog(expr) if isinstance(expr, str) else expr


def _scramble_commutative_formula(expr: Any, rng: random.Random) -> Any:
    """Rimescola ricorsivamente i figli di and/or senza cambiare il significato."""
    ast = _as_ast(expr)

    def transform(node: Any) -> Any:
        if isinstance(node, Var):
            return node
        if isinstance(node, Not):
            return Not(transform(node.expr))
        if isinstance(node, Imp):
            return Imp(transform(node.left), transform(node.right))
        if isinstance(node, Iff):
            left = transform(node.left)
            right = transform(node.right)
            if rng.random() < 0.5:
                left, right = right, left
            return Iff(left, right)
        if isinstance(node, (And, Or)):
            op_cls = type(node)
            terms = [transform(term) for term in _flatten_associative(node, op_cls)]
            rng.shuffle(terms)
            return _build_balanced(terms, op_cls, rng)
        return node

    return transform(ast)


def _scramble_formula_prolog(formula: Any, rng: random.Random) -> str:
    """Restituisce una formula Prolog con and/or rimescolati quando possibile."""
    return to_prolog(_scramble_commutative_formula(formula, rng))


def _to_spoken_string(formula: Any, rng: random.Random | None = None) -> str:
    """Return the Prolog string for the formula even when spoken requested.

    Historically this rendered a human-friendly "spoken" representation
    (e.g. 'p and q'), but callers expect a Prolog term when `allow_spoken_mode`
    is used. To preserve that contract we return a Prolog-formatted string.
    If `rng` is provided we apply the commutative scramble used elsewhere.
    """
    if rng is None:
        return _as_prolog(formula)
    return _scramble_formula_prolog(formula, rng)


def _formula_entry(expr: Any, *, rng: random.Random | None = None, **extra) -> dict:
    """Crea una voce formula standardizzata per le risposte API."""
    materialized = _as_ast(expr) if rng is None else _scramble_commutative_formula(expr, rng)
    return formula_payload(
        materialized,
        construction=build_construction_trace(materialized),
        **extra,
    )


def _has_atom_count(formula: Any, target_atom_count: int | None) -> bool:
    """Verifica l uguaglianza del numero di atomi quando richiesto."""
    if target_atom_count is None:
        return True
    return formula_atom_count(_as_ast(formula)) == target_atom_count


def _has_adjacent_duplicate_atoms(formula: Any) -> bool:
    """Rileva occorrenze con due atomi uguali come figli diretti dello stesso connettivo binario."""
    ast = _as_ast(formula)

    def walk(node: Any) -> bool:
        if isinstance(node, Var):
            return False
        if isinstance(node, Not):
            return walk(node.expr)
        if isinstance(node, (And, Or, Imp, Iff)):
            if isinstance(node.left, Var) and isinstance(node.right, Var) and node.left.name == node.right.name:
                return True
            return walk(node.left) or walk(node.right)
        raise TypeError(f"Tipo formula non supportato: {type(node)!r}")

    return walk(ast)


def _swap_and_or_rec(node: Any, rng: random.Random, swap_probability: float = 0.5) -> Any:
    """FALLBACK IMPLEMENTATION: Scambia casualmente i figli di and/or mantenendo intatto il resto della formula.

    Note: Prolog swap_and_or_children è preferito quando disponibile. Questa implementazione Python
    esiste solo come fallback se il bridge Prolog non è disponibile o fallisce.
    """
    if isinstance(node, Var):
        return node
    if isinstance(node, Not):
        return Not(_swap_and_or_rec(node.expr, rng, swap_probability))
    if isinstance(node, And):
        left = _swap_and_or_rec(node.left, rng, swap_probability)
        right = _swap_and_or_rec(node.right, rng, swap_probability)
        if rng.random() < swap_probability:
            return And(right, left)
        return And(left, right)
    if isinstance(node, Or):
        left = _swap_and_or_rec(node.left, rng, swap_probability)
        right = _swap_and_or_rec(node.right, rng, swap_probability)
        if rng.random() < swap_probability:
            return Or(right, left)
        return Or(left, right)
    if isinstance(node, Imp):
        return Imp(
            _swap_and_or_rec(node.left, rng, swap_probability),
            _swap_and_or_rec(node.right, rng, swap_probability),
        )
    if isinstance(node, Iff):
        return Iff(
            _swap_and_or_rec(node.left, rng, swap_probability),
            _swap_and_or_rec(node.right, rng, swap_probability),
        )
    return node


def _maybe_swap_and_or(formula: str, rng: random.Random, swap_probability: float = 0.5) -> str:
    """FALLBACK IMPLEMENTATION: Applica opzionalmente swap ai nodi and/or della formula.

    Note: Prolog swap_and_or_children è preferito quando disponibile via _transform_answer_candidates.
    Questa implementazione Python esiste solo come fallback se il bridge Prolog non è disponibile.
    """
    swapped = _swap_and_or_rec(_as_ast(formula), rng, swap_probability)
    return to_prolog(swapped)


def _needs_extra_transformation(formula: str) -> bool:
    """Rileva se la formula richiede una trasformazione aggiuntiva."""
    return _formula_head(formula) in {"imp", "iff", "not"}


def _canonicalize_commutative(node: Any) -> Any:
    """Normalizza and/or/iff ordinando i figli per confronto strutturale."""
    if isinstance(node, Var):
        return node
    if isinstance(node, Not):
        return Not(_canonicalize_commutative(node.expr))
    if isinstance(node, Imp):
        return Imp(_canonicalize_commutative(node.left), _canonicalize_commutative(node.right))
    if isinstance(node, And):
        left = _canonicalize_commutative(node.left)
        right = _canonicalize_commutative(node.right)
        if to_prolog(right) < to_prolog(left):
            left, right = right, left
        return And(left, right)
    if isinstance(node, Or):
        left = _canonicalize_commutative(node.left)
        right = _canonicalize_commutative(node.right)
        if to_prolog(right) < to_prolog(left):
            left, right = right, left
        return Or(left, right)
    if isinstance(node, Iff):
        left = _canonicalize_commutative(node.left)
        right = _canonicalize_commutative(node.right)
        if to_prolog(right) < to_prolog(left):
            left, right = right, left
        return Iff(left, right)
    return node


def _commutative_signature(formula: Any) -> str:
    """Restituisce una firma canonica che collassa anche le inversioni commutative."""
    return to_prolog(_canonicalize_commutative(_as_ast(formula)))


def _is_effective_transformation(original: Any, candidate: Any) -> bool:
    """Verifica che la differenza non sia solo riordinamento commutativo dei figli."""
    original_text = _normalize_formula_text(original)
    candidate_text = _normalize_formula_text(candidate)
    if original_text == candidate_text:
        return False

    original_canonical = to_prolog(_canonicalize_commutative(_as_ast(original)))
    candidate_canonical = to_prolog(_canonicalize_commutative(_as_ast(candidate)))
    return original_canonical != candidate_canonical


def _normalize_formula_text(formula: Any) -> str:
    """Normalizza una formula in testo Prolog senza spazi superflui."""
    return _as_prolog(formula).replace(" ", "")


def _get_orchestrator_module() -> Any | None:
    """Importa l'orchestrator solo quando serve per recuperare le implementazioni reali."""
    try:
        from . import orchestrator

        return orchestrator
    except Exception:
        return None


def _require_pairwise_distinct(formulas: Sequence[Any], context: str) -> None:
    """Verifica che tutte le formule siano diverse tra loro."""
    normalized = [_normalize_formula_text(formula) for formula in formulas]
    if len(set(normalized)) != len(normalized):
        raise RuntimeError(f"Postcondizione fallita: formule non distinte in {context}")


def _transform_answer_candidates(
    *,
    formula: str,
    bridge: PrologBridge,
    rng: random.Random,
    operator_cycles: int | None,
    timeout_provider: Callable[[], int],
) -> list[str]:
    """Compatibilita: delega la selezione dei candidati al livello applicativo."""
    orchestrator_module = _get_orchestrator_module()
    implementation = getattr(orchestrator_module, "_transform_answer_candidates", None) if orchestrator_module else None
    if not callable(implementation):
        raise RuntimeError("Implementazione orchestrator non disponibile")
    return implementation(
        formula=formula,
        bridge=bridge,
        rng=rng,
        operator_cycles=operator_cycles,
        timeout_provider=timeout_provider,
    )


def generate_spoken_ready_prolog(
    formula: Any,
    bridge: PrologBridge | None = None,
    timeout: int = 10,
    try_factor: bool = True,
) -> tuple[str, dict]:
    """Produce una stringa Prolog normalizzata adatta al traduttore parlato esterno.

    Flusso:
    1. to_nnf via Prolog (negazioni spinte agli atomi)
    2. expand_implications via Prolog (eliminiamo imp/iff espandendoli)
    3. ricostruzione AST locale per appiattire and/or e bilanciare l'albero
    4. opzionalmente provare un semplice factoring per reintrodurre un unico imp
    Ritorna (prolog_str, metadata)
    """
    bridge = _ensure_bridge(bridge)
    meta: dict = {"spoken_transformations": [], "spoken_fallback_used": False}

    prolog_in = _as_prolog(formula)

    # 1) to_nnf
    nnf_res = []
    try:
        nnf_res = _safe_bridge_call(bridge.to_nnf, prolog_in, timeout=timeout)
    except Exception:
        nnf_res = []

    if nnf_res:
        nnf = nnf_res[0]
        meta["spoken_transformations"].append("to_nnf")
    else:
        nnf = prolog_in
        meta["spoken_fallback_used"] = True

    # 2) expand_implications
    exp_res = []
    try:
        exp_res = _safe_bridge_call(bridge.expand_implications, nnf, timeout=timeout)
    except Exception:
        exp_res = []

    if exp_res:
        expanded = exp_res[0]
        meta["spoken_transformations"].append("expand_implications")
    else:
        expanded = nnf
        meta["spoken_fallback_used"] = True

    # Convert to AST and apply local appiattimenti
    try:
        ast = _as_ast(expanded)

        def _rebuild_balanced(terms: list[Any], op_cls: type) -> Any:
            if not terms:
                raise ValueError("No terms to rebuild")
            if len(terms) == 1:
                return terms[0]
            mid = len(terms) // 2
            left = _rebuild_balanced(terms[:mid], op_cls)
            right = _rebuild_balanced(terms[mid:], op_cls)
            return op_cls(left, right)

        def _flatten_rebuild(node: Any) -> Any:
            if isinstance(node, Var):
                return node
            if isinstance(node, Not):
                return Not(_flatten_rebuild(node.expr))
            if isinstance(node, (And, Or)):
                op_cls = type(node)
                terms: list[Any] = []

                def collect(n: Any) -> None:
                    if isinstance(n, op_cls):
                        collect(n.left)
                        collect(n.right)
                    else:
                        terms.append(_flatten_rebuild(n))

                collect(node)
                return _rebuild_balanced(terms, op_cls)
            if isinstance(node, Imp):
                return Imp(_flatten_rebuild(node.left), _flatten_rebuild(node.right))
            if isinstance(node, Iff):
                return Iff(_flatten_rebuild(node.left), _flatten_rebuild(node.right))
            return node

        rebuilt = _flatten_rebuild(ast)
        meta["spoken_transformations"].append("flatten_associative")

        # 3) try simple factoring to reintroduce a single implication when possible
        factored: Any | None = None
        if try_factor:
            try:
                if isinstance(rebuilt, Or):
                    left = rebuilt.left
                    right = rebuilt.right
                    # pattern: or(not(A), B)  -> imp(A, B)
                    if isinstance(left, Not) and isinstance(left.expr, (Var, And, Or, Imp, Iff)):
                        factored = Imp(left.expr, right)
                    elif isinstance(right, Not) and isinstance(right.expr, (Var, And, Or, Imp, Iff)):
                        factored = Imp(right.expr, left)
            except Exception:
                factored = None

        if factored is not None:
            result_ast = factored
            meta["spoken_transformations"].append("factored_imp")
        else:
            result_ast = rebuilt

        result_prolog = to_prolog(result_ast)
    except Exception:
        # In case of any local AST handling failure, return the expanded Prolog
        result_prolog = expanded
        meta["spoken_fallback_used"] = True

    return result_prolog, meta


def generate_formula(
    depth: int | None = None,
    variables: Sequence[str] = DEFAULT_VARIABLES,
    use_all: bool = False,
    timeout: int = 10,
    seed: int | None = None,
    bridge: PrologBridge | None = None,
    allow_spoken_mode: bool = False,
):
    """Genera una formula rispettando vincoli di profondita e variabili."""
    _req_int_ge("timeout", int(timeout), 1)
    rng = random.Random(seed)

    depth, variables = _resolve_depth(depth, variables)
    if len(variables) > MAX_GENERATOR_VARIABLES:
        raise ValueError(f"Il generatore supporta al massimo {MAX_GENERATOR_VARIABLES} variabili")
    bridge = _ensure_bridge(bridge)

    # Una formula che contiene tutte le N variabili richieste necessita di
    # almeno N - 1 operatori binari per collegarne le occorrenze. Il limite
    # globale di due operatori resta adatto agli esercizi brevi, ma non deve
    # rendere il pool matematicamente vuoto quando N e maggiore di tre.
    max_binary_operators = max(MAX_BINARY_OPERATORS, len(variables) - 1)

    formulas = _get_formulas(
        bridge=bridge,
        depth=depth,
        variables=variables,
        use_all=use_all,
        timeout=timeout,
        rng=rng,
        max_binary_operators=max_binary_operators,
        semantic_slot=seed if len(variables) == 4 else None,
        # L'endpoint generico alimenta anche il quiz sulla negazione dei
        # quantificatori, che aggiunge un ``not`` esterno. In forma parlata la
        # base deve quindi conservare l'intero budget di negazione per quel
        # passaggio; il percorso simbolico continua invece a usare il pool
        # completo.
        spoken_negation_limit=0 if allow_spoken_mode else None,
    )

    if not formulas:
        raise RuntimeError("Nessuna formula generata che usi tutte le variabili richieste")

    selected = _pick_formula_with_repetition_policy(
        formulas,
        rng,
        variables=variables,
        prefer_or=(len(variables) >= 5),
    )
    if not selected:
        raise RuntimeError("Formula generata non valida")
    if allow_spoken_mode:
        return _to_spoken_string(selected)
    return selected


def generate_formula_json(
    depth: int | None = None,
    variables: Sequence[str] = DEFAULT_VARIABLES,
    use_all: bool = False,
    timeout: int = 10,
    seed: int | None = None,
    bridge: PrologBridge | None = None,
    allow_spoken_mode: bool = False,
) -> dict:
    """Genera una formula e restituisce un payload pronto per JSON."""
    _req_int_ge("timeout", int(timeout), 1)
    resolved_bridge = _ensure_bridge(bridge)
    expr = _as_ast(
        generate_formula(
            depth=depth,
            variables=variables,
            use_all=use_all,
            timeout=timeout,
            seed=seed,
            bridge=resolved_bridge,
            allow_spoken_mode=allow_spoken_mode,
        )
    )
    result = formula_payload(expr, source="prolog_depth")
    if allow_spoken_mode:
        try:
            # Produce a Prolog-normalized form suitable for external spoken translator.
            spoken_prolog, meta = generate_spoken_ready_prolog(
                expr,
                bridge=resolved_bridge,
                timeout=timeout,
            )
            result["spoken_ready_prolog"] = spoken_prolog
            result["spoken_transformations"] = meta.get("spoken_transformations", [])
            result["spoken_fallback_used"] = bool(meta.get("spoken_fallback_used", False))
        except Exception:
            # If anything fails, don't break the JSON wrapper — keep only prolog
            pass
    _ensure_keys(result, ["formula_prolog", "source"])
    return result


def generate_formula_by_variable_count(
    variable_count: int,
    use_all: bool = False,
    timeout: int = 10,
    seed: int | None = None,
    bridge: PrologBridge | None = None,
    allow_spoken_mode: bool = False,
) -> str:
    """Genera una formula che usa esattamente il numero di variabili richiesto."""
    _req_int_ge("variable_count", variable_count, 1)
    _req_int_ge("timeout", int(timeout), 1)
    if variable_count > MAX_GENERATOR_VARIABLES:
        raise ValueError(f"variable_count non può superare {MAX_GENERATOR_VARIABLES}")

    variables = _default_vars(variable_count)
    depth = _depth_from_var_count(variable_count)
    return generate_formula(
        depth=depth,
        variables=variables,
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
    """Genera una formula con N variabili e restituisce un payload pronto per JSON."""
    _req_int_ge("variable_count", variable_count, 1)
    _req_int_ge("timeout", int(timeout), 1)
    resolved_bridge = _ensure_bridge(bridge)
    formula = generate_formula_by_variable_count(
        variable_count=variable_count,
        use_all=use_all,
        timeout=timeout,
        seed=seed,
        bridge=resolved_bridge,
        allow_spoken_mode=allow_spoken_mode,
    )
    ast = _as_ast(formula)
    result = formula_payload(
        ast,
        source="prolog_variable_count",
        variable_count=variable_count,
    )
    if allow_spoken_mode:
        try:
            spoken_prolog, meta = generate_spoken_ready_prolog(
                ast,
                bridge=resolved_bridge,
                timeout=timeout,
            )
            result["spoken_ready_prolog"] = spoken_prolog
            result["spoken_transformations"] = meta.get("spoken_transformations", [])
            result["spoken_fallback_used"] = bool(meta.get("spoken_fallback_used", False))
        except Exception:
            # If spoken pipeline fails, don't break the JSON wrapper — return prolog only
            pass
    _ensure_keys(result, ["formula_prolog", "source", "variable_count"])
    return result


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
    max_binary_operators: int = MAX_BINARY_OPERATORS,
) -> list[str]:
    """Raccoglie un pool di formule candidate con vincoli condivisi tra builder quiz."""
    orchestrator_module = _get_orchestrator_module()
    impl = getattr(orchestrator_module, "_collect_candidate_formulas", None) if orchestrator_module else None
    if callable(impl):
        return cast(
            list[str],
            impl(
                bridge=bridge,
                variables=variables,
                required_options=required_options,
                rng=rng,
                timeout_provider=timeout_provider,
                operator_cycles=operator_cycles,
                target_atom_count=target_atom_count,
                excluded_formulas=excluded_formulas,
                dedupe_by_commutative_signature=dedupe_by_commutative_signature,
                require_non_empty_vars=require_non_empty_vars,
                forbid_adjacent_duplicate_atoms=forbid_adjacent_duplicate_atoms,
                spoken_only=spoken_only,
                max_binary_operators=max_binary_operators,
            ),
        )
    raise RuntimeError("orchestrator required: use orchestrator._collect_candidate_formulas")


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
    """Serializza l output di build_exercise come stringa JSON formattata."""
    _req_int_ge("timeout", int(timeout), 1)
    _req_int_ge("wrong_answers_count", wrong_answers_count, 1)
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)
    return _to_json_string(
        build_exercise(
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
    """Serializza l output di build_ex_depth come stringa JSON formattata."""
    _req_int_ge("timeout", int(timeout), 1)
    _req_int_ge("wrong_answers_count", wrong_answers_count, 1)
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)
    return _to_json_string(
        build_ex_depth(
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
    """Serializza l output di build_tvq come stringa JSON formattata."""
    _req_int_ge("predicate_count", predicate_count, 1)
    _req_int_ge("timeout", int(timeout), 1)
    _req_int_ge("true_options_count", true_options_count, 1)
    _req_int_ge("false_options_count", false_options_count, 1)
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)
    return _to_json_string(
        build_tvq(
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
    """Serializza l output del quiz di conseguenza logica come stringa JSON."""
    _req_int_ge("variable_count", variable_count, 1)
    _req_int_ge("correct_options_count", correct_options_count, 1)
    _req_int_ge("wrong_options_count", wrong_options_count, 1)
    _req_int_ge("timeout", int(timeout), 1)
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)
    return _to_json_string(
        build_logical_consequence_question(
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


def multiple_questions(
    questions: Sequence[dict[str, Any]],
    seed: int | None = None,
    bridge: PrologBridge | None = None,
) -> dict[str, Any]:
    """Compatibilita: delega il batch al livello applicativo."""
    orchestrator_module = _get_orchestrator_module()
    implementation = getattr(orchestrator_module, "multiple_questions", None) if orchestrator_module else None
    if not callable(implementation) or implementation is multiple_questions:
        raise RuntimeError("Implementazione orchestrator non disponibile")
    return implementation(questions=questions, seed=seed, bridge=bridge)
