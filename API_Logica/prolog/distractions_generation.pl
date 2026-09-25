% Orchestrazione dei distractor, trasformazioni cicliche e raccolta dei risultati.
% Caricato da distractions.pl nello stesso modulo Prolog.

% ============================================================
% API principale
% ============================================================

% distract_formula(+Formula, +MaxSteps, -Distracted)
% Genera un singolo offuscamento casuale applicando da 1 a MaxSteps mutazioni.
% Esempio:
%   ?- distract_formula(and(p,q), 2, X).
%   X = imp(p, imp(q, q)).
distract_formula(Formula, MaxSteps, Distracted) :-
    require_formula(Formula),
    require_max_steps(MaxSteps),
    distract_trace(Formula, MaxSteps, Distracted, _),
    Distracted \= Formula.


% - distract_exactly(+Formula, +Steps, -Distracted)
% Applica esattamente Steps mutazioni, evitando cicli sulla stessa formula.
% Esempio:
%   ?- distract_exactly(and(p,q), 2, X).
%   X = or(p, q) ;
%   X = not(p) ;
%   X = imp(or(p, p), q) ;
%   X = imp(p, q) ;
%   X = not(p) ;
%   X = or(p, imp(q, q)) ;
%   X = imp(p, p) ;
%   X = and(p, p) ;
%   X = or(p, p) ;
%   X = imp(or(p, p), q) ;
%   X = or(or(p, p), q) ;
%   X = not(or(p, p)) ;
%   X = and(imp(p, p), q) ;
%   X = and(and(p, p), q) ;
%   X = and(not(p), q) ;
%   X = and(or(imp(p, p), p), q) ;
%   X = and(or(p, not(p)), q) ;
%   X = imp(p, or(q, q)) ;
%   X = or(p, or(q, q)) ;
%   X = not(p) ;
%   X = and(p, imp(q, q)) ;
%   X = and(p, and(q, q)) ;
%   X = and(p, not(q)) ;
%   X = and(p, or(q, imp(q, q))) ;
distract_exactly(Formula, Steps, Distracted) :-
    require_formula(Formula),
    require_steps(Steps),
    distract_exactly_(Steps, Formula, [Formula], Distracted),
    nonvar(Distracted).

distract_exactly_(0, Formula, _, Formula).
distract_exactly_(Steps, Formula, Seen, Distracted) :-
    Steps > 0,
    mutate_once(Formula, Mutated),
    Mutated \= Formula,
    \+ memberchk(Mutated, Seen),
    Steps1 is Steps - 1,
    distract_exactly_(Steps1, Mutated, [Mutated|Seen], Distracted).


% distract_formula_with_trace(+Formula, +MaxSteps, -Distracted, -Trace)
% Variante casuale che restituisce anche una traccia dei passi.
% Esempio:
%   ?- distract_formula_with_trace(and(p,q), 2, X, Y).
%   X = or(p, q),
%   Y = [mutate(root, and, imp, and(p, q), imp(p, q)), mutate(root, imp, or, imp(p, q), or(p, q))] ;
%   X = not(p),
%   Y = [mutate(root, and, imp, and(p, q), imp(p, q)), mutate(root, imp, not, imp(p, q), not(p))] ;
%   X = imp(and(p, p), q),
%   Y = [mutate(root, and, imp, and(p, q), imp(p, q)), mutate(atom, var, and, p, and(p, p))] ;
%   X = imp(p, q),
%   Y = [mutate(root, and, or, and(p, q), or(p, q)), mutate(root, or, imp, or(p, q), imp(p, q))] ;
%   X = not(p),
%   Y = [mutate(root, and, or, and(p, q), or(p, q)), mutate(root, or, not, or(p, q), not(p))] ;
%   X = imp(p, p),
%   Y = [mutate(root, and, not, and(p, q), not(p)), mutate(root, not, imp, not(p), imp(p, p))] ;
%   X = and(p, p),
%   Y = [mutate(root, and, not, and(p, q), not(p)), mutate(root, not, and, not(p), and(p, p))] ;
%   X = or(p, p),
%   Y = [mutate(root, and, not, and(p, q), not(p)), mutate(root, not, or, not(p), or(p, p))] ;
%   X = imp(p, not(q)),
%   Y = [mutate(atom, var, not, q, not(q)), mutate(root, and, imp, and(p, not(q)), imp(p, not(q)))] ;
%   X = or(p, not(q)),
%   Y = [mutate(atom, var, not, q, not(q)), mutate(root, and, or, and(p, not(q)), or(p, not(q)))] ;
%   X = not(p),
%   Y = [mutate(atom, var, not, q, not(q)), mutate(root, and, not, and(p, not(q)), not(p))] ;
%   X = and(or(p, p), not(q)),
%   Y = [mutate(atom, var, not, q, not(q)), mutate(atom, var, or, p, or(p, p))] ;
%   X = and(p, imp(q, q)),
%   Y = [mutate(atom, var, not, q, not(q)), mutate(root, not, imp, not(q), imp(q, q))] ;
%   X = and(p, and(q, q)),
%   Y = [mutate(atom, var, not, q, not(q)), mutate(root, not, and, not(q), and(q, q))] ;
%   X = and(p, or(q, q)),
%   Y = [mutate(atom, var, not, q, not(q)), mutate(root, not, or, not(q), or(q, q))] ;
distract_trace(Formula, MaxSteps, Distracted, Trace) :-
    require_formula(Formula),
    require_max_steps(MaxSteps),
    random_between(1, MaxSteps, Steps),
    distract_with_trace_(Steps, Formula, [Formula], Distracted, [], RevTrace),
    reverse(RevTrace, Trace),
    Distracted \= Formula,
    distractions_ensure_is_list(Trace).

