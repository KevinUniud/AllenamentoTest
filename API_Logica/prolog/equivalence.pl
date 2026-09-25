% prolog/equivalence.pl
%
% Predicati per controllare equivalenza, tautologia, contraddizione
% e soddisfacibilità di formule proposizionali.
%
% Funzioni esportate:
% - equiv
% - not_equiv
% - counterexample_equiv
% - all_models
% - all_countermodels
% - model
% - countermodel
% - tautology
% - contradiction
% - satisfiable
% - unsatisfiable
% - satisfying_assignment
% - falsifying_assignment
% - implies_formula
% - mutually_exclusive
% - jointly_satisfiable
% - same_value_under
% - different_value_under


:- ensure_loaded(logic).
:- use_module(library(error)).
:- use_module(library(apply)).

% Precondizioni condivise
% Verifica che Vars sia una lista di simboli proposizionali.
equivalence_require_vars(Vars) :-
    must_be(list, Vars),
    forall(member(A, Vars), atom(A)).

% Verifica che una valutazione sia una lista ben formata.
equivalence_require_valuation(Val) :-
    must_be(list, Val).

% Postcondizioni condivise
% Verifica che il risultato aggregato sia una lista.
equivalence_ensure_is_list(List) :-
    is_list(List).

% ============================================================
% Equivalenza logica
% ============================================================

% equiv(+F1, +F2, +Vars)
% Vero se F1 e F2 hanno lo stesso valore di verità
% per ogni assegnazione delle variabili in Vars.
% Esempio:
%   ?- equiv(and(a,b),or(a,b),[a,b]).
%   false.
%   ?- equiv(and(a,b),and(b,a),[a,b]).
%   true.
equiv(F1, F2, Vars) :-
    equivalence_require_vars(Vars),
    \+ (
        assignment(Vars, Val),
        eval(F1, Val, V1),
        eval(F2, Val, V2),
        V1 \= V2
    ).

% not_equiv(+F1, +F2, +Vars)
% Vero se esiste almeno un'assegnazione in cui F1 e F2 differiscono.
% Esempio:
%   ?- not_equiv(and(a,b),or(a,b),[a,b]).
%   true.
%   ?- not_equiv(and(a,b),and(b,a),[a,b]).
%   false.
not_equiv(F1, F2, Vars) :-
    equivalence_require_vars(Vars),
    assignment(Vars, Val),
    eval(F1, Val, V1),
    eval(F2, Val, V2),
    V1 \= V2.

% counterexample_equiv(+F1, +F2, +Vars, -Val)
% Restituisce le assegnazione che mostrano la non equivalenza.
% Esempio:
%   ?- counterexample_equiv(and(a,b),or(b,a),[a,b],V).
%   V = [a-true, b-false] ;
%   V = [a-false, b-true] ;
counterexample_equiv(F1, F2, Vars, Val) :-
    equivalence_require_vars(Vars),
    assignment(Vars, Val),
    eval(F1, Val, V1),
    eval(F2, Val, V2),
    V1 \= V2.

% ============================================================
% Modelli e contromodelli
% ============================================================

% all_models(+Formula, +Vars, -Models)
% Esempio:
%   ?- all_models(or(a,b),[a,b],M).
%   M = [[a-true, b-true], [a-true, b-false], [a-false, b-true]].
all_models(F, Vars, Models) :-
    equivalence_require_vars(Vars),
    findall(
        Val,
        model(F, Vars, Val),
        Models
    ),
    equivalence_ensure_is_list(Models).

% all_countermodels(+Formula, +Vars, -CounterModels)
% Esempio:
%   ?- all_countermodels(and(a,b),[a,b],M).
%   M = [[a-true, b-false], [a-false, b-true], [a-false, b-false]].
all_countermodels(F, Vars, CounterModels) :-
    equivalence_require_vars(Vars),
    findall(
        Val,
        countermodel(F, Vars, Val),
        CounterModels
    ),
    equivalence_ensure_is_list(CounterModels).

/*
Funzioni di supporto ad:
- all_models
- all_countermodels
*/

% model(+Formula, +Vars, -Valuation)
% Restituisce le valutazioni che rendono vera la formula.
% Esempio:
%   ?- model(and(a,b),[a,b],V).
%   V = [a-true, b-true] ;
model(F, Vars, Val) :-
    equivalence_require_vars(Vars),
    assignment(Vars, Val),
    eval(F, Val, true).

% countermodel(+Formula, +Vars, -Valuation)
% Restituisce le valutazioni che rendono falsa la formula.
% Esempio:
%   ?- countermodel(or(a,b),[a,b],V).
%   V = [a-false, b-false].
countermodel(F, Vars, Val) :-
    equivalence_require_vars(Vars),
    assignment(Vars, Val),
    eval(F, Val, false).



