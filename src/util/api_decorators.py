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


def api_request(**kwarg_transformers):
    """
    This decorator will transform the values for the given keywords by the corresponding
    function. It will also log the request.
    @api_request(block=Block.from_blob)
    def accept_block(block):
        # do some stuff with block as Block rather than bytes
    """
    def inner(f):
        @functools.wraps(f)
        def f_substitute(*args, **kwargs):
            sig = signature(f)
            binding = sig.bind(*args, **kwargs)
            binding.apply_defaults()
            inter = transform_args(kwarg_transformers, dict(binding.arguments))
            print_args = {k: v for (k, v) in inter.items() if k != "source_connection"
                          and k != "all_connections"}
            log.info(f"{f.__name__}({print_args})")
            return f(**inter)
        return f_substitute
    return inner
