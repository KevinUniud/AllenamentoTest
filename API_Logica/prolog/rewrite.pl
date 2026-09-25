% prolog/rewrite.pl
%
% Riscritture equivalenti per formule proposizionali.
%
% Convenzione formule:
%   not(F)
%   and(F1,F2)
%   or(F1,F2)
%   imp(F1,F2)
%   iff(F1,F2)
%
% Questo file non valuta formule: definisce soltanto trasformazioni
% sintattiche corrette dal punto di vista logico.
%
% Funzioni esportate:
% - rewrite_formula
% - expand_implications
% - to_nnf
% - to_cnf
% - to_dnf
% - rewrite_path

:- use_module(library(solution_sequences)).

% ============================================================
% Predicato principale: singolo passo di riscrittura
% ============================================================

% rewrite_formula(+In, -Out)
% Riscrive la la formula in tutte le maniere possibili
% Esempio:
%   ?- rewrite_formula(and(or(a,b),c), X).
%   X = and(c, or(a, b)) ;
%   X = or(and(a, c), and(b, c)) ;
%   X = and(or(b, a), c) ;
rewrite_formula(In, Out) :-
    rewrite_step(In, Out).

/*
Funzioni di supporto a vars_in_formula
*/

rewrite_formula(not(F), not(F2)) :-
    rewrite_formula(F, F2).

rewrite_formula(and(A, B), and(A2, B)) :-
    rewrite_formula(A, A2).

rewrite_formula(and(A, B), and(A, B2)) :-
    rewrite_formula(B, B2).

rewrite_formula(or(A, B), or(A2, B)) :-
    rewrite_formula(A, A2).

rewrite_formula(or(A, B), or(A, B2)) :-
    rewrite_formula(B, B2).

rewrite_formula(imp(A, B), imp(A2, B)) :-
    rewrite_formula(A, A2).

rewrite_formula(imp(A, B), imp(A, B2)) :-
    rewrite_formula(B, B2).

rewrite_formula(iff(A, B), iff(A2, B)) :-
    rewrite_formula(A, A2).

rewrite_formula(iff(A, B), iff(A, B2)) :-
    rewrite_formula(B, B2).

% Regole elementari di equivalenza

% Doppia negazione
rewrite_step(not(not(F)), F).

% Eliminazione implicazione
rewrite_step(imp(A, B), or(not(A), B)).

% Eliminazione bicondizionale
rewrite_step(iff(A, B), and(imp(A, B), imp(B, A))).

% Negazione simultanea dei membri del bicondizionale
rewrite_step(iff(not(A), not(B)), iff(A, B)).
rewrite_step(iff(A, B), iff(not(A), not(B))) :-
    A \= not(_),
    B \= not(_).

% De Morgan
rewrite_step(not(and(A, B)), or(not(A), not(B))).
rewrite_step(not(or(A, B)), and(not(A), not(B))).

% De Morgan inversa. Queste forme permettono di ottenere una riscrittura
% strutturale anche quando una congiunzione/disgiunzione non contiene
% implicazioni o negazioni da semplificare.
rewrite_step(and(A, B), not(or(not(A), not(B)))).
rewrite_step(or(A, B), not(and(not(A), not(B)))).

% Commutatività
rewrite_step(and(A, B), and(B, A)).
rewrite_step(or(A, B), or(B, A)).
rewrite_step(iff(A, B), iff(B, A)).

% Associazione
rewrite_step(and(A, and(B, C)), and(and(A, B), C)).
rewrite_step(and(and(A, B), C), and(A, and(B, C))).

rewrite_step(or(A, or(B, C)), or(or(A, B), C)).
rewrite_step(or(or(A, B), C), or(A, or(B, C))).

% Distribuzione
rewrite_step(and(A, or(B, C)), or(and(A, B), and(A, C))).
rewrite_step(and(or(B, C), A), or(and(B, A), and(C, A))).

rewrite_step(or(A, and(B, C)), and(or(A, B), or(A, C))).
rewrite_step(or(and(B, C), A), and(or(B, A), or(C, A))).

