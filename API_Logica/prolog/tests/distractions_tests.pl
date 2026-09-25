:- begin_tests(distractions).

:- ensure_loaded('../distractions').
:- ensure_loaded('../templates').

test(one_step_changes_formula_and_exposes_operator_swap) :-
    findall(D, one_step_distraction(and(p, q), D), Results),
    sort(Results, Unique),
    member(or(p, q), Unique),
    \+ member(and(p, q), Unique).

test(top_operator_replacement) :-
    replace_top_operator(imp(p, q), and, and(p, q)).

test(trace_reports_at_least_one_mutation) :-
    once(distract_formula_with_trace(and(p, q), 1, Distracted, Trace)),
    Distracted \= and(p, q),
    Trace = [_].

test(bounded_distractions_respect_limit) :-
    distract_n(and(p, q), 2, 2, Results),
    length(Results, Count),
    Count =< 2.

test(non_equivalence_cache_accepts_different_truth_tables) :-
    is_non_equivalent_cached(and(p, q), or(p, q), [p, q]).

test(non_equivalence_cache_rejects_equivalent_formulas, [fail]) :-
    is_non_equivalent_cached(imp(p, q), or(not(p), q), [p, q]).

test(double_negation_remains_available) :-
    once(raw_formula_of_depth(2, [p], not(not(p)))).

test(triple_negation_is_not_generated, [fail]) :-
    raw_formula_of_depth(3, [p], not(not(not(p)))).

test(head_aware_generation_rejects_triple_negation, [fail]) :-
    raw_formula_of_depth_with_head(3, [p], not, not(not(not(p)))).

test(rewrite_path_prefers_two_real_steps) :-
    once(rewrite_path(
        imp(p, q),
        [imp(p, q), or(not(p), q), or(q, not(p))]
    )).

test(rewrite_path_keeps_biconditional_elimination_reachable) :-
    once(rewrite_path(
        iff(p, q),
        [iff(p, q), and(imp(p, q), imp(q, p)), and(imp(q, p), imp(p, q))]
    )).

test(biconditional_joint_negation_is_equivalent) :-
    once(rewrite_step(iff(p, q), iff(not(p), not(q)))),
    equiv(iff(p, q), iff(not(p), not(q)), [p, q]).

test(rewrite_path_never_revisits_the_source) :-
    forall(
        rewrite_path(and(p, q), Path),
        (
            Path = [Source | Tail],
            \+ memberchk(Source, Tail)
        )
    ).

test(inverse_de_morgan_is_equivalent) :-
    once(rewrite_step(and(p, q), not(or(not(p), not(q))))),
    Rewritten = not(or(not(p), not(q))),
    equiv(and(p, q), Rewritten, [p, q]).

:- end_tests(distractions).
