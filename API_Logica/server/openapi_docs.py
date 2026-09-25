"""OpenAPI tags, shared responses, and request examples."""

from __future__ import annotations

from typing import Any

from server.schemas import ErrorResponse

OPENAPI_TAGS = [
    {"name": "meta", "description": "Endpoint informativi e di stato del servizio."},
    {"name": "generator", "description": "Endpoint espliciti per ogni funzione pubblica di python/generator.py."},
    {"name": "prolog-bridge-logic", "description": "Endpoint espliciti per i metodi logic di PrologBridge."},
    {
        "name": "prolog-bridge-equivalence",
        "description": "Endpoint espliciti per i metodi equivalence di PrologBridge.",
    },
    {"name": "prolog-bridge-rewrite", "description": "Endpoint espliciti per i metodi rewrite di PrologBridge."},
    {"name": "prolog-bridge-templates", "description": "Endpoint espliciti per i metodi templates di PrologBridge."},
    {
        "name": "prolog-bridge-distractions",
        "description": "Endpoint espliciti per i metodi distractions di PrologBridge.",
    },
]


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
    502: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


FORMULA_EXAMPLES = {
    "basic": {
        "summary": "Formula semplice",
        "value": {"expr": "and(p,q)", "timeout": 10},
    }
}

VARS_EXAMPLES = {
    "variables": {
        "summary": "Lista di variabili",
        "value": {"vars_list": ["p", "q", "r"], "timeout": 10},
    }
}

EVAL_EXAMPLES = {
    "valuation": {
        "summary": "Valutazione esplicita",
        "value": {
            "expr": "and(p,q)",
            "valuation": [{"name": "p", "value": True}, {"name": "q", "value": False}],
            "timeout": 10,
        },
    }
}

BINARY_EXAMPLES = {
    "equiv": {
        "summary": "Confronto tra due formule",
        "value": {
            "left": "imp(p,q)",
            "right": "or(not(p),q)",
            "vars_list": ["p", "q"],
            "timeout": 10,
        },
    }
}

BINARY_VALUATION_EXAMPLES = {
    "under-valuation": {
        "summary": "Confronto sotto una valutazione",
        "value": {
            "left": "and(p,q)",
            "right": "or(p,q)",
            "valuation": [{"name": "p", "value": True}, {"name": "q", "value": False}],
            "timeout": 10,
        },
    }
}

DEPTH_EXAMPLES = {
    "depth": {
        "summary": "Generazione per profondita",
        "value": {"depth": 2, "variables": ["p", "q"], "use_all": False, "seed": 42, "timeout": 10},
    }
}

DISTRACT_MAX_STEPS_EXAMPLES = {
    "max-steps": {
        "summary": "Distrazione con massimo numero di passi",
        "value": {"expr": "and(p,q)", "max_steps": 2, "timeout": 10},
    }
}

DISTRACT_EXACT_EXAMPLES = {
    "exact-steps": {
        "summary": "Distrazione con numero esatto di passi",
        "value": {"expr": "and(p,q)", "steps": 2, "timeout": 10},
    }
}

DISTRACT_N_EXAMPLES = {
    "bounded-list": {
        "summary": "Distrazioni limitate a N risultati",
        "value": {"expr": "and(p,q)", "max_steps": 2, "n": 3, "timeout": 10},
    }
}

FORMULA_PAYLOAD_EXAMPLES = {
    "payload": {
        "summary": "Payload formula con metadati extra",
        "value": {"expr": "and(p,q)", "extra": {"source": "manual"}, "timeout": 10},
    }
}

GENERATOR_EXPR_EXAMPLES = {
    "exercise-from-expr": {
        "summary": "Esercizio a partire da una formula",
        "value": {"expr": "or(p,imp(q,p))", "wrong_answers_count": 3, "seed": 42, "timeout": 10},
    }
}

GENERATOR_DEPTH_EXAMPLES = {
    "exercise-from-variables": {
        "summary": "Esercizio con variabili automatiche (profondita automatica)",
        "value": {
            "use_all": False,
            "seed": 42,
            "wrong_answers_count": 3,
            "timeout": 10,
        },
    }
}

AUTO_DEPTH_EXAMPLES = {
    "formula-from-variables": {
        "summary": "Generazione formula da variabili (profondita automatica)",
        "value": {
            "variables": ["p", "q", "r"],
            "use_all": False,
            "seed": 42,
            "timeout": 10,
        },
    }
}

TRUTH_VALUE_OPTIONS_EXAMPLES = {
    "truth-value-options": {
        "summary": "Domanda con informazioni sui predicati e opzioni vere/false",
        "value": {
            "predicate_count": 3,
            "true_options_count": 2,
            "false_options_count": 2,
            "seed": 42,
            "timeout": 10,
        },
    }
}

FORMULA_BY_VARIABLE_COUNT_EXAMPLES = {
    "formula-by-variable-count": {
        "summary": "Generazione formula con numero variabili esplicito",
        "value": {
            "variable_count": 4,
            "use_all": False,
            "seed": 42,
            "timeout": 10,
        },
    }
}

LOGICAL_CONSEQUENCE_QUESTION_EXAMPLES = {
    "logical-consequence-question": {
        "summary": "Quiz di conseguenza logica con opzioni corrette/errate",
        "value": {
            "variable_count": 4,
            "correct_options_count": 2,
            "wrong_options_count": 2,
            "allow_spoken_mode": False,
            "seed": 42,
            "timeout": 10,
        },
    }
}

TRANSLATION_QUESTION_EXAMPLES = {
    "translation-question": {
        "summary": "Quiz di traduzione italiano -> logica",
        "value": {
            "mode": "auto",
            "quantifier_ratio": 0.5,
            "wrong_options_count": 3,
            "names_pool": [
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
            ],
            "people_count": 2,
            "actions_pool": ["nuota", "corre", "salta", "guarda", "parla", "apre", "chiude", "ascolta"],
            "allow_spoken_mode": False,
            "seed": 12345,
            "timeout": 10,
        },
    }
}

MULTIPLE_QUESTIONS_EXAMPLES = {
    "batch-mixed": {
        "summary": "Batch di domande miste",
        "value": {
            "seed": 42,
            "questions": [
                {
                    "operation": "build_tvq",
                    "payload": {
                        "predicate_count": 4,
                        "true_options_count": 1,
                        "false_options_count": 1,
                        "seed": 7,
                    },
                },
                {
                    "operation": "build_translation_question",
                    "payload": {
                        "mode": "auto",
                        "quantifier_ratio": 0.5,
                        "wrong_options_count": 3,
                        "names_pool": ["Luca", "Marco"],
                        "people_count": 2,
                        "actions_pool": ["corre", "salta"],
                        "allow_spoken_mode": False,
                        "seed": 11,
                        "timeout": 10,
                    },
                },
            ],
        },
    }
}

__all__ = [
    name for name in globals() if name == "OPENAPI_TAGS" or name == "ERROR_RESPONSES" or name.endswith("_EXAMPLES")
]
