from __future__ import annotations

import inspect

# Tipi usati nelle firme degli handler.
from collections.abc import Callable
from typing import Any, cast

# Componenti FastAPI per endpoint, validazione input e gestione errori.
from fastapi import Body, HTTPException
from pydantic import BaseModel

from server.app_factory import create_app
from server.openapi_docs import (
    AUTO_DEPTH_EXAMPLES,
    BINARY_EXAMPLES,
    BINARY_VALUATION_EXAMPLES,
    DEPTH_EXAMPLES,
    DISTRACT_EXACT_EXAMPLES,
    DISTRACT_MAX_STEPS_EXAMPLES,
    DISTRACT_N_EXAMPLES,
    ERROR_RESPONSES,
    EVAL_EXAMPLES,
    FORMULA_BY_VARIABLE_COUNT_EXAMPLES,
    FORMULA_EXAMPLES,
    FORMULA_PAYLOAD_EXAMPLES,
    GENERATOR_DEPTH_EXAMPLES,
    GENERATOR_EXPR_EXAMPLES,
    LOGICAL_CONSEQUENCE_QUESTION_EXAMPLES,
    MULTIPLE_QUESTIONS_EXAMPLES,
    TRANSLATION_QUESTION_EXAMPLES,
    TRUTH_VALUE_OPTIONS_EXAMPLES,
    VARS_EXAMPLES,
)
from server.schemas import (
    AutoDepthRequest,
    BinaryFormulaRequest,
    BinaryValuationRequest,
    DepthRequest,
    DistractExactRequest,
    DistractMaxStepsRequest,
    DistractNRequest,
    EvalRequest,
    FormulaByVariableCountRequest,
    FormulaPayloadRequest,
    FormulaRequest,
    FormulaVarsRequest,
    GeneratorAutoDepthRequest,
    GeneratorExprRequest,
    LogicalConsequenceQuestionRequest,
    MultipleQuestionsRequest,
    OperationResponse,
    TranslationQuestionRequest,
    TruthValueOptionsRequest,
    ValuationEntry,
    VarsRequest,
)
from testlogica import generator, orchestrator
from testlogica.config import MAX_BATCH_SIZE
from testlogica.constants import (
    MAX_EQUIVALENCE_WRONG_OPTIONS,
    MAX_EXPLICIT_EQUIVALENCE_WRONG_OPTIONS,
    MAX_GENERATOR_VARIABLES,
    MAX_LOGICAL_CONSEQUENCE_OPTIONS,
    MAX_LOGICAL_CONSEQUENCE_VARIABLES,
    MAX_SAFE_USE_ALL_SPACE,
    MIN_LOGICAL_CONSEQUENCE_VARIABLES,
    TRANSLATION_WRONG_OPTIONS,
)
from testlogica.prolog.health import readiness as prolog_readiness
from testlogica.prolog_bridge import (
    PrologBridge,
    from_prolog,
    get_default_bridge,
)

app = create_app()
QUIZ_SESSION_MAX_QUESTIONS = 100


def _build_bridge() -> PrologBridge:
    """Restituisce il bridge Prolog condiviso con configurazione fissa."""
    return get_default_bridge()


def _parse_formula(expr: str):
    """Parsa una formula Prolog e converte gli errori in risposta HTTP 422."""
    try:
        return from_prolog(expr)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Formula non valida: {exc}") from exc


def _normalize_valuation(valuation: list[ValuationEntry | str]) -> list[tuple[str, bool] | str]:
    """Normalizza la valutazione in tuple `(nome, valore)` o stringhe Prolog."""
    normalized: list[tuple[str, bool] | str] = []
    for item in valuation:
        if isinstance(item, str):
            normalized.append(item)
        else:
            normalized.append((item.name, item.value))
    return normalized


def _wrap(operation: str, result: Any) -> OperationResponse:
    """Impacchetta il risultato nel formato uniforme di risposta API."""
    return OperationResponse(operation=operation, result=result)