% Idempotenza
rewrite_step(and(A, A), A).
rewrite_step(or(A, A), A).

% Assorbimento
rewrite_step(and(A, or(A, _)), A).
rewrite_step(and(or(A, _), A), A).

rewrite_step(or(A, and(A, _)), A).
rewrite_step(or(and(A, _), A), A).

rewrite_step(and(true, A), A).
rewrite_step(and(A, true), A).
rewrite_step(and(false, _), false).
rewrite_step(and(_, false), false).

rewrite_step(or(false, A), A).
rewrite_step(or(A, false), A).
rewrite_step(or(true, _), true).
rewrite_step(or(_, true), true).

rewrite_step(not(true), false).
rewrite_step(not(false), true).

rewrite_step(imp(true, A), A).
rewrite_step(imp(false, _), true).
rewrite_step(imp(_, true), true).
rewrite_step(imp(A, false), not(A)).

rewrite_step(iff(A, true), A).
rewrite_step(iff(true, A), A).
rewrite_step(iff(A, false), not(A)).
rewrite_step(iff(false, A), not(A)).

% Negazione complementare
rewrite_step(and(A, not(A)), false).
rewrite_step(and(not(A), A), false).

rewrite_step(or(A, not(A)), true).
rewrite_step(or(not(A), A), true).

% ============================================================
% Normalizzazione iterata
% ============================================================

% simplify_fixpoint(+In, -Out)
% Applica riscritture fino a raggiungere un punto fisso.
% Usa la prima riscrittura trovata a ogni passo.
simplify_fixpoint(In, Out) :-
    simplify_formula(In, Mid),
    !,
    simplify_fixpoint(Mid, Out).
simplify_fixpoint(F, F).

simplify_formula(In, Out) :-
    simplify_step(In, Out).

simplify_formula(not(F), not(F2)) :-
    simplify_formula(F, F2).

simplify_formula(and(A, B), and(A2, B)) :-
    simplify_formula(A, A2).
simplify_formula(and(A, B), and(A, B2)) :-
    simplify_formula(B, B2).

simplify_formula(or(A, B), or(A2, B)) :-
    simplify_formula(A, A2).
simplify_formula(or(A, B), or(A, B2)) :-
    simplify_formula(B, B2).

simplify_step(and(A, A), A).
simplify_step(or(A, A), A).

simplify_step(and(true, A), A).
simplify_step(and(A, true), A).
simplify_step(and(false, _), false).
simplify_step(and(_, false), false).

simplify_step(or(false, A), A).
simplify_step(or(A, false), A).
simplify_step(or(true, _), true).
simplify_step(or(_, true), true).

simplify_step(not(true), false).
simplify_step(not(false), true).

simplify_step(and(A, not(A)), false).
simplify_step(and(not(A), A), false).

simplify_step(or(A, not(A)), true).
simplify_step(or(not(A), A), true).

% ============================================================
% Espansioni controllate
% ============================================================

% expand_implications(+In, -Out)
% Elimina imp e iff ricorsivamente.
% Esempio:
%   ?- expand_implications(imp(iff(or(a,b),c),d), X).
%   X = or(not(and(or(not(or(a, b)), c), or(not(c), or(a, b)))), d).
expand_implications(Var, Var) :-
    atomic(Var),
    Var \= true,
    Var \= false.

/*
Funzioni di supporto a vars_in_formula
*/

expand_implications(true, true).
expand_implications(false, false).

expand_implications(not(F), not(F2)) :-
    expand_implications(F, F2).

expand_implications(and(A, B), and(A2, B2)) :-
    expand_implications(A, A2),
    expand_implications(B, B2).

expand_implications(or(A, B), or(A2, B2)) :-
    expand_implications(A, A2),
    expand_implications(B, B2).

expand_implications(imp(A, B), or(not(A2), B2)) :-
    expand_implications(A, A2),
    expand_implications(B, B2).

expand_implications(iff(A, B), and(or(not(A2), B2), or(not(B2), A2))) :-
    expand_implications(A, A2),
    expand_implications(B, B2).

