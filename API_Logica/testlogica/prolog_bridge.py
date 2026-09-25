from __future__ import annotations

# Gestione ciclo vita bridge e serializzazione richieste/risposte RPC.
import atexit
import json
import logging

# I/O non bloccante sul processo Prolog persistente.
import select
import shutil
import subprocess
import threading
from collections.abc import Iterable, Sequence

# Cache locale per liste variabili gia normalizzate.
# stdlib
from pathlib import Path

from .config import PROLOG_DIR, SWI_PROLOG_PATH
from .prolog.codec import (
    _resolve_vars_for_binary,
    _resolve_vars_for_expr,
    from_prolog,
    prolog_term_list,
    prolog_var_list,
    to_prolog,
    valuation_to_prolog,
)
from .prolog.codec import (
    collect_variables as collect_variables,
)
from .prolog.codec import (
    formula_to_dict as formula_to_dict,
)
from .prolog.exceptions import PrologBridgeError, PrologExecutionError, PrologNotFoundError

logger = logging.getLogger(__name__)


def _req_int_ge(name: str, value: int, minimum: int):
    """Utility interna per conversione/validazione: _req_int_ge."""
    if not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} deve essere un intero >= {minimum}")


def _ensure_list_result(value, name: str):
    """Utility interna per conversione/validazione: _ensure_list_result."""
    if not isinstance(value, list):
        raise RuntimeError(f"Postcondizione fallita: {name} non e una lista")
    return value


def _as_prolog_formula(expr) -> str:
    """Valida e normalizza una formula prima di inserirla in una query Prolog.

    Anche le stringhe gia in sintassi Prolog vengono prima convertite nell'AST
    ristretto supportato dall'applicazione e poi serializzate nuovamente. In
    questo modo nessun frammento arbitrario puo essere concatenato al goal.
    """
    return to_prolog(from_prolog(expr)) if isinstance(expr, str) else to_prolog(expr)


def _as_prolog_binary(left, right) -> tuple[str, str]:
    """Normalizza una coppia di formule in stringhe Prolog."""
    return _as_prolog_formula(left), _as_prolog_formula(right)


# ============================================================
# Errori specifici
# ============================================================


class _PersistentPrologSession:
    def __init__(self, *, swipl_path: str, prolog_dir: Path, entry_file: Path, rpc_file: Path):
        """Configura una sessione SWI-Prolog persistente con lock thread-safe."""
        self.swipl_path = swipl_path
        self.prolog_dir = prolog_dir
        self.entry_file = entry_file
        self.rpc_file = rpc_file
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    def _spawn(self):
        """Avvia il processo SWI-Prolog in modalita RPC."""
        # SWI-Prolog 9 considera un solo `-s` come file script: un secondo
        # `-s` puo essere ignorato, lasciando bridge_rpc_loop/0 non definito.
        # Carichiamo quindi il server RPC come unico script e consultiamo
        # esplicitamente l'entry applicativa nel goal iniziale. json.dumps
        # produce una stringa Prolog sicura anche se il percorso contiene spazi.
        startup_goal = f"consult({json.dumps(str(self.entry_file))}),bridge_rpc_loop"
        cmd = [
            self.swipl_path,
            "-q",
            "-s",
            str(self.rpc_file),
            "-g",
            startup_goal,
        ]
        self._process = subprocess.Popen(
            cmd,
            cwd=self.prolog_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def _ensure_process(self):
        """Ritorna un processo attivo, avviandolo se necessario."""
        if self._process is None or self._process.poll() is not None:
            self._spawn()
        assert self._process is not None
        return self._process

    def query(self, goal: str, timeout: int):
        """Invia una query RPC e restituisce l'output serializzato."""
        payload = json.dumps({"goal": goal, "timeout": timeout}, ensure_ascii=True)

        with self._lock:
            process = self._ensure_process()
            if process.stdin is None or process.stdout is None:
                raise PrologExecutionError("Sessione Prolog non disponibile")

            try:
                process.stdin.write(payload + "\n")
                process.stdin.flush()
            except OSError as exc:
                self.close()
                raise PrologExecutionError(f"Errore scrittura verso SWI-Prolog: {exc}") from exc

            ready, _, _ = select.select([process.stdout], [], [], max(1, timeout + 1))
            if not ready:
                self._close_unlocked()
                raise PrologExecutionError(f"Timeout durante l'esecuzione della query Prolog: {goal}")

            line = process.stdout.readline()
            if not line:
                stderr_out = ""
                if process.stderr is not None:
                    try:
                        stderr_out = process.stderr.read().strip()
                    except OSError:
                        stderr_out = ""
                self._close_unlocked()
                raise PrologExecutionError(f"SWI-Prolog ha terminato la sessione. STDERR: {stderr_out}")

            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PrologExecutionError(f"Risposta RPC Prolog non valida: {line!r}") from exc

            if not response.get("ok", False):
                error = response.get("error", "Errore Prolog sconosciuto")
                raise PrologExecutionError(f"Errore Prolog. Goal: {goal}\nDettagli: {error}")

            return str(response.get("out", "")).strip()

    def _close_unlocked(self):
        """Chiude il processo Prolog senza acquisire il lock esterno."""
        process = self._process
        self._process = None

        if process is None:
            return

        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)

    def close(self):
        """Chiude in modo sicuro la sessione persistente."""
        with self._lock:
            self._close_unlocked()