def _formula_handler(method_name: str, *, with_vars: bool = False) -> Callable[[Any], Any]:
    """Crea un handler generico per metodi bridge che accettano una formula."""

    def handler(payload):
        kwargs: dict[str, Any] = {"timeout": payload.timeout}
        if with_vars:
            kwargs["vars_list"] = payload.vars_list
        return getattr(_build_bridge(), method_name)(payload.expr, **kwargs)

    return handler


def _binary_handler(method_name: str) -> Callable[[Any], Any]:
    """Crea un handler per metodi bridge che confrontano due formule."""

    def handler(payload):
        return getattr(_build_bridge(), method_name)(
            payload.left,
            payload.right,
            vars_list=payload.vars_list,
            timeout=payload.timeout,
        )

    return handler


def _binary_val_handler(method_name: str) -> Callable[[Any], Any]:
    """Crea un handler per metodi bridge con due formule e valutazione esplicita."""

    def handler(payload):
        return getattr(_build_bridge(), method_name)(
            payload.left,
            payload.right,
            _normalize_valuation(payload.valuation),
            timeout=payload.timeout,
        )

    return handler


def _depth_handler(method_name: str) -> Callable[[Any], Any]:
    """Crea un handler per metodi bridge basati su profondita e variabili."""

    def handler(payload):
        return getattr(_build_bridge(), method_name)(
            payload.depth,
            payload.variables,
            timeout=payload.timeout,
        )

    return handler


def _steps_handler(method_name: str) -> Callable[[Any], Any]:
    """Crea un handler per metodi bridge con parametro `max_steps`."""

    def handler(payload):
        return getattr(_build_bridge(), method_name)(
            payload.expr,
            max_steps=payload.max_steps,
            timeout=payload.timeout,
        )

    return handler


def _add_post_route(
    *,
    path: str,
    operation_id: str,
    tag: str,
    summary: str,
    description: str,
    payload_model: type[BaseModel],
    examples: dict[str, Any],
    handler: Callable[[Any], Any],
) -> None:
    """Registra dinamicamente una route POST con metadati OpenAPI completi."""

    def endpoint(payload):
        return _wrap(operation_id, handler(payload))

    endpoint.__name__ = f"{operation_id}_endpoint"
    endpoint.__doc__ = description
    endpoint.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters=[
            inspect.Parameter(
                "payload",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=Body(..., openapi_examples=examples),
                annotation=payload_model,
            )
        ]
    )
    app.add_api_route(
        path,
        endpoint,
        methods=["POST"],
        tags=[tag],
        summary=summary,
        description=description,
        operation_id=operation_id,
        response_model=OperationResponse,
        responses=ERROR_RESPONSES,
    )


@app.get("/", tags=["meta"], summary="Informazioni sul servizio")
def home() -> dict[str, Any]:
    """Restituisce metadati base e link di documentazione del servizio."""
    return {
        "message": "TestLogica API attiva",
        "openapi": "/openapi.json",
        "docs": "/docs",
        "redoc": "/redoc",
        "openapi_version": app.openapi_version,
    }


@app.get("/health", tags=["meta"], summary="Stato del servizio")
def health() -> dict[str, str]:
    """Espone un controllo di salute minimale del backend."""
    return {"status": "ok"}


@app.get("/ready", tags=["meta"], summary="Disponibilita delle dipendenze")
def ready() -> dict[str, str]:
    is_ready, detail = prolog_readiness()
    if not is_ready:
        raise HTTPException(status_code=503, detail=detail)
    try:
        # La sola presenza di binario e sorgenti non garantisce che la sessione
        # RPC sia caricabile nella versione SWI-Prolog installata sul server.
        if not _build_bridge().ask_bool("true", timeout=3):
            raise RuntimeError("query di prova Prolog non riuscita")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Sessione SWI-Prolog non disponibile") from exc
    return {"status": "ready"}


