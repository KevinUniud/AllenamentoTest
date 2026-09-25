from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True)
class Var:
    """Nodo AST per una variabile proposizionale."""

    name: str

    def __repr__(self):
        """Restituisce la rappresentazione Prolog della variabile."""
        return self.name


@dataclass(frozen=True)
class Not:
    """Nodo AST per la negazione logica."""

    expr: object

    def __repr__(self):
        """Restituisce la rappresentazione Prolog della negazione."""
        return f"not({self.expr})"


@dataclass(frozen=True)
class And:
    """Nodo AST per la congiunzione logica."""

    left: object
    right: object

    def __repr__(self):
        """Restituisce la rappresentazione Prolog della congiunzione."""
        return f"and({self.left}, {self.right})"


@dataclass(frozen=True)
class Or:
    """Nodo AST per la disgiunzione logica."""

    left: object
    right: object

    def __repr__(self):
        """Restituisce la rappresentazione Prolog della disgiunzione."""
        return f"or({self.left}, {self.right})"


@dataclass(frozen=True)
class Imp:
    """Nodo AST per l'implicazione logica."""

    left: object
    right: object

    def __repr__(self):
        """Restituisce la rappresentazione Prolog dell'implicazione."""
        return f"imp({self.left}, {self.right})"


@dataclass(frozen=True)
class Iff:
    """Nodo AST per la doppia implicazione logica."""

    left: object
    right: object

    def __repr__(self):
        """Restituisce la rappresentazione Prolog della doppia implicazione."""
        return f"iff({self.left}, {self.right})"


Formula: TypeAlias = Var | Not | And | Or | Imp | Iff
