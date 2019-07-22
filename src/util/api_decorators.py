import functools
from inspect import signature


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
    function.
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
            return f(**inter)
        return f_substitute
    return inner