distract_formula_with_trace(Formula, MaxSteps, Distracted, Trace) :-
    distract_trace(Formula, MaxSteps, Distracted, Trace).

distract_with_trace_(0, Formula, _, Formula, Trace, Trace).
distract_with_trace_(Steps, Formula, Seen, Distracted, Acc, Trace) :-
    Steps > 0,
    mutate_once_with_info(Formula, Mutated, Info),
    Mutated \= Formula,
    \+ memberchk(Mutated, Seen),
    Steps1 is Steps - 1,
    distract_with_trace_(Steps1, Mutated, [Mutated|Seen], Distracted, [Info|Acc], Trace).

% - wrap_atomic_with_operator(+Atom, +Op, -Formula)
% Trasforma un atomo in una formula usando l'operatore indicato.
% Esempi:
%   ?- wrap_atomic_with_operator(p, not, X).
%   X = not(p).
%
%   ?- wrap_atomic_with_operator(p, and, X).
%   X = and(p,p).
wrap_atomic_with_operator(Atom, not, not(Atom)).
wrap_atomic_with_operator(Atom, and, and(Atom, Atom)).
wrap_atomic_with_operator(Atom, or,  or(Atom, Atom)).
wrap_atomic_with_operator(Atom, imp, imp(Atom, Atom)).


% - random_replacement_operator(+OldOp, -NewOp)
% Sceglie un operatore diverso da OldOp tra quelli usati per gli offuscamenti.
% Esempi:
%   ?- random_replacement_operator(and, X).
%   X = imp ;
%   X = or ;
%   X = not.
random_replacement_operator(OldOp, NewOp) :-
    member(NewOp, [imp, and, or, not]),
    NewOp \= OldOp.

random_replacement_operator_once(OldOp, NewOp) :-
    findall(Op, (member(Op, [imp, and, or, not]), Op \= OldOp), Candidates),
    random_member(NewOp, Candidates).


% - maybe_mutate_here
% Predicato non deterministico: permette sia di mutare nel nodo corrente
% sia di scendere nei figli.
% Esempio d'uso:
%   ?- maybe_mutate_here.
%   true ;
%   false.
maybe_mutate_here.
maybe_mutate_here :-
    fail.

mutate_once(Formula, Mutated) :-
    mutate_once_with_info(Formula, Mutated, _).

mutate_once_with_info(Formula, Mutated, mutate(root, OpFrom, OpTo, Formula, Mutated)) :-
    compound_formula(Formula),
    maybe_mutate_here,
    top_operator(Formula, OpFrom),
    random_replacement_operator(OpFrom, OpTo),
    replace_top_operator(Formula, OpTo, Mutated).

mutate_once_with_info(Formula, Mutated, Trace) :-
    compound_formula(Formula),
    mutate_inside(Formula, Mutated, _, Trace).

