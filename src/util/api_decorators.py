import functools
import logging
from inspect import signature

log = logging.getLogger(__name__)


def api_request(f):
    @functools.wraps(f)
    def f_substitute(*args, **kwargs):
        sig = signature(f)
        binding = sig.bind(*args, **kwargs)
        binding.apply_defaults()
        inter = dict(binding.arguments)

        # Converts each parameter from a Python dictionary, into an instance of the object
        # specified by the type annotation (signature) of the function that is being called (f)
        # The method can also be called with the target type instead of a dictionary.
        for param_name, param_class in f.__annotations__.items():
            if param_name != "return" and isinstance(inter[param_name], bytes):
                inter[param_name] = param_class.from_bytes(inter[param_name])

        return f(**inter)

    setattr(f_substitute, "api_function", True)
    return f_substitute


def peer_required(func):
    def inner():
        setattr(func, "peer_required", True)
        return func

    return inner()