% ============================================================
% Spinta della negazione verso le foglie (NNF)
% ============================================================

% to_nnf(+In, -Out)
% Converte in Negation Normal Form.
% Esempio:
%   ?- to_nnf(or(not(imp(p,q)),and(r,or(s,t))), X).
%   X = or(and(p, not(q)), and(r, or(s, t))) ;
to_nnf(F, Out) :-
    expand_implications(F, F1),
    nnf(F1, Out).

/*
Funzioni di supporto a vars_in_formula
*/

nnf(Var, Var) :-
    atomic(Var),
    Var \= true,
    Var \= false.

nnf(true, true).
nnf(false, false).

nnf(not(true), false).
nnf(not(false), true).

nnf(not(not(F)), Out) :-
    nnf(F, Out).

nnf(not(and(A, B)), or(NA, NB)) :-
    nnf(not(A), NA),
    nnf(not(B), NB).

nnf(not(or(A, B)), and(NA, NB)) :-
    nnf(not(A), NA),
    nnf(not(B), NB).

nnf(not(F), not(FN)) :-
    atomic(F),
    F \= true,
    F \= false,
    FN = F.

nnf(and(A, B), and(NA, NB)) :-
    nnf(A, NA),
    nnf(B, NB).

nnf(or(A, B), or(NA, NB)) :-
    nnf(A, NA),
    nnf(B, NB).

% ============================================================
% CNF e DNF semplici
% ============================================================

% to_cnf(+In, -Out)
% Porta una formula in una forma congiuntiva usando NNF + distribuzione.
% Esempio:
%   ?- to_cnf(or(not(imp(p,q)),and(r,or(s,t))), X).
%   X = and(and(or(p, r), or(p, or(s, t))), and(or(not(q), r), or(not(q), or(s, t)))) ;
%   X = and(and(or(p, r), or(p, or(s, t))), or(not(q), and(r, or(s, t)))) ;
%   X = and(or(p, and(r, or(s, t))), and(or(not(q), r), or(not(q), or(s, t)))) ;
%   X = and(or(p, and(r, or(s, t))), or(not(q), and(r, or(s, t)))) ;
%   X = and(and(or(p, r), or(not(q), r)), and(or(p, or(s, t)), or(not(q), or(s, t)))) ;
%   X = and(and(or(p, r), or(not(q), r)), or(and(p, not(q)), or(s, t))) ;
%   X = and(or(and(p, not(q)), r), and(or(p, or(s, t)), or(not(q), or(s, t)))) ;
%   X = and(or(and(p, not(q)), r), or(and(p, not(q)), or(s, t))) ;
%   X = or(and(p, not(q)), and(r, or(s, t))) ;
to_cnf(F, Out) :-
    to_nnf(F, NNF),
    cnf(NNF, Out0),
    simplify_fixpoint(Out0, Out).

/*
Funzioni di supporto a vars_in_formula
*/

cnf(Var, Var) :-
    atomic(Var),
    Var \= true,
    Var \= false.

cnf(true, true).
cnf(false, false).

cnf(not(F), not(F)) :-
    atomic(F).

cnf(and(A, B), and(CA, CB)) :-
    cnf(A, CA),
    cnf(B, CB).

cnf(or(A, B), Out) :-
    cnf(A, CA),
    cnf(B, CB),
    distribute_or_over_and(CA, CB, Out).

% distribute_or_over_and(+A, +B, -Out)
distribute_or_over_and(and(A, B), C, and(Out1, Out2)) :-
    distribute_or_over_and(A, C, Out1),
    distribute_or_over_and(B, C, Out2).

distribute_or_over_and(A, and(B, C), and(Out1, Out2)) :-
    distribute_or_over_and(A, B, Out1),
    distribute_or_over_and(A, C, Out2).

distribute_or_over_and(A, B, or(A, B)).