mutate_once_with_info(Atom, Mutated, mutate(atom, var, OpTo, Atom, Mutated)) :-
    atomic(Atom),
    random_member(OpTo, [not, and, or, imp]),
    wrap_atomic_with_operator(Atom, OpTo, Mutated).

% recursively_change_operators(+Formula, -Mutated)
% Cambia ricorsivamente gli operatori su tutta la formula.
% Gli atomi restano invariati.
recursively_change_operators(Atom, Atom) :-
    atomic(Atom),
    !.

recursively_change_operators(not(A), Mutated) :-
    recursively_change_operators(A, AMut),
    random_replacement_operator_once(not, OpTo),
    replace_top_operator(not(AMut), OpTo, Mutated).

recursively_change_operators(and(A, B), Mutated) :-
    recursively_change_operators(A, AMut),
    recursively_change_operators(B, BMut),
    random_replacement_operator_once(and, OpTo),
    replace_top_operator(and(AMut, BMut), OpTo, Mutated).

recursively_change_operators(or(A, B), Mutated) :-
    recursively_change_operators(A, AMut),
    recursively_change_operators(B, BMut),
    random_replacement_operator_once(or, OpTo),
    replace_top_operator(or(AMut, BMut), OpTo, Mutated).

recursively_change_operators(imp(A, B), Mutated) :-
    recursively_change_operators(A, AMut),
    recursively_change_operators(B, BMut),
    random_replacement_operator_once(imp, OpTo),
    replace_top_operator(imp(AMut, BMut), OpTo, Mutated).

recursively_change_operators(iff(A, B), Mutated) :-
    recursively_change_operators(A, AMut),
    recursively_change_operators(B, BMut),
    random_replacement_operator_once(iff, OpTo),
    replace_top_operator(iff(AMut, BMut), OpTo, Mutated).

% apply_operator_cycles(+Formula, +Cycles, -Result)
% Per ogni ciclo applica una mutazione (inversione atomo inclusa)
% seguita dal cambio ricorsivo di tutti gli operatori.
apply_operator_cycles(Formula, Cycles, Result) :-
    require_formula(Formula),
    require_steps(Cycles),
    apply_operator_cycles_(Cycles, Formula, Result).

apply_operator_cycles_(0, Formula, Formula).
apply_operator_cycles_(Cycles, Formula, Result) :-
    Cycles > 0,
    once(mutate_once_with_info(Formula, Inverted, _)),
    recursively_change_operators(Inverted, Changed),
    NextCycles is Cycles - 1,
    apply_operator_cycles_(NextCycles, Changed, Result).

% ============================================================
% Trasformazioni risposta (pipeline orientata alle opzioni)
% ============================================================

maybe_swap_operands(and(A, B), and(B, A)) :-
    R is random_float,
    R < 0.5,
    !.
maybe_swap_operands(or(A, B), or(B, A)) :-
    R is random_float,
    R < 0.5,
    !.
maybe_swap_operands(Formula, Formula).

swap_and_or_children(Atom, Atom) :-
    atomic(Atom),
    !.
swap_and_or_children(not(A), not(ASwapped)) :-
    swap_and_or_children(A, ASwapped).
swap_and_or_children(and(A, B), Swapped) :-
    swap_and_or_children(A, ASwapped),
    swap_and_or_children(B, BSwapped),
    maybe_swap_operands(and(ASwapped, BSwapped), Swapped).
swap_and_or_children(or(A, B), Swapped) :-
    swap_and_or_children(A, ASwapped),
    swap_and_or_children(B, BSwapped),
    maybe_swap_operands(or(ASwapped, BSwapped), Swapped).
swap_and_or_children(imp(A, B), imp(ASwapped, BSwapped)) :-
    swap_and_or_children(A, ASwapped),
    swap_and_or_children(B, BSwapped).
swap_and_or_children(iff(A, B), iff(ASwapped, BSwapped)) :-
    swap_and_or_children(A, ASwapped),
    swap_and_or_children(B, BSwapped).

requires_extra_transform(Formula) :-
    compound_formula(Formula),
    top_operator(Formula, Op),
    member(Op, [imp, iff, not]).

