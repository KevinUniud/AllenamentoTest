:- use_module(library(http/json)).
:- use_module(library(readutil)).
:- use_module(library(time)).

reply_json(Dict) :-
    json_write_dict(current_output, Dict, [width(0)]),
    nl,
    flush_output(current_output).

rpc_error(Message) :-
    reply_json(_{ok:false, error:Message, out:""}).

run_goal_string(GoalText, Timeout, Out, Error) :-
    catch(read_term_from_atom(GoalText, Goal, []), ReadErr, (
        message_to_string(ReadErr, Msg),
        Error = Msg,
        Out = "",
        !
    )),
    ( nonvar(Error) ->
        true
    ; run_goal_term(Goal, Timeout, Out, Error)
    ).

run_goal_term(Goal, Timeout, Out, Error) :-
    catch(
        with_output_to(
            string(Out),
            call_with_time_limit(Timeout, (Goal -> true ; throw(goal_failed)))
        ),
        ExecErr,
        (
            message_to_string(ExecErr, Msg),
            Error = Msg,
            Out = ""
        )
    ),
    ( var(Error) -> Error = "" ; true ).

handle_rpc_line(Line) :-
    catch(atom_json_dict(Line, Request, [as(string)]), JsonErr, (
        message_to_string(JsonErr, Msg),
        rpc_error(Msg),
        !,
        fail
    )),
    GoalText = Request.get(goal),
    Timeout = Request.get(timeout, 10),
    run_goal_string(GoalText, Timeout, Out, Error),
    ( Error == "" ->
        reply_json(_{ok:true, out:Out})
    ;
        reply_json(_{ok:false, error:Error, out:Out})
    ).

bridge_rpc_loop :-
    set_prolog_flag(answer_write_options, [max_depth(0)]),
    repeat,
    read_line_to_string(user_input, Line),
    ( Line == end_of_file ->
        !
    ; Line == "" ->
        fail
    ; handle_rpc_line(Line),
        fail
    ).
