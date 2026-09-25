% Regole elementari di mutazione e sostituzione degli operatori.
% Caricato da distractions.pl nello stesso modulo Prolog.

% ============================================================
% Mutazioni elementari di un solo passo
% ============================================================

% one_step_distraction(+Formula, -Distracted)
% Elenca tutte le mutazioni possibili di un solo passo.
% Esempio:
%   ?- one_step_distraction(and(p,q), X).
%   X = not(p) ;
%   X = or(p, q) ;
%   X = imp(p, q) ;
%   X = and(not(p), q) ;
%   X = and(and(p, p), q) ;
%   X = and(or(p, p), q) ;
%   X = and(imp(p, p), q) ;
%   X = and(p, not(q)) ;
%   X = and(p, and(q, q)) ;
%   X = and(p, or(q, q)) ;
%   X = and(p, imp(q, q)) ;
one_step_distraction(Formula, Distracted) :-
    one_step_distraction_(Formula, Distracted),
    Distracted \= Formula.


one_step_distraction_with_trace(Atom, not(Atom), mutate(atom, var, not, Atom, not(Atom))) :-
    atomic(Atom).
one_step_distraction_with_trace(Atom, and(Atom, Atom), mutate(atom, var, and, Atom, and(Atom, Atom))) :-
    atomic(Atom).
one_step_distraction_with_trace(Atom, or(Atom, Atom), mutate(atom, var, or, Atom, or(Atom, Atom))) :-
    atomic(Atom).
one_step_distraction_with_trace(Atom, imp(Atom, Atom), mutate(atom, var, imp, Atom, imp(Atom, Atom))) :-
    atomic(Atom).

one_step_distraction_with_trace(Formula, Distracted, mutate(root, Current, NewOp, Formula, Distracted)) :-
    compound_formula(Formula),
    top_operator(Formula, Current),
    allowed_wrong_operator(NewOp),
    NewOp \= Current,
    replace_top_operator(Formula, NewOp, Distracted),
    Distracted \= Formula.

one_step_distraction_with_trace(not(A), not(DA), descend(not, Trace)) :-
    one_step_distraction_with_trace(A, DA, Trace).

one_step_distraction_with_trace(and(A, B), and(DA, B), descend(left, and, Trace)) :-
    one_step_distraction_with_trace(A, DA, Trace).
one_step_distraction_with_trace(and(A, B), and(A, DB), descend(right, and, Trace)) :-
    one_step_distraction_with_trace(B, DB, Trace).

one_step_distraction_with_trace(or(A, B), or(DA, B), descend(left, or, Trace)) :-
    one_step_distraction_with_trace(A, DA, Trace).
one_step_distraction_with_trace(or(A, B), or(A, DB), descend(right, or, Trace)) :-
    one_step_distraction_with_trace(B, DB, Trace).

one_step_distraction_with_trace(imp(A, B), imp(DA, B), descend(left, imp, Trace)) :-
    one_step_distraction_with_trace(A, DA, Trace).
one_step_distraction_with_trace(imp(A, B), imp(A, DB), descend(right, imp, Trace)) :-
    one_step_distraction_with_trace(B, DB, Trace).

one_step_distraction_with_trace(iff(A, B), iff(DA, B), descend(left, iff, Trace)) :-
    one_step_distraction_with_trace(A, DA, Trace).
one_step_distraction_with_trace(iff(A, B), iff(A, DB), descend(right, iff, Trace)) :-
    one_step_distraction_with_trace(B, DB, Trace).


one_step_distraction_(Formula, Distracted) :-
    one_step_distraction_with_trace(Formula, Distracted, _).

% ============================================================
% Sostituzione dell'operatore principale
% ============================================================

replace_top_operator(not(A), not, not(A)).
replace_top_operator(not(A), and, and(A, A)).
replace_top_operator(not(A), or,  or(A, A)).
replace_top_operator(not(A), imp, imp(A, A)).

replace_top_operator(and(A, _), not, not(A)).
replace_top_operator(or(A, _),  not, not(A)).
replace_top_operator(imp(A, _), not, not(A)).
replace_top_operator(iff(A, _), not, not(A)).

replace_top_operator(and(A, B), and, and(A, B)).
replace_top_operator(and(A, B), or,  or(A, B)).
replace_top_operator(and(A, B), imp, imp(A, B)).

replace_top_operator(or(A, B), and, and(A, B)).
replace_top_operator(or(A, B), or,  or(A, B)).
replace_top_operator(or(A, B), imp, imp(A, B)).

replace_top_operator(imp(A, B), and, and(A, B)).
replace_top_operator(imp(A, B), or,  or(A, B)).
replace_top_operator(imp(A, B), imp, imp(A, B)).

replace_top_operator(iff(A, B), and, and(A, B)).
replace_top_operator(iff(A, B), or,  or(A, B)).
replace_top_operator(iff(A, B), imp, imp(A, B)).


top_operator(not(_), not).
top_operator(and(_, _), and).
top_operator(or(_, _), or).
top_operator(imp(_, _), imp).
top_operator(iff(_, _), iff).