@app.get("/api/capabilities", tags=["meta"], summary="Capacita supportate dal quiz")
def capabilities() -> dict[str, Any]:
    """Espone limiti stabili utili al configuratore senza avviare Prolog."""
    return {
        "version": 1,
        "question_types": [
            "equivalence",
            "truth-value",
            "logical-consequence",
            "translation",
            "quantifier-negation",
        ],
        "difficulties": ["easy", "medium", "hard"],
        "modes": ["practice", "exam"],
        "limits": {
            "batch_size": MAX_BATCH_SIZE,
            "question_count": {"minimum": 1, "maximum": QUIZ_SESSION_MAX_QUESTIONS},
            "atom_count": {"minimum": 3, "maximum": 5},
            "formula_variable_count": {"minimum": 1, "maximum": MAX_GENERATOR_VARIABLES},
            "equivalence_wrong_option_count": {
                "minimum": 1,
                "maximum": MAX_EQUIVALENCE_WRONG_OPTIONS,
                "explicit_formula_maximum": MAX_EXPLICIT_EQUIVALENCE_WRONG_OPTIONS,
            },
            "exhaustive_formula_space_maximum": MAX_SAFE_USE_ALL_SPACE,
            "logical_consequence_variable_count": {
                "minimum": MIN_LOGICAL_CONSEQUENCE_VARIABLES,
                "maximum": MAX_LOGICAL_CONSEQUENCE_VARIABLES,
            },
            "logical_consequence_option_count": {
                "minimum": 2,
                "maximum": MAX_LOGICAL_CONSEQUENCE_OPTIONS,
                "must_be_even": True,
            },
            "translation_wrong_option_count": TRANSLATION_WRONG_OPTIONS,
            "timeout_seconds": {"minimum": 1, "maximum": 120},
        },
        "features": {
            "construction_trace": True,
            "transformation_trace": True,
            "spoken_mode": True,
            "batch_questions": True,
        },
    }


_add_post_route(
    path="/api/prolog-bridge/logic/assignment",
    operation_id="bridge_assignment",
    tag="prolog-bridge-logic",
    summary="Genera valutazioni per un insieme di variabili",
    description=(
        "Espone PrologBridge.assignment e restituisce tutte le valutazioni "
        "booleane possibili per la lista di variabili fornita."
    ),
    payload_model=VarsRequest,
    examples=VARS_EXAMPLES,
    handler=lambda payload: _build_bridge().assignment(payload.vars_list, timeout=payload.timeout),
)

_add_post_route(
    path="/api/prolog-bridge/logic/eval",
    operation_id="bridge_eval",
    tag="prolog-bridge-logic",
    summary="Valuta una formula sotto una valutazione",
    description="Espone PrologBridge.eval e restituisce il valore booleano della formula sotto la valutazione fornita.",
    payload_model=EvalRequest,
    examples=EVAL_EXAMPLES,
    handler=lambda payload: _build_bridge().eval(
        payload.expr,
        _normalize_valuation(payload.valuation),
        timeout=payload.timeout,
    ),
)

_add_post_route(
    path="/api/prolog-bridge/logic/vars-in-formula",
    operation_id="bridge_vars_in_formula",
    tag="prolog-bridge-logic",
    summary="Estrae le variabili di una formula",
    description=(
        "Espone PrologBridge.vars_in_formula e restituisce la lista ordinata delle variabili presenti nella formula."
    ),
    payload_model=FormulaRequest,
    examples=FORMULA_EXAMPLES,
    handler=_formula_handler("vars_in_formula"),
)

_add_post_route(
    path="/api/prolog-bridge/logic/truth-table-auto",
    operation_id="bridge_truth_table_auto",
    tag="prolog-bridge-logic",
    summary="Costruisce la tabella di verita con variabili auto-rilevate",
    description="Espone PrologBridge.truth_table_auto e restituisce variabili e righe della tabella di verita.",
    payload_model=FormulaRequest,
    examples=FORMULA_EXAMPLES,
    handler=_formula_handler("truth_table_auto"),
)

