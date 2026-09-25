% prolog/templates.pl
%
% Template strutturali per la generazione di formule ed esercizi.
%
% Convenzione formule:
%   p, q, r, ...
%   not(F)
%   and(F1,F2)
%   or(F1,F2)
%   imp(F1,F2)
%   iff(F1,F2)
%
% Funzioni esportate:
% - formula_of_depth
% - all_formulas_of_depth

:- ensure_loaded(rewrite).
:- ensure_loaded(equivalence).
:- ensure_loaded(distractions).
:- use_module(library(error)).
:- use_module(library(solution_sequences)).

% ============================================================
% Generazione formule
% ============================================================

% Precondizioni condivise
% Verifica che la profondita sia un intero non negativo.
require_depth(Depth) :-
    must_be(integer, Depth),
    Depth >= 0.

% Verifica che il limite richiesto sia positivo.
templates_require_limit(Limit) :-
    must_be(integer, Limit),
    Limit > 0.

% Verifica che le variabili siano una lista non vuota di atomi.
templates_require_vars(Vars) :-
    must_be(list, Vars),
    valid_Vars(Vars).

% Postcondizioni condivise
% Verifica che il risultato sia una lista.
templates_ensure_is_list(List) :-
    is_list(List).

% Verifica che la cardinalita del risultato non superi il limite richiesto.
templates_ensure_len_leq(List, Max) :-
    length(List, Len),
    Len =< Max.

% formula_of_depth(+Depth, +Vars, -Formula)
formula_of_depth(Depth, Vars, F) :-
    require_depth(Depth),
    templates_require_vars(Vars),
    setof(X, raw_formula_of_depth(Depth, Vars, X), Fs),
    member(F, Fs),
    nonvar(F).

all_depth(Depth, Vars, Formulas) :-
    require_depth(Depth),
    templates_require_vars(Vars),
    setof(F, raw_formula_of_depth(Depth, Vars, F), Formulas),
    templates_ensure_is_list(Formulas).

all_formulas_of_depth(Depth, Vars, Formulas) :-
    all_depth(Depth, Vars, Formulas).

same_atoms(A, B) :-
    sort(A, SA),
    sort(B, SB),
    SA == SB.

formula_uses_all_vars(Formula, Vars) :-
    vars_in_formula(Formula, UsedVars),
    same_atoms(UsedVars, Vars).

formula_has_head(Formula, Head) :-
    nonvar(Formula),
    nonvar(Head),
    ( compound(Formula) ->
        functor(Formula, Head, _)
    ;
        Head = var
    ).

all_depth_allvars(Depth, Vars, Formulas) :-
    require_depth(Depth),
    templates_require_vars(Vars),
    setof(F, (raw_formula_of_depth(Depth, Vars, F), formula_uses_all_vars(F, Vars)), Formulas),
    templates_ensure_is_list(Formulas).

all_formulas_of_depth_using_all_vars(Depth, Vars, Formulas) :-
    all_depth_allvars(Depth, Vars, Formulas).

% some_formulas_of_depth(+Depth, +Vars, +Limit, -Formulas)
some_depth(Depth, Vars, Limit, Formulas) :-
    require_depth(Depth),
    templates_require_vars(Vars),
    templates_require_limit(Limit),
    findall(
        F,
        limit(Limit, distinct(F, raw_formula_of_depth(Depth, Vars, F))),
        Formulas
    ),
    templates_ensure_is_list(Formulas),
    templates_ensure_len_leq(Formulas, Limit).

some_formulas_of_depth(Depth, Vars, Limit, Formulas) :-
    some_depth(Depth, Vars, Limit, Formulas).

some_depth_allvars(Depth, Vars, Limit, Formulas) :-
    require_depth(Depth),
    templates_require_vars(Vars),
    templates_require_limit(Limit),
    findall(
        F,
        limit(Limit, distinct(F, (raw_formula_of_depth(Depth, Vars, F), formula_uses_all_vars(F, Vars)))),
        Formulas
    ),
    templates_ensure_is_list(Formulas),
    templates_ensure_len_leq(Formulas, Limit).

some_formulas_of_depth_using_all_vars(Depth, Vars, Limit, Formulas) :-
    some_depth_allvars(Depth, Vars, Limit, Formulas).

some_depth_head(Depth, Vars, Head, Limit, Formulas) :-
    require_depth(Depth),
    templates_require_vars(Vars),
    must_be(atom, Head),
    templates_require_limit(Limit),
    findall(
        F,
        limit(
            Limit,
            distinct(
                F,
                (
                    raw_formula_of_depth_with_head(Depth, Vars, Head, F),
                    formula_uses_all_vars(F, Vars)
                )
            )
        ),
        Formulas
    ),
    templates_ensure_is_list(Formulas),
    templates_ensure_len_leq(Formulas, Limit).