% ============================================================
% Tautologia / Contraddizione / Soddisfacibilità
% ============================================================

% tautology(+F, +Vars)
% Vero se F è vera per ogni assegnazione.
% Esempio:
%   ?- tautology(or(not(a),a),[a]).
%   true.
tautology(F, Vars) :-
    \+ countermodel(F, Vars, _).

% contradiction(+F, +Vars)
% Vero se F è falsa per ogni assegnazione.
% Esempio:
%   ?- contradiction(and(not(a),a),[a]).
%   true.
contradiction(F, Vars) :-
    \+ model(F, Vars, _).

% satisfiable(+F, +Vars)
% Vero se esiste almeno un'assegnazione che rende F vera.
% Esempio:
%   ?- satisfiable(and(a,b), [a,b])
%   true.
satisfiable(F, Vars) :-
    model(F, Vars, _).

% unsatisfiable(+F, +Vars)
% Sinonimo pratico di contradiction/2.
% Esempio:
%   ?- unsatisfiable(and(a,not(a)), [a]).
%   true.
unsatisfiable(F, Vars) :-
    \+ model(F, Vars, _).

% satisfying_assignment(+F, +Vars, -Val)
% Restituisce una assegnazione che rende F vera.
% Esempio:
%   ?- satisfying_assignment(and(a,b), [a,b], V).
%   X = [a-true, b-true] ;
satisfying_assignment(F, Vars, Val) :-
    assignment(Vars, Val),
    eval(F, Val, true).

% falsifying_assignment(+F, +Vars, -Val)
% Restituisce una assegnazione che rende F falsa.
% Esempio:
%   ?- falsifying_assignment(and(a,b), [a,b], V).
%   V = [a-true, b-false] ;
%   V = [a-false, b-true] ;
%   V = [a-false, b-false].
falsifying_assignment(F, Vars, Val) :-
    assignment(Vars, Val),
    eval(F, Val, false).

% ============================================================
% Relazioni logiche derivate
% ============================================================

% implies_formula(+F1, +F2, +Vars)
% Vero se F1 implica logicamente F2.
% Equivale a dire che imp(F1,F2) è una tautologia.
% Esempio:
%   ?- implies_formula(p, or(p,q), [p,q]).
%   true.
implies_formula(F1, F2, Vars) :-
    tautology(imp(F1, F2), Vars).

% mutually_exclusive(+F1, +F2, +Vars)
% Vero se F1 e F2 non possono essere entrambe vere.
% Esempio:
%   ?- mutually_exclusive(p, not(p), [p]).
%   true.
mutually_exclusive(F1, F2, Vars) :-
    contradiction(and(F1, F2), Vars).

% jointly_satisfiable(+F1, +F2, +Vars)
% Vero se esiste una assegnazione che rende vere entrambe.
% Esempio:
%   ?- jointly_satisfiable(p, q, [p,q]).
%   true.
jointly_satisfiable(F1, F2, Vars) :-
    satisfiable(and(F1, F2), Vars).

% ============================================================
% Confronto formula / formula
% ============================================================

% same_value_under(+F1, +F2, +Valuation)
% Esempio:
%   ?- same_value_under(and(a,b), or(a,b), [a-true,b-true]).
%   true ;
same_value_under(F1, F2, Val) :-
    equivalence_require_valuation(Val),
    eval(F1, Val, V),
    eval(F2, Val, V).

% different_value_under(+F1, +F2, +Valuation)
% Esempio:
%   ?- different_value_under(and(a,b), or(a,b), [a-true,b-false]).
%   true.
different_value_under(F1, F2, Val) :-
    equivalence_require_valuation(Val),
    eval(F1, Val, V1),
    eval(F2, Val, V2),
    V1 \= V2.

% ============================================================
% Utility batch
% ============================================================

is_non_equivalent_to(Fixed, Vars, Candidate) :-
    not_equiv(Fixed, Candidate, Vars).

is_equivalent_to(Fixed, Vars, Candidate) :-
    equiv(Fixed, Candidate, Vars).

% filter_non_equivalent(+Fixed, +Candidates, +Vars, -Filtered)
% Filtra i candidati restituendo solo quelli non equivalenti a Fixed.
filter_non_equivalent(Fixed, Candidates, Vars, Filtered) :-
    equivalence_require_vars(Vars),
    must_be(list, Candidates),
    include(is_non_equivalent_to(Fixed, Vars), Candidates, Filtered).

% filter_equivalent(+Fixed, +Candidates, +Vars, -Filtered)
% Filtra i candidati restituendo solo quelli equivalenti a Fixed.
filter_equivalent(Fixed, Candidates, Vars, Filtered) :-
    equivalence_require_vars(Vars),
    must_be(list, Candidates),
    include(is_equivalent_to(Fixed, Vars), Candidates, Filtered).