# ============================================================
# Bridge principale
# ============================================================


class PrologBridge:
    def __init__(
        self,
        prolog_dir: str | Path | None = None,
        entry_file: str = "templates.pl",
        swipl_path: str = SWI_PROLOG_PATH,
        persistent: bool = True,
    ):
        """Wrapper bridge per la routine Prolog: __init__."""
        self.swipl_path = swipl_path
        self.persistent = persistent
        if prolog_dir is None:
            # default from config.PROLOG_DIR
            self.prolog_dir = Path(PROLOG_DIR)
        else:
            self.prolog_dir = Path(prolog_dir).resolve()
        self.entry_file = self.prolog_dir / entry_file
        self.rpc_file = self.prolog_dir / "rpc_server.pl"
        self._session: _PersistentPrologSession | None = None

    def close(self):
        """Wrapper bridge per la routine Prolog: close."""
        if self._session is not None:
            self._session.close()
            self._session = None

    def _session_query(self, goal: str, timeout: int):
        """Wrapper bridge per la routine Prolog: _session_query."""
        if self._session is None:
            self._session = _PersistentPrologSession(
                swipl_path=self.swipl_path,
                prolog_dir=self.prolog_dir,
                entry_file=self.entry_file,
                rpc_file=self.rpc_file,
            )
        return self._session.query(goal, timeout)

    def ensure_available(self):
        """Wrapper bridge per la routine Prolog: ensure_available."""
        if shutil.which(self.swipl_path) is None:
            raise PrologNotFoundError(f"SWI-Prolog non trovato. Comando atteso: {self.swipl_path!r}")
        if not self.prolog_dir.exists():
            raise PrologBridgeError(f"Directory Prolog non trovata: {self.prolog_dir}")
        if not self.entry_file.exists():
            raise PrologBridgeError(f"File Prolog principale non trovato: {self.entry_file}")
        if self.persistent and not self.rpc_file.exists():
            raise PrologBridgeError(f"File Prolog RPC non trovato: {self.rpc_file}")

    def run_query(self, goal: str, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: run_query."""
        self.ensure_available()
        wrapped_goal = f"use_module(library(http/json)), set_prolog_flag(answer_write_options,[max_depth(0)]), ({goal})"

        if self.persistent:
            return self._session_query(wrapped_goal, timeout)

        cmd = [
            self.swipl_path,
            "-q",
            "-s",
            str(self.entry_file),
            "-g",
            wrapped_goal,
            "-t",
            "halt",
        ]

        try:
            result = subprocess.run(
                cmd,
                cwd=self.prolog_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PrologExecutionError(f"Timeout durante l'esecuzione della query Prolog: {goal}") from exc
        except OSError as exc:
            raise PrologExecutionError(f"Impossibile eseguire SWI-Prolog: {exc}") from exc

        if result.returncode != 0:
            raise PrologExecutionError(
                "Errore Prolog.\n"
                f"Goal: {goal}\n"
                f"Return code: {result.returncode}\n"
                f"STDOUT:\n{result.stdout}\n"
                f"STDERR:\n{result.stderr}"
            )
        return result.stdout.strip()

    def run_json_query(self, goal: str, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: run_json_query."""
        out = self.run_query(goal, timeout=timeout)
        try:
            return json.loads(out)
        except json.JSONDecodeError as exc:
            raise PrologExecutionError(f"Output JSON non valido da Prolog: {out!r}") from exc

    def ask_bool(self, predicate_call: str, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: ask_bool."""
        out = self.run_query(f"(({predicate_call}) -> write(true) ; write(false))", timeout=timeout).strip().lower()
        if out == "true":
            return True
        if out == "false":
            return False
        raise PrologExecutionError(f"Output booleano non riconosciuto: {out!r} per query {predicate_call!r}")

    def _findall_terms(self, generator_goal: str, key: str = "items", timeout: int = 10):
        """Wrapper bridge per la routine Prolog: _findall_terms."""
        goal = (
            f"findall(OutStr, ({generator_goal}, term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{{key}:Raw}})"
        )
        return self._json_list_field(goal, key=key, timeout=timeout)

    def _json_list_field(self, goal: str, key: str, timeout: int = 10, limit: int | None = None) -> list:
        """Esegue una query JSON e restituisce il campo lista richiesto con controllo opzionale sul limite."""
        data = self.run_json_query(goal, timeout=timeout)
        out = _ensure_list_result(list(data[key]), key)
        if limit is not None and len(out) > limit:
            raise RuntimeError("Postcondizione fallita: troppi risultati")
        return out

    def _valuation_strings_expr(self, valuation_var: str, output_var: str = "ValuationStrs"):
        """Wrapper bridge per la routine Prolog: _valuation_strings_expr."""
        return f"findall(ItemStr, (member(Item, {valuation_var}), term_string(Item, ItemStr)), {output_var})"

    # ========================================================
    # logic.pl
    # ========================================================

    def assignment(self, vars_list: Iterable[str], timeout: int = 10):
        """Wrapper bridge per la routine Prolog: assignment."""
        _req_int_ge("timeout", timeout, 1)
        vars_str = prolog_var_list(list(vars_list))
        goal = (
            f"findall(ValuationStrs, (assignment({vars_str}, V), {self._valuation_strings_expr('V')}), Vs), "
            f"json_write_dict(current_output, _{{valuations:Vs}})"
        )
        return self._json_list_field(goal, key="valuations", timeout=timeout)

    def eval(self, expr, valuation: Sequence[tuple[str, bool] | str], timeout: int = 10):
        """Wrapper bridge per la routine Prolog: eval."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        valuation_str = valuation_to_prolog(valuation)
        goal = f"eval({formula}, {valuation_str}, B), write(B)"
        out = self.run_query(goal, timeout=timeout).strip().lower()
        if out == "true":
            return True
        if out == "false":
            return False
        raise PrologExecutionError(f"Output eval non riconosciuto: {out!r}")

    def vars_in_formula(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: vars_in_formula."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = f"vars_in_formula({formula}, Vars), json_write_dict(current_output, _{{vars:Vars}})"
        data = self.run_json_query(goal, timeout=timeout)
        return _ensure_list_result(list(data["vars"]), "vars")

    def truth_table_auto(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: truth_table_auto."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = (
            f"truth_table_auto({formula}, Vars, Rows), "
            f"findall(_{{valuation:ValuationStrs, result:Result}}, "
            f"(member(row(V, Result), Rows), {self._valuation_strings_expr('V')}), JsonRows), "
            f"json_write_dict(current_output, _{{vars:Vars, rows:JsonRows}})"
        )
        out = self.run_json_query(goal, timeout=timeout)
        if not isinstance(out, dict) or "vars" not in out or "rows" not in out:
            raise RuntimeError("Postcondizione fallita: truth_table_auto output non valido")
        return out

    # ========================================================
    # equivalence.pl
    # ========================================================

    def equiv(self, left, right, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: equiv."""
        _req_int_ge("timeout", timeout, 1)
        left_str, right_str = _as_prolog_binary(left, right)
        resolved_vars = _resolve_vars_for_binary(left, right, vars_list)
        return self.ask_bool(f"equiv({left_str}, {right_str}, {prolog_var_list(resolved_vars)})", timeout=timeout)

    def not_equiv(self, left, right, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: not_equiv."""
        _req_int_ge("timeout", timeout, 1)
        left_str, right_str = _as_prolog_binary(left, right)
        resolved_vars = _resolve_vars_for_binary(left, right, vars_list)
        return self.ask_bool(f"not_equiv({left_str}, {right_str}, {prolog_var_list(resolved_vars)})", timeout=timeout)

    def counterexample_equiv(self, left, right, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: counterexample_equiv."""
        _req_int_ge("timeout", timeout, 1)
        left_str, right_str = _as_prolog_binary(left, right)
        resolved_vars = _resolve_vars_for_binary(left, right, vars_list)
        variables = prolog_var_list(resolved_vars)
        goal = (
            f"findall(ValuationStrs, (counterexample_equiv({left_str}, {right_str}, {variables}, V), "
            f"{self._valuation_strings_expr('V')}), Vs), json_write_dict(current_output, _{{valuations:Vs}})"
        )
        return self._json_list_field(goal, key="valuations", timeout=timeout)

    def filter_non_equivalent(
        self,
        expr,
        candidates: Sequence[str],
        vars_list: Iterable[str] | None = None,
        timeout: int = 10,
    ) -> list[str]:
        """Wrapper bridge per la routine Prolog: filter_non_equivalent."""
        formula = _as_prolog_formula(expr)
        resolved_vars = _resolve_vars_for_expr(expr, vars_list)
        candidates_str = prolog_term_list(list(candidates))
        goal = (
            f"filter_non_equivalent({formula}, {candidates_str}, {prolog_var_list(resolved_vars)}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        return list(data["formulas"])

    def filter_equivalent(
        self,
        expr,
        candidates: Sequence[str],
        vars_list: Iterable[str] | None = None,
        timeout: int = 10,
    ) -> list[str]:
        """Wrapper bridge per la routine Prolog: filter_equivalent."""
        formula = _as_prolog_formula(expr)
        resolved_vars = _resolve_vars_for_expr(expr, vars_list)
        candidates_str = prolog_term_list(list(candidates))
        goal = (
            f"filter_equivalent({formula}, {candidates_str}, {prolog_var_list(resolved_vars)}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        return list(data["formulas"])

    def all_models(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: all_models."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        resolved_vars = _resolve_vars_for_expr(expr, vars_list)
        goal = (
            f"all_models({formula}, {prolog_var_list(resolved_vars)}, Models), "
            f"findall(ValuationStrs, (member(V, Models), {self._valuation_strings_expr('V')}), JsonModels), "
            f"json_write_dict(current_output, _{{models:JsonModels}})"
        )
        return self._json_list_field(goal, key="models", timeout=timeout)

    def all_countermodels(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: all_countermodels."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        resolved_vars = _resolve_vars_for_expr(expr, vars_list)
        goal = (
            f"all_countermodels({formula}, {prolog_var_list(resolved_vars)}, Models), "
            f"findall(ValuationStrs, (member(V, Models), {self._valuation_strings_expr('V')}), JsonModels), "
            f"json_write_dict(current_output, _{{models:JsonModels}})"
        )
        return self._json_list_field(goal, key="models", timeout=timeout)

    def model(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: model."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        resolved_vars = _resolve_vars_for_expr(expr, vars_list)
        variables = prolog_var_list(resolved_vars)
        valuation_strings = self._valuation_strings_expr("V")
        goal = (
            f"findall(ValuationStrs, (model({formula}, {variables}, V), {valuation_strings}), Vs), "
            f"json_write_dict(current_output, _{{valuations:Vs}})"
        )
        return self._json_list_field(goal, key="valuations", timeout=timeout)

    def countermodel(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: countermodel."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        resolved_vars = _resolve_vars_for_expr(expr, vars_list)
        variables = prolog_var_list(resolved_vars)
        valuation_strings = self._valuation_strings_expr("V")
        goal = (
            f"findall(ValuationStrs, (countermodel({formula}, {variables}, V), {valuation_strings}), Vs), "
            f"json_write_dict(current_output, _{{valuations:Vs}})"
        )
        return self._json_list_field(goal, key="valuations", timeout=timeout)

    def tautology(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: tautology."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        resolved_vars = _resolve_vars_for_expr(expr, vars_list)
        return self.ask_bool(f"tautology({formula}, {prolog_var_list(resolved_vars)})", timeout=timeout)

    def contradiction(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: contradiction."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        resolved_vars = _resolve_vars_for_expr(expr, vars_list)
        return self.ask_bool(f"contradiction({formula}, {prolog_var_list(resolved_vars)})", timeout=timeout)

    def satisfiable(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: satisfiable."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        resolved_vars = _resolve_vars_for_expr(expr, vars_list)
        return self.ask_bool(f"satisfiable({formula}, {prolog_var_list(resolved_vars)})", timeout=timeout)

    def unsatisfiable(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: unsatisfiable."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        resolved_vars = _resolve_vars_for_expr(expr, vars_list)
        return self.ask_bool(f"unsatisfiable({formula}, {prolog_var_list(resolved_vars)})", timeout=timeout)

    def satisfying_assignment(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: satisfying_assignment."""
        return self.model(expr, vars_list=vars_list, timeout=timeout)

    def falsifying_assignment(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: falsifying_assignment."""
        return self.countermodel(expr, vars_list=vars_list, timeout=timeout)

    def implies_formula(self, left, right, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: implies_formula."""
        _req_int_ge("timeout", timeout, 1)
        left_str, right_str = _as_prolog_binary(left, right)
        resolved_vars = _resolve_vars_for_binary(left, right, vars_list)
        return self.ask_bool(
            f"implies_formula({left_str}, {right_str}, {prolog_var_list(resolved_vars)})", timeout=timeout
        )

    def mutually_exclusive(self, left, right, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: mutually_exclusive."""
        _req_int_ge("timeout", timeout, 1)
        left_str, right_str = _as_prolog_binary(left, right)
        resolved_vars = _resolve_vars_for_binary(left, right, vars_list)
        return self.ask_bool(
            f"mutually_exclusive({left_str}, {right_str}, {prolog_var_list(resolved_vars)})", timeout=timeout
        )

    def jointly_satisfiable(self, left, right, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: jointly_satisfiable."""
        _req_int_ge("timeout", timeout, 1)
        left_str, right_str = _as_prolog_binary(left, right)
        resolved_vars = _resolve_vars_for_binary(left, right, vars_list)
        return self.ask_bool(
            f"jointly_satisfiable({left_str}, {right_str}, {prolog_var_list(resolved_vars)})", timeout=timeout
        )

    def same_value_under(self, left, right, valuation: Sequence[tuple[str, bool] | str], timeout: int = 10):
        """Wrapper bridge per la routine Prolog: same_value_under."""
        _req_int_ge("timeout", timeout, 1)
        left_str, right_str = _as_prolog_binary(left, right)
        val_str = valuation_to_prolog(valuation)
        return self.ask_bool(f"same_value_under({left_str}, {right_str}, {val_str})", timeout=timeout)

    def different_value_under(self, left, right, valuation: Sequence[tuple[str, bool] | str], timeout: int = 10):
        """Wrapper bridge per la routine Prolog: different_value_under."""
        _req_int_ge("timeout", timeout, 1)
        left_str, right_str = _as_prolog_binary(left, right)
        val_str = valuation_to_prolog(valuation)
        return self.ask_bool(f"different_value_under({left_str}, {right_str}, {val_str})", timeout=timeout)

    # ========================================================
    # rewrite.pl
    # ========================================================

    def rewrite_formula(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: rewrite_formula."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = f"rewrite_formula({formula}, Out)"
        return self._findall_terms(goal, key="formulas", timeout=timeout)

    def expand_implications(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: expand_implications."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = f"expand_implications({formula}, Out)"
        return self._findall_terms(goal, key="formulas", timeout=timeout)

    def to_nnf(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: to_nnf."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = f"to_nnf({formula}, Out)"
        return self._findall_terms(goal, key="formulas", timeout=timeout)

    def to_cnf(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: to_cnf."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = f"to_cnf({formula}, Out)"
        return self._findall_terms(goal, key="formulas", timeout=timeout)

    def to_dnf(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: to_dnf."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = f"to_dnf({formula}, Out)"
        return self._findall_terms(goal, key="formulas", timeout=timeout)

    def rewrite_paths(self, expr, timeout: int = 10):
        """Return a bounded set of continuous pedagogical rewrite paths."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = (
            f"findnsols(96, PathStrs, ("
            f"rewrite_path({formula}, Path), "
            f"findall(StepStr, (member(Step, Path), term_string(Step, StepStr)), PathStrs)"
            f"), Paths), "
            f"json_write_dict(current_output, _{{paths:Paths}})"
        )
        data = self.run_json_query(goal, timeout=timeout)

        paths = data.get("paths", [])
        if not isinstance(paths, list):
            raise RuntimeError("Postcondizione fallita: paths non e una lista")
        normalized: list[list[str]] = []
        for path in paths:
            if not isinstance(path, list):
                raise RuntimeError("Postcondizione fallita: rewrite path non e una lista")
            normalized.append([str(step) for step in path])
        return normalized

    def rewrite_path(self, expr, timeout: int = 10):
        """Compatibility wrapper returning the historical flattened path."""
        paths = self.rewrite_paths(expr, timeout=timeout)

        flattened: list[str] = []
        seen: set[str] = set()
        for path in paths:
            for step in path or []:
                if step in seen:
                    continue
                seen.add(step)
                flattened.append(step)
        return _ensure_list_result(flattened, "paths")

    # ========================================================
    # templates.pl
    # ========================================================

    def formula_of_depth(self, depth: int, vars_list: Iterable[str], timeout: int = 10):
        """Wrapper bridge per la routine Prolog: formula_of_depth."""
        _req_int_ge("depth", depth, 0)
        _req_int_ge("timeout", timeout, 1)
        vars_str = prolog_var_list(list(vars_list))
        goal = f"formula_of_depth({depth}, {vars_str}, Out)"
        return self._findall_terms(goal, key="formulas", timeout=timeout)

    def all_depth(self, depth: int, vars_list: Iterable[str], timeout: int = 10):
        """Wrapper bridge per la routine Prolog: all_depth."""
        _req_int_ge("depth", depth, 0)
        _req_int_ge("timeout", timeout, 1)
        vars_str = prolog_var_list(list(vars_list))
        goal = (
            f"all_formulas_of_depth({depth}, {vars_str}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        return self._json_list_field(goal, key="formulas", timeout=timeout)

    def all_depth_allvars(self, depth: int, vars_list: Iterable[str], timeout: int = 10):
        """Wrapper bridge per la routine Prolog: all_depth_allvars."""
        _req_int_ge("depth", depth, 0)
        _req_int_ge("timeout", timeout, 1)
        vars_str = prolog_var_list(list(vars_list))
        goal = (
            f"all_formulas_of_depth_using_all_vars({depth}, {vars_str}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        return self._json_list_field(goal, key="formulas", timeout=timeout)

    def some_depth(self, depth: int, vars_list: Iterable[str], limit: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: some_depth."""
        _req_int_ge("depth", depth, 0)
        _req_int_ge("limit", limit, 1)
        _req_int_ge("timeout", timeout, 1)
        vars_str = prolog_var_list(list(vars_list))
        goal = (
            f"some_formulas_of_depth({depth}, {vars_str}, {limit}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        return self._json_list_field(goal, key="formulas", timeout=timeout, limit=limit)

    def some_depth_allvars(
        self,
        depth: int,
        vars_list: Iterable[str],
        limit: int,
        timeout: int = 10,
    ) -> list[str]:
        """Wrapper bridge per la routine Prolog: some_depth_allvars."""
        _req_int_ge("depth", depth, 0)
        _req_int_ge("limit", limit, 1)
        _req_int_ge("timeout", timeout, 1)
        vars_str = prolog_var_list(list(vars_list))
        goal = (
            f"some_formulas_of_depth_using_all_vars({depth}, {vars_str}, {limit}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        return self._json_list_field(goal, key="formulas", timeout=timeout, limit=limit)

    def some_depth_head(
        self,
        depth: int,
        vars_list: Iterable[str],
        head: str,
        limit: int,
        timeout: int = 10,
    ) -> list[str]:
        """Wrapper bridge per la routine Prolog: some_depth_head."""
        _req_int_ge("depth", depth, 0)
        _req_int_ge("limit", limit, 1)
        _req_int_ge("timeout", timeout, 1)
        vars_str = prolog_var_list(list(vars_list))
        goal = (
            f"some_formulas_of_depth_using_all_vars_with_head({depth}, {vars_str}, '{head}', {limit}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        return self._json_list_field(goal, key="formulas", timeout=timeout, limit=limit)

    def some_depth_hbal(
        self,
        depth: int,
        vars_list: Iterable[str],
        head: str,
        limit: int,
        timeout: int = 10,
    ) -> list[str]:
        """Wrapper bridge per la routine Prolog: some_depth_hbal."""
        _req_int_ge("depth", depth, 0)
        _req_int_ge("limit", limit, 1)
        _req_int_ge("timeout", timeout, 1)
        vars_str = prolog_var_list(list(vars_list))
        goal = (
            f"some_formulas_of_depth_using_all_vars_with_head_balanced({depth}, {vars_str}, '{head}', {limit}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        return self._json_list_field(goal, key="formulas", timeout=timeout, limit=limit)

    # ========================================================
    # distractions.pl
    # ========================================================

    def distract_formula(self, expr, max_steps: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: distract_formula."""
        _req_int_ge("max_steps", max_steps, 1)
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = f"distract_formula({formula}, {max_steps}, Out)"
        return self._findall_terms(goal, key="formulas", timeout=timeout)

    def distract_exactly(self, expr, steps: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: distract_exactly."""
        _req_int_ge("steps", steps, 0)
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = f"distract_exactly({formula}, {steps}, Out)"
        return self._findall_terms(goal, key="formulas", timeout=timeout)

    def distract_trace(self, expr, max_steps: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: distract_trace."""
        _req_int_ge("max_steps", max_steps, 1)
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = (
            f"findall(_{{formula:OutStr, trace:TraceStrs}}, "
            f"(distract_formula_with_trace({formula}, {max_steps}, Out, Trace), "
            f"term_string(Out, OutStr), "
            f"findall(TraceStr, (member(TraceStep, Trace), term_string(TraceStep, TraceStr)), TraceStrs)), "
            f"Items), "
            f"json_write_dict(current_output, _{{items:Items}})"
        )
        return self._json_list_field(goal, key="items", timeout=timeout)

    def all_distractions(self, expr, max_steps: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: all_distractions."""
        _req_int_ge("max_steps", max_steps, 1)
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = f"all_distractions({formula}, {max_steps}, Out)"
        return self._findall_terms(goal, key="formulas", timeout=timeout)

    def distract_n(self, expr, max_steps: int, n: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: distract_n."""
        _req_int_ge("max_steps", max_steps, 1)
        _req_int_ge("n", n, 0)
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = (
            f"distract_n({formula}, {max_steps}, {n}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        return self._json_list_field(goal, key="formulas", timeout=timeout, limit=n)

    def one_step_distraction(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: one_step_distraction."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = f"one_step_distraction({formula}, Out)"
        return self._findall_terms(goal, key="formulas", timeout=timeout)

    def apply_operator_cycles(self, expr, cycles: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: apply_operator_cycles."""
        _req_int_ge("cycles", cycles, 0)
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = f"apply_operator_cycles({formula}, {cycles}, Out)"
        return self._findall_terms(goal, key="formulas", timeout=timeout)

    def swap_and_or_children(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: swap_and_or_children."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = f"swap_and_or_children({formula}, Out)"
        return self._findall_terms(goal, key="formulas", timeout=timeout)

    def apply_answer_transform_cycles(self, expr, cycles: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: apply_answer_transform_cycles."""
        _req_int_ge("cycles", cycles, 0)
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = f"apply_answer_transform_cycles({formula}, {cycles}, Out)"
        return self._findall_terms(goal, key="formulas", timeout=timeout)

    def one_step_neq(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: one_step_neq."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = f"one_step_non_equivalent_distraction({formula}, Out)"
        return self._findall_terms(goal, key="formulas", timeout=timeout)

    def all_step_neq(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: all_step_neq."""
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = (
            f"all_one_step_non_equivalent_distractions({formula}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        return self._json_list_field(goal, key="formulas", timeout=timeout)

    def some_step_neq(self, expr, limit: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: some_step_neq."""
        _req_int_ge("limit", limit, 1)
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = (
            f"some_one_step_non_equivalent_distractions({formula}, {limit}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        return self._json_list_field(goal, key="formulas", timeout=timeout, limit=limit)

    def non_equivalent_distraction(self, expr, max_steps: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: non_equivalent_distraction."""
        _req_int_ge("max_steps", max_steps, 1)
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = f"non_equivalent_distraction({formula}, {max_steps}, Out)"
        return self._findall_terms(goal, key="formulas", timeout=timeout)

    def all_neq(self, expr, max_steps: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: all_neq."""
        _req_int_ge("max_steps", max_steps, 1)
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = (
            f"all_non_equivalent_distractions({formula}, {max_steps}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        return self._json_list_field(goal, key="formulas", timeout=timeout)

    def some_neq(self, expr, max_steps: int, limit: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: some_neq."""
        _req_int_ge("max_steps", max_steps, 1)
        _req_int_ge("limit", limit, 1)
        _req_int_ge("timeout", timeout, 1)
        formula = _as_prolog_formula(expr)
        goal = (
            f"some_non_equivalent_distractions({formula}, {max_steps}, {limit}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        return self._json_list_field(goal, key="formulas", timeout=timeout, limit=limit)


_default_bridge: PrologBridge | None = None


def get_default_bridge():
    """Utility interna per conversione/validazione: get_default_bridge."""
    global _default_bridge
    if _default_bridge is None:
        _default_bridge = PrologBridge(entry_file="templates.pl", persistent=True)
    return _default_bridge


def _close_default_bridge():
    """Utility interna per conversione/validazione: _close_default_bridge."""
    global _default_bridge
    if _default_bridge is not None:
        _default_bridge.close()


atexit.register(_close_default_bridge)
