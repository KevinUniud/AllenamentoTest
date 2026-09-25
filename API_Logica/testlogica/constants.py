"""Centralized constants used by the generator and bridge modules.

This keeps magic numbers and defaults in one place to simplify refactors.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

# Variables and sets
DEFAULT_VARIABLES: Sequence[str] = ("p", "q", "r", "s", "t")
VAR_SET_LARGE: Sequence[str] = ("p", "q", "r", "s", "t")
VAR_SET_SMALL: Sequence[str] = ("p", "q", "r", "s")

# Formula generation limits
MAX_BINARY_OPERATORS: int = 2
DEFAULT_FORMULA_SAMPLE_LIMIT: int = 24
DEFAULT_FORMULA_FETCH_MULTIPLIER: int = 8
FORMULA_HEADS: Sequence[str] = ("and", "or", "imp", "iff", "not")
FORMULA_FETCH_CACHE_MAX: int = 64
MAX_GENERATOR_VARIABLES: int = 5
MAX_SAFE_USE_ALL_SPACE: int = 50_000
MAX_EQUIVALENCE_WRONG_OPTIONS: int = 21
MAX_EXPLICIT_EQUIVALENCE_WRONG_OPTIONS: int = 3
MAX_FORMULA_ATOM_REPETITIONS: int = 3
MAX_CONSECUTIVE_NEGATIONS: int = 2
MAX_SPOKEN_NESTED_NEGATIONS: int = 1
FORMULA_REPETITION_PROBABILITY: float = 0.5
MIN_FORMULA_ATOM_REPETITION_DISTANCE: int = 3

# Modification / distraction tuning
MAX_MODIFIED_EQUIV_CHECKS: int = 8
DISTRACTION_CANDIDATE_MULTIPLIER: int = 4
MAX_AUTOMATIC_TRANSFORM_CYCLES: int = 8
MIN_NON_TRIVIAL_CORRECT_STEPS: int = 2
DEFAULT_DISTRACTOR_MAX_STEPS: int = 2

# Exercise contracts verified by the generator stress suite.
MIN_LOGICAL_CONSEQUENCE_VARIABLES: int = 2
MAX_LOGICAL_CONSEQUENCE_VARIABLES: int = 5
MAX_LOGICAL_CONSEQUENCE_OPTIONS: int = 8
TRANSLATION_WRONG_OPTIONS: int = 3

# JSON formatting defaults
JSON_INDENT: int = 2

# Default prolog directory relative to project root (can be overridden via config)
DEFAULT_PROLOG_DIR: Path = Path(__file__).resolve().parent.parent / "prolog"