_add_post_route(
    path="/api/prolog-bridge/equivalence/equiv",
    operation_id="bridge_equiv",
    tag="prolog-bridge-equivalence",
    summary="Verifica equivalenza logica",
    description=(
        "Espone PrologBridge.equiv e restituisce true se le due formule sono "
        "logicamente equivalenti sulle variabili fornite."
    ),
    payload_model=BinaryFormulaRequest,
    examples=BINARY_EXAMPLES,
    handler=_binary_handler("equiv"),
)

_add_post_route(
    path="/api/prolog-bridge/equivalence/not-equiv",
    operation_id="bridge_not_equiv",
    tag="prolog-bridge-equivalence",
    summary="Verifica non equivalenza logica",
    description=(
        "Espone PrologBridge.not_equiv e restituisce true se esiste almeno "
        "una valutazione che distingue le due formule."
    ),
    payload_model=BinaryFormulaRequest,
    examples=BINARY_EXAMPLES,
    handler=_binary_handler("not_equiv"),
)

_add_post_route(
    path="/api/prolog-bridge/equivalence/counterexample-equiv",
    operation_id="bridge_counterexample_equiv",
    tag="prolog-bridge-equivalence",
    summary="Restituisce controesempi di equivalenza",
    description=(
        "Espone PrologBridge.counterexample_equiv e restituisce le valutazioni che mostrano la non equivalenza."
    ),
    payload_model=BinaryFormulaRequest,
    examples=BINARY_EXAMPLES,
    handler=_binary_handler("counterexample_equiv"),
)

for path_suffix, operation_id, summary in [
    ("all-models", "bridge_all_models", "Restituisce tutti i modelli"),
    ("all-countermodels", "bridge_all_countermodels", "Restituisce tutti i contromodelli"),
    ("model", "bridge_model", "Restituisce un modello"),
    ("countermodel", "bridge_countermodel", "Restituisce un contromodello"),
    ("tautology", "bridge_tautology", "Verifica se la formula e una tautologia"),
    ("contradiction", "bridge_contradiction", "Verifica se la formula e una contraddizione"),
    ("satisfiable", "bridge_satisfiable", "Verifica se la formula e soddisfacibile"),
    ("unsatisfiable", "bridge_unsatisfiable", "Verifica se la formula e insoddisfacibile"),
    ("satisfying-assignment", "bridge_satisfying_assignment", "Restituisce una assegnazione soddisfacente"),
    ("falsifying-assignment", "bridge_falsifying_assignment", "Restituisce una assegnazione falsificante"),
]:
    method_name = operation_id.removeprefix("bridge_").replace("-", "_")
    _add_post_route(
        path=f"/api/prolog-bridge/equivalence/{path_suffix}",
        operation_id=operation_id,
        tag="prolog-bridge-equivalence",
        summary=summary,
        description=f"Espone PrologBridge.{method_name} per una singola formula.",
        payload_model=FormulaVarsRequest,
        examples=FORMULA_EXAMPLES,
        handler=_formula_handler(method_name, with_vars=True),
    )

for path_suffix, method_name, summary in [
    ("implies-formula", "implies_formula", "Verifica implicazione logica"),
    ("mutually-exclusive", "mutually_exclusive", "Verifica mutua esclusione"),
    ("jointly-satisfiable", "jointly_satisfiable", "Verifica soddisfacibilita congiunta"),
]:
    _add_post_route(
        path=f"/api/prolog-bridge/equivalence/{path_suffix}",
        operation_id=f"bridge_{method_name}",
        tag="prolog-bridge-equivalence",
        summary=summary,
        description=f"Espone PrologBridge.{method_name} per due formule con una lista opzionale di variabili.",
        payload_model=BinaryFormulaRequest,
        examples=BINARY_EXAMPLES,
        handler=_binary_handler(method_name),
    )

