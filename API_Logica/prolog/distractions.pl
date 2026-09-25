:- use_module(library(random)).
:- use_module(library(solution_sequences)).
:- use_module(library(error)).
:- ensure_loaded(equivalence).
:- dynamic non_equiv_cache/4.

non_equiv_cache_limit(4096).

% Precondizioni condivise
% Verifica che la formula di input sia valorizzata.
require_formula(F) :-
    nonvar(F).

% Verifica che il numero passi sia intero non negativo.
require_steps(Steps) :-
    must_be(integer, Steps),
    Steps >= 0.

% Verifica che max_steps sia intero positivo.
require_max_steps(MaxSteps) :-
    must_be(integer, MaxSteps),
    MaxSteps >= 1.

% Verifica che il limite numerico sia intero non negativo.
distractions_require_limit(Limit) :-
    must_be(integer, Limit),
    Limit >= 0.

% Postcondizioni condivise
% Verifica che il risultato sia una lista.
distractions_ensure_is_list(List) :-
    is_list(List).

% Verifica che la lunghezza del risultato sia entro limite.
distractions_ensure_len_leq(List, Max) :-
    length(List, Len),
    Len =< Max.

%
% Funzioni esportate:
%   distract_formula
%   distract_exactly
%   distract_formula_with_trace
%   all_distractions
%   distract_n
%   one_step_distraction
%   non_equivalent_distraction
%   all_non_equivalent_distractions

% ============================================================
% distractions.pl
% Generazione di offuscamenti / distrattori per formule logiche
% ============================================================

allowed_wrong_operator(not).
allowed_wrong_operator(and).
allowed_wrong_operator(or).
allowed_wrong_operator(imp).

compound_formula(not(_)).
compound_formula(and(_, _)).
compound_formula(or(_, _)).
compound_formula(imp(_, _)).
compound_formula(iff(_, _)).


% Le famiglie di regole sono caricate separatamente per mantenere
% distinte orchestrazione, mutazioni elementari e filtri di equivalenza.
:- ensure_loaded(distractions_generation).
:- ensure_loaded(distractions_mutations).
:- ensure_loaded(distractions_non_equivalent).
