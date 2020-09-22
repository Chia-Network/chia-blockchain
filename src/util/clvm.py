from clvm.casts import int_from_bytes, int_to_bytes  # noqa
from clvm.serialize import sexp_from_stream, sexp_to_stream  # noqa


def run_program(
    program,
    args,
    quote_kw=KEYWORD_TO_ATOM["q"],
    args_kw=KEYWORD_TO_ATOM["a"],
    operator_lookup=OPERATOR_LOOKUP,
    max_cost=None,
    pre_eval_f=None,
):
    return default_run_program(
        program, args, quote_kw, operator_lookup, max_cost, pre_eval_f=pre_eval_f,
    )