some_formulas_of_depth_using_all_vars_with_head(Depth, Vars, Head, Limit, Formulas) :-
    some_depth_head(Depth, Vars, Head, Limit, Formulas).

% Variante che usa binary_subdepths_commutative_balanced per generare
% prima formule con struttura bilanciata (entrambi i sottoalberi non banali).
% Es: or(and(p,q), and(r,or(s,t))) invece di or(p, and(and(q,r),and(s,t))).
some_depth_hbal(Depth, Vars, Head, Limit, Formulas) :-
    require_depth(Depth),
    templates_require_vars(Vars),
    must_be(atom, Head),
    templates_require_limit(Limit),
    findall(
        F,
        limit(
            Limit,
            distinct(
                F,
                (
                    raw_formula_of_depth_with_head_balanced(Depth, Vars, Head, F),
                    formula_uses_all_vars(F, Vars)
                )
            )
        ),
        Formulas
    ),
    templates_ensure_is_list(Formulas),
    templates_ensure_len_leq(Formulas, Limit).

some_formulas_of_depth_using_all_vars_with_head_balanced(Depth, Vars, Head, Limit, Formulas) :-
    some_depth_hbal(Depth, Vars, Head, Limit, Formulas).

/*
Funzioni di supporto a vars_in_formula
*/

valid_Vars(Vars) :-
    is_list(Vars),
    Vars \= [],
    forall(member(A, Vars), atom(A)).

canonical_comm_args(A, B, X, Y) :-
    ( A @=< B ->
        X = A, Y = B
    ;
        X = B, Y = A
    ).

% Generates only binary-rooted formulas (and/or/iff/imp) at the requested depth.
raw_binary_formula_of_depth(Depth, Vars, Formula) :-
    member(Head, [and, or, iff, imp]),
    raw_formula_of_depth_with_head(Depth, Vars, Head, Formula).

binary_subdepths_any_order(Depth, DLeft, DRight) :-
    Max is Depth - 1,
    between(0, Max, DLeft),
    between(0, Max, DRight),
    (DLeft =:= Max ; DRight =:= Max).

