"""Input normalization, invariant checks and deadline helpers."""

from __future__ import annotations

import json
import math
import random
import time
from collections.abc import Callable, Sequence
from typing import Any, cast

from .constants import DEFAULT_VARIABLES, JSON_INDENT, VAR_SET_LARGE, VAR_SET_SMALL


class GenerationDeadlineExceeded(RuntimeError):
    """La deadline complessiva della generazione è stata superata."""


def require_int_at_least(name: str, value: int, minimum: int) -> None:
    if not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} deve essere un intero >= {minimum}")


def ensure_keys(payload: dict[str, Any], required: Sequence[str]) -> None:
    missing = [key for key in required if key not in payload]
    if missing:
        raise RuntimeError(f"Output incompleto: chiavi mancanti {missing}")


def make_timeout_provider(timeout: int) -> Callable[[int | None], int]:
    deadline = time.monotonic() + max(1, int(timeout))

    def remaining_timeout(cap: int | None = None) -> int:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise GenerationDeadlineExceeded("Tempo complessivo di generazione esaurito")
        left = max(1, math.ceil(remaining))
        return min(left, cap) if cap is not None else left

    return remaining_timeout


def to_json_string(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=JSON_INDENT)


def default_vars(predicate_count: int) -> list[str]:
    if predicate_count <= 0:
        raise ValueError("predicate_count deve essere >= 1")
    if predicate_count <= len(DEFAULT_VARIABLES):
        return list(DEFAULT_VARIABLES[:predicate_count])
    return list(DEFAULT_VARIABLES) + [f"p{index}" for index in range(1, predicate_count - len(DEFAULT_VARIABLES) + 1)]


def normalize_vars(variables: Sequence[str]) -> list[str]:
    normalized = [variable for variable in dict.fromkeys(variables) if variable]
    if not normalized:
        raise ValueError("variables non può essere vuoto")
    return normalized


def max_vars_for_depth(depth: int) -> int:
    return 2**depth


def depth_from_var_count(variables_count: int) -> int:
    return 0 if variables_count <= 1 else max(2, math.ceil(math.log2(variables_count)))


def validate_vars(depth: int, variables: Sequence[str]) -> list[str]:
    normalized = normalize_vars(variables)
    maximum = max_vars_for_depth(depth)
    if len(normalized) > maximum:
        raise ValueError(
            "La profondita richiesta non consente di usare tutte le variabili fornite: "
            f"depth={depth}, variabili richieste={len(normalized)}, massimo utilizzabile={maximum}"
        )
    return normalized


def resolve_depth(depth: int | None, variables: Sequence[str]) -> tuple[int, list[str]]:
    normalized = normalize_vars(variables)
    resolved = depth_from_var_count(len(normalized)) if depth is None else depth
    if resolved < 0:
        raise ValueError("depth deve essere >= 0")
    return resolved, validate_vars(resolved, normalized)


def select_random_var_set(*, rng: random.Random, depth: int | None = None) -> tuple[str, ...]:
    candidates = [VAR_SET_LARGE, VAR_SET_SMALL]
    if depth is not None:
        candidates = [item for item in candidates if len(item) <= max_vars_for_depth(depth)]
    if not candidates:
        raise ValueError("La profondita richiesta non consente il set automatico di variabili")
    return cast(tuple[str, ...], rng.choice(candidates))