answer_transform_once(Formula, Result) :-
    once(mutate_once_with_info(Formula, Mutated, _)),
    swap_and_or_children(Mutated, Swapped),
    (
        requires_extra_transform(Swapped)
    ->
        once(mutate_once_with_info(Swapped, ExtraMutated, _)),
        swap_and_or_children(ExtraMutated, Result)
    ;
        Result = Swapped
    ).

apply_answer_transform_cycles(Formula, Cycles, Result) :-
    require_formula(Formula),
    require_steps(Cycles),
    apply_answer_transform_cycles_(Cycles, Formula, Result).

apply_answer_transform_cycles_(0, Formula, Formula).
apply_answer_transform_cycles_(Cycles, Formula, Result) :-
    Cycles > 0,
    answer_transform_once(Formula, Next),
    NextCycles is Cycles - 1,
    apply_answer_transform_cycles_(NextCycles, Next, Result).

mutate_inside(and(A, B), and(AMut, B), descend(left, and), Trace) :-
    random_member(Side, [left, right]),
    Side == left,
    mutate_once_with_info(A, AMut, Trace).
mutate_inside(and(A, B), and(A, BMut), descend(right, and), Trace) :-
    random_member(Side, [left, right]),
    Side == right,
    mutate_once_with_info(B, BMut, Trace).

mutate_inside(or(A, B), or(AMut, B), descend(left, or), Trace) :-
    random_member(Side, [left, right]),
    Side == left,
    mutate_once_with_info(A, AMut, Trace).
mutate_inside(or(A, B), or(A, BMut), descend(right, or), Trace) :-
    random_member(Side, [left, right]),
    Side == right,
    mutate_once_with_info(B, BMut, Trace).

mutate_inside(imp(A, B), imp(AMut, B), descend(left, imp), Trace) :-
    random_member(Side, [left, right]),
    Side == left,
    mutate_once_with_info(A, AMut, Trace).
mutate_inside(imp(A, B), imp(A, BMut), descend(right, imp), Trace) :-
    random_member(Side, [left, right]),
    Side == right,
    mutate_once_with_info(B, BMut, Trace).

mutate_inside(iff(A, B), iff(AMut, B), descend(left, iff), Trace) :-
    random_member(Side, [left, right]),
    Side == left,
    mutate_once_with_info(A, AMut, Trace).
mutate_inside(iff(A, B), iff(A, BMut), descend(right, iff), Trace) :-
    random_member(Side, [left, right]),
    Side == right,
    mutate_once_with_info(B, BMut, Trace).

% all_distractions(+Formula, +MaxSteps, -List)
% Raccoglie tutti gli offuscamenti distinti ottenibili in 1..MaxSteps passi.
% Esempio:
%   ?- all_distractions(and(p,q), 2, X).
%   X = [not(p), not(not(p)), not(and(p, p)), not(imp(p, p)), not(or(p, p)), and(p, p), and(p, not(q)), and(p, not(...)), and(..., ...)|...].
all_distractions(Formula, MaxSteps, List) :-
    require_formula(Formula),
    require_max_steps(MaxSteps),
    setof(D, distraction_upto(Formula, MaxSteps, D), List),
    distractions_ensure_is_list(List),
    !.
all_distractions(_, _, []).


distraction_upto(Formula, MaxSteps, Distracted) :-
    between(1, MaxSteps, Steps),
    distract_exactly(Formula, Steps, Distracted).


% distract_n(+Formula, +MaxSteps, +N, -List)
% Restituisce fino a N offuscamenti distinti, senza loop infinito.
% Se esistono meno di N risultati distinti, restituisce tutti quelli disponibili.
% Esempio:
%   ?- distract_n(and(p,q), 2, 2, X).
%   X = [and(imp(imp(p, p), p), q), imp(p, imp(q, q))].
distract_n(Formula, MaxSteps, N, List) :-
    require_formula(Formula),
    require_max_steps(MaxSteps),
    distractions_require_limit(N),
    all_distractions(Formula, MaxSteps, All),
    random_permutation(All, Shuffled),
    take_up_to(N, Shuffled, List),
    distractions_ensure_is_list(List),
    distractions_ensure_len_leq(List, N).


take_up_to(0, _, []) :- !.
take_up_to(_, [], []) :- !.
take_up_to(N, [X|Xs], [X|Ys]) :-
    N > 0,
    N1 is N - 1,
    take_up_to(N1, Xs, Ys).