% Variante bilanciata per operatori non commutativi: prova prima split dove
% entrambi i lati sono non banali, ma mantiene anche l'ordine sinistra/destra.
binary_subdepths_any_order_balanced(Depth, DLeft, DRight) :-
    Max is Depth - 1,
    Half is max(1, Max // 2),
    between(Half, Max, DLeft),
    between(Half, Max, DRight),
    (DLeft =:= Max ; DRight =:= Max).
binary_subdepths_any_order_balanced(Depth, 0, DRight) :-
    Max is Depth - 1,
    DRight is Max.
binary_subdepths_any_order_balanced(Depth, DLeft, 0) :-
    Max is Depth - 1,
    DLeft is Max.

binary_subdepths_commutative(Depth, DLeft, DRight) :-
    Max is Depth - 1,
    between(0, Max, DLeft),
    between(DLeft, Max, DRight),
    (DLeft =:= Max ; DRight =:= Max).

% Come binary_subdepths_commutative ma tenta prima le divisioni bilanciate
% (DLeft >= Max//2) per ottenere formule strutturalmente piu ricche.
% Per depth=3: prova (1,2) e (2,2) prima di (0,2).
binary_subdepths_commutative_balanced(Depth, DLeft, DRight) :-
    Max is Depth - 1,
    Half is max(1, Max // 2),
    between(Half, Max, DLeft),
    between(DLeft, Max, DRight),
    (DLeft =:= Max ; DRight =:= Max).
binary_subdepths_commutative_balanced(Depth, 0, DRight) :-
    Max is Depth - 1,
    DRight is Max.

raw_formula_of_depth(0, Vars, A) :-
    valid_Vars(Vars),
    member(A, Vars).

raw_formula_of_depth(Depth, Vars, not(F)) :-
    integer(Depth),
    Depth > 0,
    D1 is Depth - 1,
    raw_formula_of_depth(D1, Vars, F),
    \+ F = not(not(_)).

raw_formula_of_depth(Depth, Vars, and(F1c, F2c)) :-
    integer(Depth),
    Depth > 0,
    binary_subdepths_commutative(Depth, DLeft, DRight),
    raw_formula_of_depth(DLeft, Vars, F1),
    raw_formula_of_depth(DRight, Vars, F2),
    canonical_comm_args(F1, F2, F1c, F2c),
    F1c \= F2c.

raw_formula_of_depth(Depth, Vars, or(F1c, F2c)) :-
    integer(Depth),
    Depth > 0,
    binary_subdepths_commutative(Depth, DLeft, DRight),
    raw_formula_of_depth(DLeft, Vars, F1),
    raw_formula_of_depth(DRight, Vars, F2),
    canonical_comm_args(F1, F2, F1c, F2c),
    F1c \= F2c.

raw_formula_of_depth(Depth, Vars, iff(F1c, F2c)) :-
    integer(Depth),
    Depth > 0,
    binary_subdepths_commutative(Depth, DLeft, DRight),
    raw_formula_of_depth(DLeft, Vars, F1),
    raw_formula_of_depth(DRight, Vars, F2),
    canonical_comm_args(F1, F2, F1c, F2c),
    F1c \= F2c.

raw_formula_of_depth(Depth, Vars, imp(F1, F2)) :-
    integer(Depth),
    Depth > 0,
    binary_subdepths_any_order(Depth, DLeft, DRight),
    raw_formula_of_depth(DLeft, Vars, F1),
    raw_formula_of_depth(DRight, Vars, F2),
    F1 \= F2.

% Versione head-aware per evitare di enumerare tutte le formule quando
% serve campionare solo una specifica testa (and/or/imp/iff/not/var).
raw_formula_of_depth_with_head(0, Vars, var, A) :-
    valid_Vars(Vars),
    member(A, Vars).

raw_formula_of_depth_with_head(Depth, Vars, not, not(F)) :-
    integer(Depth),
    Depth > 0,
    D1 is Depth - 1,
    raw_formula_of_depth(D1, Vars, F),
    \+ F = not(not(_)).

raw_formula_of_depth_with_head(Depth, Vars, and, and(F1c, F2c)) :-
    integer(Depth),
    Depth > 0,
    binary_subdepths_commutative(Depth, DLeft, DRight),
    raw_formula_of_depth(DLeft, Vars, F1),
    raw_formula_of_depth(DRight, Vars, F2),
    canonical_comm_args(F1, F2, F1c, F2c),
    F1c \= F2c.

raw_formula_of_depth_with_head(Depth, Vars, or, or(F1c, F2c)) :-
    integer(Depth),
    Depth > 0,
    binary_subdepths_commutative(Depth, DLeft, DRight),
    raw_formula_of_depth(DLeft, Vars, F1),
    raw_formula_of_depth(DRight, Vars, F2),
    canonical_comm_args(F1, F2, F1c, F2c),
    F1c \= F2c.

raw_formula_of_depth_with_head(Depth, Vars, iff, iff(F1c, F2c)) :-
    integer(Depth),
    Depth > 0,
    binary_subdepths_commutative(Depth, DLeft, DRight),
    raw_formula_of_depth(DLeft, Vars, F1),
    raw_formula_of_depth(DRight, Vars, F2),
    canonical_comm_args(F1, F2, F1c, F2c),
    F1c \= F2c.

raw_formula_of_depth_with_head(Depth, Vars, imp, imp(F1, F2)) :-
    integer(Depth),
    Depth > 0,
    binary_subdepths_any_order(Depth, DLeft, DRight),
    raw_formula_of_depth(DLeft, Vars, F1),
    raw_formula_of_depth(DRight, Vars, F2),
    F1 \= F2.

% Versione bilanciata: tenta prima le divisioni con DLeft >= Max//2,
% producendo formule dove entrambi i rami sono strutture non banali.
raw_formula_of_depth_with_head_balanced(Depth, Vars, and, and(F1c, F2c)) :-
    integer(Depth), Depth > 0,
    binary_subdepths_commutative_balanced(Depth, DLeft, DRight),
    raw_binary_formula_of_depth(DLeft, Vars, F1),
    raw_binary_formula_of_depth(DRight, Vars, F2),
    canonical_comm_args(F1, F2, F1c, F2c),
    F1c \= F2c.

raw_formula_of_depth_with_head_balanced(Depth, Vars, or, or(F1c, F2c)) :-
    integer(Depth), Depth > 0,
    binary_subdepths_commutative_balanced(Depth, DLeft, DRight),
    raw_binary_formula_of_depth(DLeft, Vars, F1),
    raw_binary_formula_of_depth(DRight, Vars, F2),
    canonical_comm_args(F1, F2, F1c, F2c),
    F1c \= F2c.

raw_formula_of_depth_with_head_balanced(Depth, Vars, iff, iff(F1c, F2c)) :-
    integer(Depth), Depth > 0,
    binary_subdepths_commutative_balanced(Depth, DLeft, DRight),
    raw_binary_formula_of_depth(DLeft, Vars, F1),
    raw_binary_formula_of_depth(DRight, Vars, F2),
    canonical_comm_args(F1, F2, F1c, F2c),
    F1c \= F2c.

raw_formula_of_depth_with_head_balanced(Depth, Vars, imp, imp(F1, F2)) :-
    integer(Depth), Depth > 0,
    binary_subdepths_any_order_balanced(Depth, DLeft, DRight),
    raw_binary_formula_of_depth(DLeft, Vars, F1),
    raw_binary_formula_of_depth(DRight, Vars, F2),
    F1 \= F2.
