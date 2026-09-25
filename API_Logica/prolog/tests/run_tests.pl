:- ensure_loaded(distractions_tests).

:- initialization(main, main).

main :-
    ( run_tests -> halt(0) ; halt(1) ).

