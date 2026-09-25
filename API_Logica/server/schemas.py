"""Pydantic request and response contracts for the HTTP API."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from testlogica.config import DEFAULT_TIMEOUT, MAX_BATCH_SIZE
from testlogica.constants import (
    MAX_EQUIVALENCE_WRONG_OPTIONS,
    MAX_EXPLICIT_EQUIVALENCE_WRONG_OPTIONS,
    MAX_GENERATOR_VARIABLES,
    MAX_LOGICAL_CONSEQUENCE_OPTIONS,
    MAX_LOGICAL_CONSEQUENCE_VARIABLES,
    MIN_LOGICAL_CONSEQUENCE_VARIABLES,
    TRANSLATION_WRONG_OPTIONS,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FormulaConstructionStep(ApiModel):
    """Un singolo nodo composto durante la costruzione bottom-up."""

    index: int = Field(ge=1)
    node_id: str = Field(min_length=1, max_length=256)
    kind: Literal["atom", "predicate", "unary", "binary", "quantifier"]
    operator: str | None = Field(default=None, max_length=64)
    operands: list[str] = Field(default_factory=list, max_length=8)
    result_prolog: str = Field(min_length=1, max_length=10_000)
    depth: int = Field(ge=0, le=128)
    details: dict[str, str] = Field(default_factory=dict)


class FormulaConstructionTrace(ApiModel):
    """Contratto versionato per spiegare come una formula è stata composta."""

    version: Literal[1] = 1
    strategy: Literal["ast_postorder", "term_postorder"]
    final_formula_prolog: str = Field(min_length=1, max_length=10_000)
    steps: list[FormulaConstructionStep] = Field(min_length=1, max_length=10_000)


class FormulaTransformationStep(ApiModel):
    """Un arco reale nel percorso che collega due formule consecutive."""

    index: int = Field(ge=1)
    kind: Literal["rewrite", "mutation"]
    rule: str = Field(min_length=1, max_length=128)
    before_prolog: str = Field(min_length=1, max_length=10_000)
    after_prolog: str = Field(min_length=1, max_length=10_000)
    before_subformula_prolog: str = Field(min_length=1, max_length=10_000)
    after_subformula_prolog: str = Field(min_length=1, max_length=10_000)
    location: str = Field(min_length=1, max_length=512)


class FormulaTransformationTrace(ApiModel):
    """Contratto versionato per spiegare come una formula e stata raggiunta."""

    version: Literal[1] = 1
    strategy: Literal["equivalence_rewrite", "distractor_mutation"]
    source_formula_prolog: str = Field(min_length=1, max_length=10_000)
    final_formula_prolog: str = Field(min_length=1, max_length=10_000)
    preserves_meaning: bool
    steps: list[FormulaTransformationStep] = Field(min_length=1, max_length=10_000)


class ValuationEntry(ApiModel):
    name: str = Field(min_length=1, max_length=32, description="Nome della variabile proposizionale")
    value: bool = Field(description="Valore booleano della variabile")


class RequestBase(ApiModel):
    timeout: int = Field(default=DEFAULT_TIMEOUT, ge=1, le=120, description="Timeout della chiamata in secondi")


class FormulaRequest(RequestBase):
    expr: str = Field(min_length=1, max_length=10_000, description="Formula in sintassi Prolog, per esempio and(p,q)")


class FormulaPayloadRequest(FormulaRequest):
    extra: dict[str, Any] | None = Field(default=None, description="Campi extra da includere nel payload")


class VarsRequest(RequestBase):
    vars_list: list[str] = Field(min_length=1, max_length=64, description="Lista di variabili proposizionali")


class FormulaVarsRequest(FormulaRequest):
    vars_list: list[str] | None = Field(default=None, max_length=64, description="Variabili da usare per l'operazione")


class EvalRequest(FormulaRequest):
    valuation: list[ValuationEntry | str] = Field(
        max_length=64,
        description="Valutazione come lista di oggetti {name, value} o stringhe gia in formato Prolog",
    )


class BinaryFormulaRequest(RequestBase):
    left: str = Field(min_length=1, max_length=10_000, description="Formula sinistra in sintassi Prolog")
    right: str = Field(min_length=1, max_length=10_000, description="Formula destra in sintassi Prolog")
    vars_list: list[str] | None = Field(default=None, max_length=64, description="Variabili da usare nel controllo")


class BinaryValuationRequest(RequestBase):
    left: str = Field(min_length=1, max_length=10_000, description="Formula sinistra in sintassi Prolog")
    right: str = Field(min_length=1, max_length=10_000, description="Formula destra in sintassi Prolog")
    valuation: list[ValuationEntry | str] = Field(
        max_length=64,
        description="Valutazione come lista di oggetti {name, value} o stringhe gia in formato Prolog",
    )


class DepthRequest(RequestBase):
    depth: int = Field(ge=0, le=32, description="Profondita della formula")
    variables: list[str] = Field(min_length=1, max_length=64, description="Variabili disponibili")
    use_all: bool = Field(default=False, description="Se vero, usa tutte le formule della profondita indicata")
    seed: int | None = Field(default=None, description="Seed casuale")


class DistractMaxStepsRequest(FormulaRequest):
    max_steps: int = Field(ge=1, le=64, description="Numero massimo di passi di distrazione")


class DistractExactRequest(FormulaRequest):
    steps: int = Field(ge=0, le=64, description="Numero esatto di passi di distrazione")


class DistractNRequest(FormulaRequest):
    max_steps: int = Field(ge=1, le=64, description="Numero massimo di passi di distrazione")
    n: int = Field(ge=0, le=1_000, description="Numero massimo di distractor da restituire")


class AutoDepthRequest(RequestBase):
    variables: list[str] = Field(
        min_length=1,
        max_length=MAX_GENERATOR_VARIABLES,
        description="Variabili disponibili; il generatore campionato supporta operativamente fino a 5 variabili",
    )
    use_all: bool = Field(
        default=False,
        description="Usa l'insieme completo solo quando resta sotto la soglia combinatoria di sicurezza",
    )
    seed: int | None = Field(default=None, description="Seed casuale")
    allow_spoken_mode: bool = False


class GeneratorAutoDepthRequest(RequestBase):
    use_all: bool = False
    seed: int | None = None
    wrong_answers_count: int = Field(default=3, ge=1, le=MAX_EQUIVALENCE_WRONG_OPTIONS)
    allow_spoken_mode: bool = False


class GeneratorExprRequest(FormulaRequest):
    expr: str = Field(
        min_length=1,
        max_length=10_000,
        description=(
            "Formula Prolog con almeno 2 atomi, al massimo 2 operatori binari "
            "e senza due atomi uguali come figli dello stesso operatore"
        ),
    )
    wrong_answers_count: int = Field(
        default=3,
        ge=1,
        le=MAX_EXPLICIT_EQUIVALENCE_WRONG_OPTIONS,
        description=(
            "Distractor per una formula esplicita; il profilo supportato richiede "
            f"al massimo {MAX_EXPLICIT_EQUIVALENCE_WRONG_OPTIONS}"
        ),
    )
    seed: int | None = None
    allow_spoken_mode: bool = False


class TruthValueOptionsRequest(RequestBase):
    predicate_count: int = Field(ge=3, le=5)
    true_options_count: int = Field(ge=1, le=32)
    false_options_count: int = Field(ge=1, le=32)
    seed: int | None = None
    allow_spoken_mode: bool = False


class FormulaByVariableCountRequest(RequestBase):
    variable_count: int = Field(ge=1, le=MAX_GENERATOR_VARIABLES)
    use_all: bool = False
    seed: int | None = None
    allow_spoken_mode: bool = False


class LogicalConsequenceQuestionRequest(RequestBase):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "description": (
                "Il totale di correct_options_count e wrong_options_count deve essere pari "
                f"e non superiore a {MAX_LOGICAL_CONSEQUENCE_OPTIONS}."
            ),
            "x-option-count-constraints": {
                "sum_multiple_of": 2,
                "sum_maximum": MAX_LOGICAL_CONSEQUENCE_OPTIONS,
            },
        },
    )

    variable_count: int = Field(
        ge=MIN_LOGICAL_CONSEQUENCE_VARIABLES,
        le=MAX_LOGICAL_CONSEQUENCE_VARIABLES,
    )
    correct_options_count: int = Field(ge=1, le=32)
    wrong_options_count: int = Field(ge=1, le=32)
    allow_spoken_mode: bool = False
    seed: int | None = None

    @model_validator(mode="after")
    def validate_even_option_count(self) -> Self:
        option_count = self.correct_options_count + self.wrong_options_count
        if option_count % 2 != 0:
            raise ValueError("Il totale delle opzioni deve essere pari")
        if option_count > MAX_LOGICAL_CONSEQUENCE_OPTIONS:
            raise ValueError(f"Il totale delle opzioni non può superare {MAX_LOGICAL_CONSEQUENCE_OPTIONS}")
        return self


class TranslationQuestionRequest(ApiModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "description": (
                "I pool devono poter descrivere atomi distinti per ogni subtype "
                "che mode e quantifier_ratio possono selezionare."
            ),
            "x-pool-capacity-constraints": {
                "quantifier_distinct_actions_minimum": "people_count oppure 2",
                "propositional_distinct_descriptions_minimum": 2,
                "propositional_chain_distinct_descriptions_minimum": 3,
            },
        },
    )

    mode: str = Field(pattern="^(auto|quantifier|propositional)$")
    quantifier_ratio: float = Field(ge=0, le=1)
    wrong_options_count: int = Field(
        default=TRANSLATION_WRONG_OPTIONS,
        ge=TRANSLATION_WRONG_OPTIONS,
        le=TRANSLATION_WRONG_OPTIONS,
    )
    names_pool: list[str] = Field(min_length=1, max_length=128)
    people_count: int | None = Field(default=None, ge=1, le=128)
    actions_pool: list[str] = Field(min_length=1, max_length=128)
    allow_spoken_mode: bool = False
    seed: int | None = None
    timeout: int = Field(
        default=DEFAULT_TIMEOUT,
        ge=1,
        le=120,
        validation_alias=AliasChoices("timeout", "timeout_seconds"),
        description="Timeout in secondi; timeout_seconds resta accettato per compatibilita",
    )

    @model_validator(mode="after")
    def validate_pool_capacity(self) -> Self:
        effective_quantifier_count = self.people_count or 2
        quantifier_is_possible = self.mode == "quantifier" or (
            self.mode == "auto" and self.quantifier_ratio > 0
        )
        propositional_is_possible = self.mode == "propositional" or (
            self.mode == "auto" and self.quantifier_ratio < 1
        )
        distinct_names = len(set(self.names_pool))
        distinct_actions = len(set(self.actions_pool))
        if quantifier_is_possible and distinct_actions < effective_quantifier_count:
            raise ValueError(
                "actions_pool non contiene abbastanza azioni distinte per il subtype quantifier"
            )
        if (
            propositional_is_possible
            and self.people_count is not None
            and distinct_names < self.people_count
        ):
            raise ValueError(
                "names_pool non contiene abbastanza nomi distinti per il subtype propositional"
            )
        effective_propositional_names = self.people_count or distinct_names
        if (
            propositional_is_possible
            and effective_propositional_names * distinct_actions < 2
        ):
            raise ValueError(
                "names_pool e actions_pool non producono abbastanza descrizioni atomiche distinte"
            )
        return self


_BATCH_OPERATION_ALIASES = {
    "build_exercise_from_depth": "build_ex_depth",
    "build_truth_value_options_question": "build_tvq",
}

_BATCH_PAYLOAD_MODELS: dict[str, type[ApiModel]] = {
    "build_exercise": GeneratorExprRequest,
    "build_ex_depth": GeneratorAutoDepthRequest,
    "build_tvq": TruthValueOptionsRequest,
    "build_logical_consequence_question": LogicalConsequenceQuestionRequest,
    "build_translation_question": TranslationQuestionRequest,
}


class MultipleQuestionItemRequest(ApiModel):
    operation: str = Field(
        min_length=1,
        max_length=128,
        description="Nome dell'operazione generator; gli alias legacy supportati vengono normalizzati",
    )
    payload: dict[str, Any] = Field(
        description=(
            "Payload validato con lo stesso modello dell'endpoint singolo quando operation è supportata; "
            "le operazioni sconosciute restano rappresentate come elementi failed nel risultato batch"
        )
    )

    @model_validator(mode="after")
    def validate_operation_payload(self) -> Self:
        """Applica nel batch lo stesso contratto usato dall'endpoint singolo."""
        normalized_operation = _BATCH_OPERATION_ALIASES.get(self.operation, self.operation)
        payload_model = _BATCH_PAYLOAD_MODELS.get(normalized_operation)
        if payload_model is not None:
            validated_payload = payload_model.model_validate(self.payload)
            # Conserva soltanto i campi forniti dal chiamante, ma usa i nomi
            # canonici (per esempio ``timeout`` al posto del vecchio alias
            # ``timeout_seconds``) che i builder Python accettano.
            self.payload = validated_payload.model_dump(exclude_unset=True)
        return self


class MultipleQuestionsRequest(ApiModel):
    questions: list[MultipleQuestionItemRequest] = Field(min_length=1, max_length=MAX_BATCH_SIZE)
    seed: int | None = None


class OperationResponse(ApiModel):
    operation: str
    result: Any


class ErrorResponse(ApiModel):
    code: str
    message: str
    request_id: str | None = None