for path_suffix, method_name, summary in [
    ("same-value-under", "same_value_under", "Confronta due formule sotto una valutazione"),
    ("different-value-under", "different_value_under", "Verifica se due formule differiscono sotto una valutazione"),
]:
    _add_post_route(
        path=f"/api/prolog-bridge/equivalence/{path_suffix}",
        operation_id=f"bridge_{method_name}",
        tag="prolog-bridge-equivalence",
        summary=summary,
        description=f"Espone PrologBridge.{method_name} per due formule sotto una valutazione esplicita.",
        payload_model=BinaryValuationRequest,
        examples=BINARY_VALUATION_EXAMPLES,
        handler=_binary_val_handler(method_name),
    )

for path_suffix, method_name, summary in [
    ("rewrite-formula", "rewrite_formula", "Restituisce formule equivalenti ottenute con rewrite"),
    ("expand-implications", "expand_implications", "Espande le implicazioni"),
    ("to-nnf", "to_nnf", "Converte una formula in NNF"),
    ("to-cnf", "to_cnf", "Converte una formula in CNF"),
    ("to-dnf", "to_dnf", "Converte una formula in DNF"),
    ("rewrite-path", "rewrite_path", "Restituisce un percorso di rewrite"),
]:
    _add_post_route(
        path=f"/api/prolog-bridge/rewrite/{path_suffix}",
        operation_id=f"bridge_{method_name}",
        tag="prolog-bridge-rewrite",
        summary=summary,
        description=f"Espone PrologBridge.{method_name} per una formula in sintassi Prolog.",
        payload_model=FormulaRequest,
        examples=FORMULA_EXAMPLES,
        handler=_formula_handler(method_name),
    )

for path_suffix, method_name, summary in [
    ("formula-of-depth", "formula_of_depth", "Genera formule di profondita esatta"),
    ("all-formulas-of-depth", "all_depth", "Restituisce tutte le formule della profondita richiesta"),
]:
    _add_post_route(
        path=f"/api/prolog-bridge/templates/{path_suffix}",
        operation_id=f"bridge_{method_name}",
        tag="prolog-bridge-templates",
        summary=summary,
        description=f"Espone PrologBridge.{method_name} usando profondita e variabili come input.",
        payload_model=DepthRequest,
        examples=DEPTH_EXAMPLES,
        handler=_depth_handler(method_name),
    )

for path_suffix, method_name, summary, steps_payload_model, examples in [
    (
        "distract-formula",
        "distract_formula",
        "Genera distractor fino a un numero massimo di passi",
        DistractMaxStepsRequest,
        DISTRACT_MAX_STEPS_EXAMPLES,
    ),
    (
        "distract-formula-with-trace",
        "distract_trace",
        "Genera distractor con traccia",
        DistractMaxStepsRequest,
        DISTRACT_MAX_STEPS_EXAMPLES,
    ),
    (
        "all-distractions",
        "all_distractions",
        "Restituisce tutti i distractor fino a max_steps",
        DistractMaxStepsRequest,
        DISTRACT_MAX_STEPS_EXAMPLES,
    ),
    (
        "non-equivalent-distraction",
        "non_equivalent_distraction",
        "Genera distractor non equivalenti",
        DistractMaxStepsRequest,
        DISTRACT_MAX_STEPS_EXAMPLES,
    ),
    (
        "all-non-equivalent-distractions",
        "all_neq",
        "Restituisce tutti i distractor non equivalenti",
        DistractMaxStepsRequest,
        DISTRACT_MAX_STEPS_EXAMPLES,
    ),
]:
    _add_post_route(
        path=f"/api/prolog-bridge/distractions/{path_suffix}",
        operation_id=f"bridge_{method_name}",
        tag="prolog-bridge-distractions",
        summary=summary,
        description=f"Espone PrologBridge.{method_name} per una formula con limite di passi.",
        payload_model=steps_payload_model,
        examples=examples,
        handler=_steps_handler(method_name),
    )

