from clvm import run_program as default_run_program, to_sexp_f, KEYWORD_TO_ATOM  # noqa
from clvm.runtime_001 import OPERATOR_LOOKUP  # noqa
from clvm.EvalError import EvalError  # noqa
from clvm.casts import int_from_bytes, int_to_bytes  # noqa
from clvm.serialize import sexp_from_stream, sexp_to_stream  # noqa
from clvm.subclass_sexp import BaseSExp  # noqa

SExp = to_sexp_f(1).__class__


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
        program,
        args,
        quote_kw,
        args_kw,
        operator_lookup,
        max_cost,
        pre_eval_f=pre_eval_f,
    )
