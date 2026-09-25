% Filtri di non-equivalenza e cache dei confronti semantici.
% Caricato da distractions.pl nello stesso modulo Prolog.

% ============================================================
% Variante che filtra le formule equivalenti
% ============================================================

% generatore interno, può produrre duplicati
non_equivalent_distraction_raw(Formula, MaxSteps, Distracted) :-
    distraction_upto(Formula, MaxSteps, Distracted),
    vars_in_formula(Formula, Vars1),
    vars_in_formula(Distracted, Vars2),
    append(Vars1, Vars2, VarsBoth),
    sort(VarsBoth, Vars),
    is_non_equivalent_cached(Formula, Distracted, Vars).

% versione pubblica senza ripetizioni
% Esempio:
%   ?- non_equivalent_distraction(and(p,q), 2, X).
%   X = not(p) ;
%   X = not(and(p, p)) ;
%   X = and(p, p) ;
%   X = and(not(p), q) ;
%   X = and(imp(p, p), q) ;
%   X = imp(p, p) ;
%   X = imp(p, q) ;
%   X = imp(and(p, p), q) ;
%   X = or(p, p) ;
%   X = or(p, q) ;
%   X = or(p, not(q)) ;
%   X = or(and(p, p), q).
non_equivalent_distraction(Formula, MaxSteps, Distracted) :-
    require_formula(Formula),
    require_max_steps(MaxSteps),
    setof(D, non_equivalent_distraction_raw(Formula, MaxSteps, D), Ds),
    member(Distracted, Ds),
    Distracted \= Formula.

% Esempio:
%   ?- all_non_equivalent_distractions(and(p,q), 2, X).
%   X = [not(p), not(not(p)), and(p, p), and(p, not(q)), and(p, imp(q, q)), and(imp(p, p), q), imp(p, p), imp(p, q), imp(..., ...)|...].
all_neq(Formula, MaxSteps, Ds) :-
    require_formula(Formula),
    require_max_steps(MaxSteps),
    setof(D, non_equivalent_distraction_raw(Formula, MaxSteps, D), Ds),
    distractions_ensure_is_list(Ds),
    !.
all_neq(_, _, []).

all_non_equivalent_distractions(Formula, MaxSteps, Ds) :-
    all_neq(Formula, MaxSteps, Ds).


% ============================================================
% Variante rapida: distractor non equivalenti in un solo passo
% ============================================================

one_step_neq(Formula, Distracted) :-
    require_formula(Formula),
    setof(D, one_step_non_equivalent_distraction_raw(Formula, D), Ds),
    member(Distracted, Ds),
    Distracted \= Formula.

one_step_non_equivalent_distraction(Formula, Distracted) :-
    one_step_neq(Formula, Distracted).

all_step_neq(Formula, Ds) :-
    require_formula(Formula),
    setof(D, one_step_non_equivalent_distraction_raw(Formula, D), Ds),
    distractions_ensure_is_list(Ds),
    !.
all_step_neq(_, []).

all_one_step_non_equivalent_distractions(Formula, Ds) :-
    all_step_neq(Formula, Ds).

% some_one_step_non_equivalent_distractions(+Formula, +Limit, -Ds)
% Restituisce al massimo Limit distractor non equivalenti a un passo.
some_step_neq(Formula, Limit, Ds) :-
    require_formula(Formula),
    must_be(integer, Limit),
    Limit > 0,
    findall(
        D,
        limit(Limit, distinct(D, one_step_non_equivalent_distraction_raw(Formula, D))),
        Ds
    ),
    distractions_ensure_is_list(Ds),
    distractions_ensure_len_leq(Ds, Limit).

some_one_step_non_equivalent_distractions(Formula, Limit, Ds) :-
    some_step_neq(Formula, Limit, Ds).

% some_non_equivalent_distractions(+Formula, +MaxSteps, +Limit, -Ds)
% Restituisce al massimo Limit distractor non equivalenti entro MaxSteps.
some_neq(Formula, MaxSteps, Limit, Ds) :-
    require_formula(Formula),
    require_max_steps(MaxSteps),
    must_be(integer, Limit),
    Limit > 0,
    findall(
        D,
        limit(Limit, distinct(D, non_equivalent_distraction_raw(Formula, MaxSteps, D))),
        Ds
    ),
    distractions_ensure_is_list(Ds),
    distractions_ensure_len_leq(Ds, Limit).

some_non_equivalent_distractions(Formula, MaxSteps, Limit, Ds) :-
    some_neq(Formula, MaxSteps, Limit, Ds).

one_step_non_equivalent_distraction_raw(Formula, Distracted) :-
    one_step_distraction(Formula, Distracted),
    vars_in_formula(Formula, Vars),
    is_non_equivalent_cached(Formula, Distracted, Vars).

% ============================================================
% Cache equivalenza/non-equivalenza
% ============================================================

cache_key(F1, F2, Vars, A, B, VarsSorted) :-
    sort(Vars, VarsSorted),
    ( F1 @=< F2 ->
        A = F1,
        B = F2
    ;
        A = F2,
        B = F1
    ).

trim_non_equiv_cache_if_needed :-
    non_equiv_cache_limit(Limit),
    aggregate_all(count, non_equiv_cache(_, _, _, _), Count),
    ( Count =< Limit ->
        true
    ;
        retractall(non_equiv_cache(_, _, _, _))
    ).

is_non_equivalent_cached(F1, F2, Vars) :-
    cache_key(F1, F2, Vars, A, B, VarsSorted),
    ( non_equiv_cache(A, B, VarsSorted, Result) ->
        Result = true
    ;
        ( equiv(F1, F2, VarsSorted) ->
            Result = false
        ;
            Result = true
        ),
        trim_non_equiv_cache_if_needed,
        assertz(non_equiv_cache(A, B, VarsSorted, Result)),
        Result = true
    ).