_add_post_route(
    path="/api/prolog-bridge/distractions/distract-exactly",
    operation_id="bridge_distract_exactly",
    tag="prolog-bridge-distractions",
    summary="Genera distractor con numero esatto di passi",
    description="Espone PrologBridge.distract_exactly per una formula e un numero esatto di passi.",
    payload_model=DistractExactRequest,
    examples=DISTRACT_EXACT_EXAMPLES,
    handler=lambda payload: _build_bridge().distract_exactly(
        payload.expr,
        steps=payload.steps,
        timeout=payload.timeout,
    ),
)

_add_post_route(
    path="/api/prolog-bridge/distractions/distract-n",
    operation_id="bridge_distract_n",
    tag="prolog-bridge-distractions",
    summary="Restituisce al piu N distractor",
    description="Espone PrologBridge.distract_n per una formula, un massimo di passi e un limite N.",
    payload_model=DistractNRequest,
    examples=DISTRACT_N_EXAMPLES,
    handler=lambda payload: _build_bridge().distract_n(
        payload.expr,
        max_steps=payload.max_steps,
        n=payload.n,
        timeout=payload.timeout,
    ),
)

for path_suffix, method_name, summary in [
    ("one-step-distraction", "one_step_distraction", "Restituisce distractor in un solo passo"),
    ("one-step-non-equivalent-distraction", "one_step_neq", "Restituisce distractor non equivalenti in un solo passo"),
    (
        "all-one-step-non-equivalent-distractions",
        "all_step_neq",
        "Restituisce tutti i distractor non equivalenti in un solo passo",
    ),
]:
    _add_post_route(
        path=f"/api/prolog-bridge/distractions/{path_suffix}",
        operation_id=f"bridge_{method_name}",
        tag="prolog-bridge-distractions",
        summary=summary,
        description=f"Espone PrologBridge.{method_name} per una formula con un solo passo di mutazione.",
        payload_model=FormulaRequest,
        examples=FORMULA_EXAMPLES,
        handler=_formula_handler(method_name),
    )

