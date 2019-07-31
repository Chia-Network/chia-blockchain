import functools
from inspect import signature
import logging

log = logging.getLogger(__name__)


def transform_args(kwarg_transformers, message):
    if not isinstance(message, dict):
        return message
    new_message = dict(message)
    for k, v in kwarg_transformers.items():
        new_message[k] = v(message[k])
    return new_message


def api_request(f):
    """
    This decorator will log the request.
    @api_request
    def accept_block(block):
        # do some stuff with block as Block rather than bytes
    """
    @functools.wraps(f)
    def f_substitute(*args, **kwargs):
        sig = signature(f)
        binding = sig.bind(*args, **kwargs)
        binding.apply_defaults()
        inter = dict(binding.arguments)
        print_args = {k: v for (k, v) in inter.items() if k != "source_connection"
                      and k != "all_connections"}
        log.info(f"{f.__name__}({print_args})")
        return f(**inter)
    return f_substitute