% to_dnf(+In, -Out)
% Porta una formula in forma disgiuntiva usando NNF + distribuzione duale.
% Esempio:
%   ?- to_dnf(or(not(imp(p,q)),and(r,or(s,t))), X).
%   X = or(and(p, not(q)), or(and(r, s), and(r, t))) ;
%   X = or(and(p, not(q)), and(r, or(s, t))) ;
to_dnf(F, Out) :-
    to_nnf(F, NNF),
    dnf(NNF, Out0),
    simplify_fixpoint(Out0, Out).

/*
Funzioni di supporto a vars_in_formula
*/

dnf(Var, Var) :-
    atomic(Var),
    Var \= true,
    Var \= false.

dnf(true, true).
dnf(false, false).

dnf(not(F), not(F)) :-
    atomic(F).

dnf(or(A, B), or(DA, DB)) :-
    dnf(A, DA),
    dnf(B, DB).

dnf(and(A, B), Out) :-
    dnf(A, DA),
    dnf(B, DB),
    distribute_and_over_or(DA, DB, Out).

% distribute_and_over_or(+A, +B, -Out)
distribute_and_over_or(or(A, B), C, or(Out1, Out2)) :-
    distribute_and_over_or(A, C, Out1),
    distribute_and_over_or(B, C, Out2).

distribute_and_over_or(A, or(B, C), or(Out1, Out2)) :-
    distribute_and_over_or(A, B, Out1),
    distribute_and_over_or(A, C, Out2).

distribute_and_over_or(A, B, and(A, B)).

% ============================================================
% Predicati di ispezione
% ============================================================

% rewrite_path(+In, -Path)
% Restituisce prima percorsi pedagogici di due passi e poi quelli di un
% singolo passo. La visita e limitata a formule che crescono al massimo di
% quattro nodi rispetto all'ingresso: include De Morgan inversa e
% l'eliminazione di un bicondizionale atomico, ma
% impedisce alle espansioni distributive/bicondizionali di far esplodere lo
% spazio di ricerca.
% Esempio:
%   ?- rewrite_path(and(true, not(not(p))), X).
%   X = [and(true, not(not(p))), not(not(p)), p].
rewrite_path(In, Path) :-
    formula_size(In, InitialSize),
    rewrite_path_two_steps(In, InitialSize, Path).
rewrite_path(In, [In, Out]) :-
    formula_size(In, InitialSize),
    bounded_rewrite(InitialSize, In, Out),
    Out \== In.

/*
Funzioni di supporto a vars_in_formula
*/

formula_size(F, 1) :-
    atomic(F), !.
formula_size(not(F), N) :-
    formula_size(F, N1),
    N is N1 + 1.
formula_size(and(A, B), N) :-
    formula_size(A, N1),
    formula_size(B, N2),
    N is N1 + N2 + 1.
formula_size(or(A, B), N) :-
    formula_size(A, N1),
    formula_size(B, N2),
    N is N1 + N2 + 1.
formula_size(imp(A, B), N) :-
    formula_size(A, N1),
    formula_size(B, N2),
    N is N1 + N2 + 1.
formula_size(iff(A, B), N) :-
    formula_size(A, N1),
    formula_size(B, N2),
    N is N1 + N2 + 1.

bounded_rewrite(InitialSize, In, Out) :-
    between(0, 2, Priority),
    bounded_rewrite_at_priority(Priority, InitialSize, In, Out).

bounded_rewrite_at_priority(Priority, InitialSize, In, Out) :-
    rewrite_formula(In, Out),
    Out \== In,
    formula_size(Out, OutSize),
    MaximumSize is InitialSize + 4,
    OutSize =< MaximumSize,
    formula_size(In, InSize),
    rewrite_size_priority(InSize, OutSize, Priority).

rewrite_size_priority(InSize, OutSize, 0) :-
    OutSize < InSize.
rewrite_size_priority(InSize, OutSize, 1) :-
    OutSize =:= InSize.
rewrite_size_priority(InSize, OutSize, 2) :-
    OutSize > InSize.

rewrite_path_two_steps(In, InitialSize, [In, Mid, Out]) :-
    bounded_rewrite(InitialSize, In, Mid),
    bounded_rewrite(InitialSize, Mid, Out),
    Out \== In,
    Out \== Mid.