for path_suffix, operation_id, summary, generator_payload_model, examples, handler in [
    (
        "formula-depth",
        "generator_formula_depth",
        "Calcola la profondita di una formula",
        FormulaRequest,
        FORMULA_EXAMPLES,
        lambda payload: generator.formula_depth(_parse_formula(payload.expr)),
    ),
    (
        "formula-size",
        "generator_formula_size",
        "Calcola la dimensione di una formula",
        FormulaRequest,
        FORMULA_EXAMPLES,
        lambda payload: generator.formula_size(_parse_formula(payload.expr)),
    ),
    (
        "formula-metadata",
        "generator_formula_metadata",
        "Restituisce i metadati di una formula",
        FormulaRequest,
        FORMULA_EXAMPLES,
        lambda payload: generator.formula_metadata(_parse_formula(payload.expr)),
    ),
    (
        "formula-payload",
        "generator_formula_payload",
        "Restituisce payload JSON di una formula",
        FormulaPayloadRequest,
        FORMULA_PAYLOAD_EXAMPLES,
        lambda payload: generator.formula_payload(_parse_formula(payload.expr), **(payload.extra or {})),
    ),
    (
        "generate-formula",
        "generator_generate_formula",
        "Genera una formula in sintassi Prolog (profondita automatica)",
        AutoDepthRequest,
        AUTO_DEPTH_EXAMPLES,
        lambda payload: generator.generate_formula(
            variables=payload.variables,
            use_all=payload.use_all,
            timeout=payload.timeout,
            seed=payload.seed,
            bridge=_build_bridge(),
            allow_spoken_mode=payload.allow_spoken_mode,
        ),
    ),
    (
        "generate-formula-json",
        "generator_generate_formula_json",
        "Genera una formula come JSON (profondita automatica)",
        AutoDepthRequest,
        AUTO_DEPTH_EXAMPLES,
        lambda payload: orchestrator.generate_formula_json(
            variables=payload.variables,
            use_all=payload.use_all,
            timeout=payload.timeout,
            seed=payload.seed,
            bridge=_build_bridge(),
            allow_spoken_mode=payload.allow_spoken_mode,
        ),
    ),
    (
        "generate-formula-by-variable-count",
        "generator_generate_formula_by_variable_count",
        "Genera una formula in sintassi Prolog con un numero specifico di variabili",
        FormulaByVariableCountRequest,
        FORMULA_BY_VARIABLE_COUNT_EXAMPLES,
        lambda payload: generator.generate_formula_by_variable_count(
            variable_count=payload.variable_count,
            use_all=payload.use_all,
            timeout=payload.timeout,
            seed=payload.seed,
            bridge=_build_bridge(),
            allow_spoken_mode=payload.allow_spoken_mode,
        ),
    ),
    (
        "generate-formula-by-variable-count-json",
        "generator_generate_formula_by_variable_count_json",
        "Genera una formula con numero variabili esplicito e la restituisce come payload JSON",
        FormulaByVariableCountRequest,
        FORMULA_BY_VARIABLE_COUNT_EXAMPLES,
        lambda payload: orchestrator.generate_formula_by_variable_count_json(
            variable_count=payload.variable_count,
            use_all=payload.use_all,
            timeout=payload.timeout,
            seed=payload.seed,
            bridge=_build_bridge(),
            allow_spoken_mode=payload.allow_spoken_mode,
        ),
    ),
    (
        "build-exercise",
        "generator_build_exercise",
        "Costruisce un esercizio a partire da una formula",
        GeneratorExprRequest,
        GENERATOR_EXPR_EXAMPLES,
        lambda payload: generator.build_exercise(
            expr=payload.expr,
            wrong_answers_count=payload.wrong_answers_count,
            bridge=_build_bridge(),
            seed=payload.seed,
            timeout=payload.timeout,
            allow_spoken_mode=payload.allow_spoken_mode,
        ),
    ),
    (
        "build-exercise-from-depth",
        "generator_build_ex_depth",
        "Costruisce un esercizio con variabili automatiche (profondita automatica)",
        GeneratorAutoDepthRequest,
        GENERATOR_DEPTH_EXAMPLES,
        lambda payload: generator.build_ex_depth(
            use_all=payload.use_all,
            timeout=payload.timeout,
            seed=payload.seed,
            wrong_answers_count=payload.wrong_answers_count,
            bridge=_build_bridge(),
            allow_spoken_mode=payload.allow_spoken_mode,
        ),
    ),
    (
        "build-truth-value-options-question",
        "generator_build_tvq",
        "Costruisce una domanda da informazioni booleane sui predicati e opzioni vere/false",
        TruthValueOptionsRequest,
        TRUTH_VALUE_OPTIONS_EXAMPLES,
        lambda payload: generator.build_tvq(
            predicate_count=payload.predicate_count,
            true_options_count=payload.true_options_count,
            false_options_count=payload.false_options_count,
            timeout=payload.timeout,
            seed=payload.seed,
            bridge=_build_bridge(),
            allow_spoken_mode=payload.allow_spoken_mode,
        ),
    ),
    (
        "build-logical-consequence-question",
        "generator_build_logical_consequence_question",
        "Costruisce un quiz di conseguenza logica con opzioni corrette e errate",
        LogicalConsequenceQuestionRequest,
        LOGICAL_CONSEQUENCE_QUESTION_EXAMPLES,
        lambda payload: generator.build_logical_consequence_question(
            variable_count=payload.variable_count,
            correct_options_count=payload.correct_options_count,
            wrong_options_count=payload.wrong_options_count,
            timeout=payload.timeout,
            seed=payload.seed,
            allow_spoken_mode=payload.allow_spoken_mode,
            bridge=_build_bridge(),
        ),
    ),
    (
        "build-translation-question",
        "generator_build_translation_question",
        "Costruisce un quiz di traduzione italiano -> logica",
        TranslationQuestionRequest,
        TRANSLATION_QUESTION_EXAMPLES,
        lambda payload: generator.build_translation_question(
            mode=payload.mode,
            quantifier_ratio=payload.quantifier_ratio,
            wrong_options_count=payload.wrong_options_count,
            names_pool=payload.names_pool,
            people_count=payload.people_count,
            actions_pool=payload.actions_pool,
            allow_spoken_mode=payload.allow_spoken_mode,
            seed=payload.seed,
            timeout=payload.timeout,
        ),
    ),
    (
        "multiple-questions",
        "generator_multiple_questions",
        "Costruisce piu domande in una singola chiamata e le mescola",
        MultipleQuestionsRequest,
        MULTIPLE_QUESTIONS_EXAMPLES,
        lambda payload: orchestrator.multiple_questions(
            [item.model_dump() for item in payload.questions], seed=payload.seed, bridge=_build_bridge()
        ),
    ),
    (
        "build-exercise-json-string",
        "generator_build_ex_json",
        "Costruisce un esercizio e lo serializza come stringa JSON",
        GeneratorExprRequest,
        GENERATOR_EXPR_EXAMPLES,
        lambda payload: orchestrator.build_ex_json(
            expr=payload.expr,
            bridge=_build_bridge(),
            seed=payload.seed,
            wrong_answers_count=payload.wrong_answers_count,
            timeout=payload.timeout,
            allow_spoken_mode=payload.allow_spoken_mode,
        ),
    ),
    (
        "build-exercise-from-depth-json-string",
        "generator_build_ex_depth_json",
        "Costruisce un esercizio con variabili automatiche e lo serializza come stringa JSON",
        GeneratorAutoDepthRequest,
        GENERATOR_DEPTH_EXAMPLES,
        lambda payload: orchestrator.build_ex_depth_json(
            use_all=payload.use_all,
            timeout=payload.timeout,
            seed=payload.seed,
            wrong_answers_count=payload.wrong_answers_count,
            bridge=_build_bridge(),
            allow_spoken_mode=payload.allow_spoken_mode,
        ),
    ),
    (
        "build-truth-value-options-question-json-string",
        "generator_build_tvq_json",
        "Costruisce la domanda con opzioni vere/false e la serializza come JSON",
        TruthValueOptionsRequest,
        TRUTH_VALUE_OPTIONS_EXAMPLES,
        lambda payload: orchestrator.build_tvq_json(
            predicate_count=payload.predicate_count,
            true_options_count=payload.true_options_count,
            false_options_count=payload.false_options_count,
            timeout=payload.timeout,
            seed=payload.seed,
            bridge=_build_bridge(),
            allow_spoken_mode=payload.allow_spoken_mode,
        ),
    ),
    (
        "build-logical-consequence-question-json-string",
        "generator_build_logical_consequence_question_json",
        "Costruisce il quiz di conseguenza logica e lo serializza come JSON",
        LogicalConsequenceQuestionRequest,
        LOGICAL_CONSEQUENCE_QUESTION_EXAMPLES,
        lambda payload: orchestrator.build_logical_consequence_question_json(
            variable_count=payload.variable_count,
            correct_options_count=payload.correct_options_count,
            wrong_options_count=payload.wrong_options_count,
            timeout=payload.timeout,
            seed=payload.seed,
            allow_spoken_mode=payload.allow_spoken_mode,
            bridge=_build_bridge(),
        ),
    ),
]:
    _add_post_route(
        path=f"/api/generator/{path_suffix}",
        operation_id=operation_id,
        tag="generator",
        summary=summary,
        description=summary,
        payload_model=cast(type[BaseModel], generator_payload_model),
        examples=examples,
        handler=handler,
    )
