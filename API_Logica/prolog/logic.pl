% prolog/logic.pl
%
% Valutazione di formule proposizionali.
%
% Convenzione formule:
%   not(F)
%   and(F1,F2)
%   or(F1,F2)
%   imp(F1,F2)
%   iff(F1,F2)
%
% Variabili proposizionali:
%   atomi Prolog come p, q, r, ...
%
% Valutazioni:
%   liste di coppie Var-Bool, ad esempio:
%     [p-true, q-false]
%
% Bool usati:
%   true
%   false
%
% Funzioni esportate:
% - assignment
% - eval
% - vars_in_formula
% - truth_table_auto

:- use_module(library(error)).

% Verifica che l'elenco variabili sia una lista di atomi.
logic_require_vars(Vars) :-
    must_be(list, Vars),
    forall(member(A, Vars), atom(A)).

% Verifica che una valutazione abbia formato [Var-Bool] con Bool valido.
logic_require_valuation(Val) :-
    must_be(list, Val),
    forall(member(_-B, Val), bool(B)).

% Verifica che il risultato costruito sia una lista.
logic_ensure_is_list(List) :-
    is_list(List).

% ============================================================
% Valori booleani
% ============================================================

bool(true).
bool(false).

neg(true, false).
neg(false, true).

bool_and(true, true, true).
bool_and(true, false, false).
bool_and(false, true, false).
bool_and(false, false, false).

bool_or(true, true, true).
bool_or(true, false, true).
bool_or(false, true, true).
bool_or(false, false, false).

bool_imp(true, true, true).
bool_imp(true, false, false).
bool_imp(false, true, true).
bool_imp(false, false, true).

bool_iff(true, true, true).
bool_iff(true, false, false).
bool_iff(false, true, false).
bool_iff(false, false, true).

% ============================================================
% Lookup di una variabile nella valutazione
% ============================================================

% lookup(+Var, +Valuation, -Bool)
% Cerca il valore booleano associato a Var nella valutazione.
lookup(Var, [Var-Bool | _], Bool) :-
    !.

lookup(Var, [_ | Rest], Bool) :-
    lookup(Var, Rest, Bool).

% ============================================================
% Generazione di assegnazioni
% ============================================================

% assignment(+Vars, -Valuation)
% Genera tutte le valutazioni possibili per l'elenco di variabili Vars.
% Esempio:
%   ?- assignment([p,q], V).
%   V = [p-true, q-true] ;
%   V = [p-true, q-false] ;
%   V = [p-false, q-true] ;
%   V = [p-false, q-false].
assignment([], []).

assignment([Var | Vars], [Var-Bool | Rest]) :-
    atom(Var),
    bool(Bool),
    assignment(Vars, Rest).

% ============================================================
% Valutazione delle formule
% ============================================================

% eval(+Formula, +Valuation, -Bool)
% Valuta se la formula sia true o false
% Esempio:
%   ?- eval(and(a,b),[a-false,b-true], B).
%   B = false ;

% Costanti logiche
eval(true, _Val, true) :-
    !.

eval(false, _Val, false) :-
    !.

% Variabile atomica
eval(Var, Val, Bool) :-
    atomic(Var),
    Var \= true,
    Var \= false,
    !,
    logic_require_valuation(Val),
    lookup(Var, Val, Bool).

% Negazione
eval(not(F), Val, Out) :-
    eval(F, Val, B),
    neg(B, Out).

% Congiunzione
eval(and(F1, F2), Val, Out) :-
    eval(F1, Val, B1),
    eval(F2, Val, B2),
    bool_and(B1, B2, Out).

% Disgiunzione
eval(or(F1, F2), Val, Out) :-
    eval(F1, Val, B1),
    eval(F2, Val, B2),
    bool_or(B1, B2, Out).

% Implicazione
eval(imp(F1, F2), Val, Out) :-
    eval(F1, Val, B1),
    eval(F2, Val, B2),
    bool_imp(B1, B2, Out).

% Bicondizionale
eval(iff(F1, F2), Val, Out) :-
    eval(F1, Val, B1),
    eval(F2, Val, B2),
    bool_iff(B1, B2, Out).

% ============================================================
% Predicati di supporto
% ============================================================

% vars_in_formula(+Formula, -Vars)
% Raccoglie le variabili della formula, senza duplicati e ordinate.
% Esempio:
%   ?- vars_in_formula(and(a,b), V).
%   V = [a, b].
vars_in_formula(F, Vars) :-
    vars_in_formula_raw(F, Raw),
    sort(Raw, Vars),
    logic_ensure_is_list(Vars).

/*
Funzioni di supporto a vars_in_formula
*/

vars_in_formula_raw(true, []) :-
    !.

vars_in_formula_raw(false, []) :-
    !.

vars_in_formula_raw(Var, [Var]) :-
    atomic(Var),
    !.

vars_in_formula_raw(not(F), Vars) :-
    vars_in_formula_raw(F, Vars).

vars_in_formula_raw(and(A, B), Vars) :-
    vars_in_formula_raw(A, VA),
    vars_in_formula_raw(B, VB),
    append(VA, VB, Vars).

vars_in_formula_raw(or(A, B), Vars) :-
    vars_in_formula_raw(A, VA),
    vars_in_formula_raw(B, VB),
    append(VA, VB, Vars).

vars_in_formula_raw(imp(A, B), Vars) :-
    vars_in_formula_raw(A, VA),
    vars_in_formula_raw(B, VB),
    append(VA, VB, Vars).

vars_in_formula_raw(iff(A, B), Vars) :-
    vars_in_formula_raw(A, VA),
    vars_in_formula_raw(B, VB),
    append(VA, VB, Vars).

% ============================================================
% Tabelle di verità
% ============================================================

% truth_table_auto(+Formula, -Vars, -Rows)
% Estrae automaticamente le variabili dalla formula.
% Esempio:
%   ?- truth_table_auto(and(a,b), V, R).
%   V = [a, b],
%   R = [row([a-true, b-true], true), 
%        row([a-true, b-false], false), 
%        row([a-false, b-true], false), 
%        row([a-false, b-false], false)].
truth_table_auto(F, Vars, Rows) :-
    vars_in_formula(F, Vars),
    truth_table(F, Vars, Rows),
    logic_ensure_is_list(Vars),
    logic_ensure_is_list(Rows).

/*
Funzioni di supporto a truth_table_auto
*/

% truth_row(+Formula, +Vars, -row(Valuation, Result))
truth_row(F, Vars, row(Val, Result)) :-
    logic_require_vars(Vars),
    assignment(Vars, Val),
    eval(F, Val, Result).

% truth_table(+Formula, +Vars, -Rows)
truth_table(F, Vars, Rows) :-
    logic_require_vars(Vars),
    findall(
        row(Val, Result),
        truth_row(F, Vars, row(Val, Result)),
        Rows
    ),
    logic_ensure_is_list(Rows).
